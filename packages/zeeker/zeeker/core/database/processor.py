"""
Resource processing for Zeeker database operations.

This module handles loading resource modules, executing data functions,
applying transformations, and inserting data into SQLite databases.
"""

import copy
import importlib.util
import inspect
import sqlite3
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

import sqlite_utils

from ..schema import SchemaManager
from ..types import Skip, ValidationResult
from .async_executor import AsyncExecutor


class ResourceProcessor:
    """Handles processing of individual resources and fragments."""

    def __init__(self, resources_path: Path, schema_manager: SchemaManager):
        """Initialize resource processor.

        Args:
            resources_path: Path to resources directory
            schema_manager: Schema manager instance for tracking
        """
        self.resources_path = resources_path
        self.schema_manager = schema_manager
        self.async_executor = AsyncExecutor()
        # Per-build cache of loaded resource modules, keyed by resource name.
        # Guarantees each resource module is imported exactly once per build,
        # including under parallel pre-warm (the pre-warm and the sequential
        # loop must operate on the SAME module instance so module-level state
        # written by fetch_data survives into the fragments phase).
        self._module_cache: Dict[str, Any] = {}
        # Sibling modules (helpers in resources/) registered in sys.modules
        # during resource loads, keyed by module name. Tracked so they can be
        # purged between builds — otherwise two projects with a same-named
        # helper (e.g. resources/extraction.py) would silently share the
        # first project's module in a long-lived process.
        self._sibling_modules: Dict[str, Any] = {}

    def clear_build_caches(self) -> None:
        """Drop all per-build state. Call when a build finishes.

        Clears the loaded-module cache, unregisters sibling helper modules
        from sys.modules (only if they are still the objects we loaded), and
        clears the executor's fetch cache and pre-warmed data.
        """
        self._module_cache.clear()
        for name, mod in self._sibling_modules.items():
            if sys.modules.get(name) is mod:
                del sys.modules[name]
        self._sibling_modules.clear()
        self.async_executor.clear_prewarmed()
        self.async_executor.clear_fetch_cache()

    def process_resource(
        self, db: sqlite_utils.Database, resource_name: str, module: Any = None
    ) -> ValidationResult:
        """Process a single resource using sqlite-utils for robust data insertion.

        Args:
            db: sqlite-utils Database instance
            resource_name: Name of the resource to process
            module: Pre-loaded resource module (optional, loaded if not provided)

        Returns:
            ValidationResult with processing results
        """
        result = ValidationResult(is_valid=True)

        # Load module if not provided
        if module is None:
            module_result = self._load_resource_module(resource_name)
            if not module_result.is_valid:
                return module_result
            module = module_result.data

        try:
            # Get the fetch_data function
            if not hasattr(module, "fetch_data"):
                result.is_valid = False
                result.errors.append(f"Resource '{resource_name}' missing fetch_data() function")
                return result

            fetch_data = getattr(module, "fetch_data")

            # Check if table already exists to pass to fetch_data
            existing_table = db[resource_name] if db[resource_name].exists() else None

            # Fetch the data. A resource may raise Skip(reason, kind=...)
            # instead of returning [] to declare WHY it is skipping
            # (up_to_date vs blocked vs disabled).
            try:
                raw_data = self.async_executor.call_fetch_data(
                    fetch_data, existing_table, resource_name=resource_name
                )
            except Skip as skip:
                result.skipped = True
                result.skip_reason = skip.reason
                result.skip_kind = skip.kind
                # An empty context is a valid fragments context (same shape
                # as a returned-[] skip with fragments_on_skip).
                result.raw_data = []
                result.info.append(
                    f"Resource '{resource_name}' skipped ({skip.kind}): {skip.reason}"
                )
                return result

            if not isinstance(raw_data, list):
                result.is_valid = False
                result.errors.append(f"fetch_data() in '{resource_name}' must return a list")
                return result

            # Expose the raw fetch output so the builder can thread it into
            # the fragments phase as main_data_context without re-running
            # fetch_data(). When a transform exists, snapshot with deepcopy
            # first: transform_data() commonly mutates rows in place, and the
            # fragments phase is documented to receive the PRE-transform data.
            if hasattr(module, "transform_data"):
                result.raw_data = copy.deepcopy(raw_data)
            else:
                result.raw_data = raw_data

            if not raw_data:
                result.skipped = True
                result.skip_kind = "up_to_date"
                result.info.append(f"No data returned for resource '{resource_name}' - skipping")
                return result

            # Apply transformation if available
            transformed_data, transform_tb = self._apply_transformation(
                module, raw_data, resource_name, "transform_data"
            )
            if transformed_data is None:
                result.is_valid = False
                result.errors.append(f"Data transformation failed for '{resource_name}'")
                if transform_tb:
                    result.tracebacks.append(transform_tb)
                return result

            # Validate transformed data structure
            validation_result = self._validate_data_structure(transformed_data, resource_name)
            if not validation_result.is_valid:
                return validation_result

            # Insert data using sqlite-utils
            table = db[resource_name]

            # Track schema for conflict detection
            if not existing_table:  # New table
                self.schema_manager.track_new_table_schema(db, resource_name, transformed_data)

            # Insert all data at once for better performance
            table.insert_all(transformed_data, replace=False)

            result.records = len(transformed_data)
            result.info.append(
                f"Processed {len(transformed_data)} records for resource '{resource_name}'"
            )

        except sqlite3.IntegrityError as e:
            result.is_valid = False
            result.errors.append(f"Database integrity error in '{resource_name}': {e}")
            result.tracebacks.append(traceback.format_exc())
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to process resource '{resource_name}': {e}")
            result.tracebacks.append(traceback.format_exc())
        finally:
            # Optional counters reported by the resource (module-level
            # __zeeker_report__): consumed on EVERY exit path — success,
            # skip (returned [] or raised Skip), transform, and failure —
            # so enrichment work committed before a crash is still visible
            # and the attribute never goes stale on the cached module.
            self._consume_zeeker_report(module, result)

        return result

    def _consume_zeeker_report(self, module: Any, result: ValidationResult) -> None:
        """Read (and clear) an optional module-level ``__zeeker_report__`` dict.

        Resources may report enrichment/update counters that don't show up as
        inserted rows, e.g.::

            def fetch_data(existing_table):
                global __zeeker_report__
                __zeeker_report__ = {"updated": 50, "enriched": 25,
                                     "notes": "phase2 drained 25"}
                return []

        Validation is deliberately lenient: non-int values are ignored (except
        the optional ``notes`` string) and a malformed report never fails the
        build. The attribute is deleted after reading so a reused module can't
        leak stale counts into a later resource or build.

        Counts MERGE into ``result.extra_counts`` (summing on key collision)
        so a second consumption — e.g. after the fragments phase, where
        fetch_fragments_data may have set fresh counters — accumulates rather
        than overwrites.
        """
        try:
            report = getattr(module, "__zeeker_report__", None)
            if report is None:
                return
            try:
                delattr(module, "__zeeker_report__")
            except Exception:
                pass
            if not isinstance(report, dict):
                return
            counts: Dict[str, int] = {}
            notes = None
            for key, value in report.items():
                if not isinstance(key, str):
                    continue
                if key == "notes":
                    if isinstance(value, str):
                        notes = value
                    continue
                if isinstance(value, bool):
                    continue  # bools are ints in Python; not meaningful counts
                if isinstance(value, int):
                    counts[key] = value
            for key, value in counts.items():
                result.extra_counts[key] = result.extra_counts.get(key, 0) + value
            if notes:
                result.notes = f"{result.notes}; {notes}" if result.notes else notes
        except Exception:
            # Defensive: a broken report must never fail the build.
            pass

    def process_fragments_data(
        self,
        db: sqlite_utils.Database,
        resource_name: str,
        module: Any,
        main_data_context: List[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Process fragments data for a resource that supports document fragmentation.

        Args:
            db: sqlite-utils Database instance
            resource_name: Name of the main resource
            module: The imported resource module
            main_data_context: Raw data from fetch_data() to avoid duplicate fetches (optional)

        Returns:
            ValidationResult with processing results
        """
        result = ValidationResult(is_valid=True)
        fragments_table_name = f"{resource_name}_fragments"

        try:
            if not hasattr(module, "fetch_fragments_data"):
                result.is_valid = False
                result.errors.append(
                    f"Resource '{resource_name}' missing fetch_fragments_data() function"
                )
                return result

            fetch_fragments_data = getattr(module, "fetch_fragments_data")

            # Check if fragments table already exists
            existing_fragments_table = (
                db[fragments_table_name] if db[fragments_table_name].exists() else None
            )

            # Fetch fragments data with optional main data context. A
            # fetch_fragments_data that raises Skip declares a graceful
            # no-fragments skip (e.g. its enrichment proxy is down) — honor
            # it instead of flipping the resource to "failed".
            try:
                raw_fragments = self._call_fragments_function(
                    fetch_fragments_data, existing_fragments_table, main_data_context
                )
            except Skip as skip:
                result.info.append(
                    f"Fragments for '{resource_name}' skipped ({skip.kind}): {skip.reason}"
                )
                return result

            if not isinstance(raw_fragments, list):
                result.is_valid = False
                result.errors.append(
                    f"fetch_fragments_data() in '{resource_name}' must return a list"
                )
                return result

            if not raw_fragments:
                result.info.append(f"No fragments data for '{resource_name}' - skipping")
                return result

            # Apply transformation if available
            transformed_fragments, transform_tb = self._apply_transformation(
                module, raw_fragments, resource_name, "transform_fragments_data"
            )
            if transformed_fragments is None:
                result.is_valid = False
                result.errors.append(f"Fragment transformation failed for '{resource_name}'")
                if transform_tb:
                    result.tracebacks.append(transform_tb)
                return result

            # Validate fragments data structure
            validation_result = self._validate_data_structure(
                transformed_fragments, f"{resource_name} fragments"
            )
            if not validation_result.is_valid:
                return validation_result

            # Insert fragments data using sqlite-utils
            fragments_table = db[fragments_table_name]

            # Track schema for conflict detection
            if not existing_fragments_table:  # New table
                self.schema_manager.track_new_table_schema(
                    db, fragments_table_name, transformed_fragments
                )

            # Insert all fragments at once for better performance
            fragments_table.insert_all(transformed_fragments, replace=False)

            result.records = len(transformed_fragments)
            result.info.append(
                f"Processed {len(transformed_fragments)} fragments for resource '{resource_name}'"
            )

        except sqlite3.IntegrityError as e:
            result.is_valid = False
            result.errors.append(f"Database integrity error in '{resource_name}' fragments: {e}")
            result.tracebacks.append(traceback.format_exc())
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to process fragments for '{resource_name}': {e}")
            result.tracebacks.append(traceback.format_exc())

        return result

    def _load_resource_module(self, resource_name: str) -> ValidationResult:
        """Load a resource module dynamically.

        Args:
            resource_name: Name of the resource to load

        Returns:
            ValidationResult with module in data field if successful
        """
        result = ValidationResult(is_valid=True)

        # Serve from the per-build cache: each resource module must be
        # imported exactly once per build (parallel pre-warm and the
        # sequential loop must share the same instance so module-level
        # state written by fetch_data reaches the fragments phase).
        cached = self._module_cache.get(resource_name)
        if cached is not None:
            result.data = cached
            return result

        resource_file = self.resources_path / f"{resource_name}.py"
        if not resource_file.exists():
            result.is_valid = False
            result.errors.append(f"Resource file not found: {resource_file}")
            return result

        # Make sibling modules in resources/ importable (e.g.
        # ``import extraction`` from resources/judgments.py). Resource
        # modules are loaded by file path with no package context, so
        # without this, sibling imports require a manual sys.path shim
        # in every resource file. The directory is APPENDED (lowest
        # precedence, so resources/*.py can never shadow stdlib or
        # site-packages) and removed again after the load — sibling
        # imports therefore must happen at module top level.
        resources_dir = str(self.resources_path)
        path_added = resources_dir not in sys.path
        if path_added:
            sys.path.append(resources_dir)
        modules_before = set(sys.modules)

        try:
            # Dynamically import the resource module
            spec = importlib.util.spec_from_file_location(resource_name, resource_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result.data = module
            self._module_cache[resource_name] = module

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to load resource module '{resource_name}': {e}")
            result.tracebacks.append(traceback.format_exc())

        finally:
            if path_added and resources_dir in sys.path:
                sys.path.remove(resources_dir)
            # Track sibling modules that landed in sys.modules from
            # resources/ so clear_build_caches() can purge them — they must
            # not leak into other projects' builds in the same process.
            for name in set(sys.modules) - modules_before:
                mod = sys.modules.get(name)
                mod_file = getattr(mod, "__file__", None)
                if not mod_file:
                    continue
                try:
                    if Path(mod_file).resolve().is_relative_to(Path(resources_dir).resolve()):
                        self._sibling_modules[name] = mod
                except (OSError, ValueError):
                    continue

        return result

    def _call_fragments_function(
        self,
        fetch_fragments_data,
        existing_fragments_table,
        main_data_context,
    ) -> List[Dict[str, Any]]:
        """Call fetch_fragments_data with proper signature handling."""
        sig = inspect.signature(fetch_fragments_data)

        if len(sig.parameters) >= 2 and main_data_context is not None:
            # Enhanced signature: fetch_fragments_data(existing_fragments_table, main_data_context)
            try:
                return self.async_executor.call_fetch_fragments_data(
                    fetch_fragments_data, existing_fragments_table, main_data_context
                )
            except TypeError:
                # Fallback to old signature if function doesn't accept context
                return self.async_executor.call_fetch_fragments_data(
                    fetch_fragments_data, existing_fragments_table
                )
        else:
            # Original signature: fetch_fragments_data(existing_fragments_table)
            return self.async_executor.call_fetch_fragments_data(
                fetch_fragments_data, existing_fragments_table
            )

    def _apply_transformation(
        self, module: Any, data: List[Dict[str, Any]], resource_name: str, transform_func_name: str
    ) -> tuple[List[Dict[str, Any]] | None, str | None]:
        """Apply transformation function if available.

        Returns:
            A tuple ``(transformed_data, traceback_str)``:
            - ``(data, None)`` on success (or when no transform function exists)
            - ``(None, traceback_str)`` when the transform raised
        """
        if hasattr(module, transform_func_name):
            try:
                transform_func = getattr(module, transform_func_name)
                return transform_func(data), None
            except Exception:
                return None, traceback.format_exc()
        else:
            return data, None

    def _validate_data_structure(
        self, data: List[Dict[str, Any]], context: str
    ) -> ValidationResult:
        """Validate that data has the correct structure.

        Args:
            data: Data to validate
            context: Context string for error messages

        Returns:
            ValidationResult indicating if data is valid
        """
        result = ValidationResult(is_valid=True)

        if not isinstance(data, list):
            result.is_valid = False
            result.errors.append(f"Data for '{context}' must be a list")
            return result

        if not all(isinstance(item, dict) for item in data):
            result.is_valid = False
            result.errors.append(f"All items in '{context}' data must be dictionaries")

        return result
