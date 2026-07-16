"""
Main database builder for Zeeker projects.

This module orchestrates the database building process, coordinating
resource processing, schema management, and S3 synchronization.
"""

import asyncio
import time
import traceback
from pathlib import Path
from typing import Callable

import sqlite_utils

from ..schema import SchemaManager
from ..types import (
    BuildReport,
    ResourceOutcome,
    ValidationResult,
    ZeekerProject,
    ZeekerSchemaConflictError,
)
from .async_executor import AsyncExecutor
from .fts_processor import FTSProcessor
from .processor import ResourceProcessor
from .s3_sync import S3Synchronizer


class DatabaseBuilder:
    """Builds SQLite databases from Zeeker resources with S3 sync support."""

    def __init__(self, project_path: Path, project: ZeekerProject):
        """Initialize database builder.

        Args:
            project_path: Path to the Zeeker project
            project: ZeekerProject configuration
        """
        self.project_path = project_path
        self.project = project
        self.resources_path = project_path / "resources"
        self.schema_manager = SchemaManager()
        self.processor = ResourceProcessor(self.resources_path, self.schema_manager)
        self.s3_sync = S3Synchronizer()
        self.fts_processor = FTSProcessor(project)

    def build_database(
        self,
        force_schema_reset: bool = False,
        sync_from_s3: bool = False,
        resources: list[str] = None,
        setup_fts: bool = False,
        progress_callback: Callable[[str, ResourceOutcome | None], None] | None = None,
        max_parallel: int = 1,
        force_sync: bool = False,
    ) -> ValidationResult:
        """Build the SQLite database from resources using sqlite-utils.

        Uses Simon Willison's sqlite-utils for robust table creation and data insertion:
        - Automatic schema detection from data
        - Proper type inference (INTEGER, TEXT, REAL)
        - Safe table creation and data insertion
        - Better error handling than raw SQL

        Args:
            force_schema_reset: If True, ignore schema conflicts and rebuild
            sync_from_s3: If True, download existing database from S3 before building
            resources: List of specific resource names to build. If None, builds all resources.
            setup_fts: If True, set up full-text search indexes on configured fields
            progress_callback: Optional callable invoked as (resource_name, None) when a
                resource starts and (resource_name, outcome) when it finishes. Allows the
                CLI layer to drive progress bars or streaming output.

        Returns:
            ValidationResult with build results. `result.report` holds a BuildReport
            describing per-resource outcomes, timings, and fatal/FTS errors.
        """
        result = ValidationResult(is_valid=True)
        report = BuildReport()
        result.report = report
        build_started = time.perf_counter()

        db_path = self.project_path / self.project.database

        # S3 Database Synchronization - Download existing DB if requested
        if sync_from_s3:
            sync_result = self.s3_sync.sync_from_s3(
                self.project.database, db_path, force=force_sync
            )
            if not sync_result.is_valid:
                result.errors.extend(sync_result.errors)
                # Don't fail build if S3 sync fails - just warn
                result.warnings.append("S3 sync failed but continuing with local build")
            else:
                result.info.extend(sync_result.info)
            if sync_result.warnings:
                result.warnings.extend(sync_result.warnings)

        # Open existing database or create new one using sqlite-utils
        # Don't delete existing database - let resources check existing data for duplicates
        db = sqlite_utils.Database(str(db_path))

        try:
            # Initialize meta tables
            self.schema_manager.ensure_meta_tables(db)
            build_id = self.schema_manager.generate_build_id()

            # Determine which resources to process
            resources_to_build = resources if resources else list(self.project.resources.keys())

            # Pre-warm fetches concurrently when requested. The per-resource
            # sequential loop below will then hit pre-warmed data instead of
            # re-running each fetch_data() serially.
            if max_parallel > 1 and len(resources_to_build) > 1:
                prewarm_warnings = self._prewarm_fetches(db, resources_to_build, max_parallel)
                result.warnings.extend(prewarm_warnings)

            # Process each specified resource
            for resource_name in resources_to_build:
                if progress_callback:
                    progress_callback(resource_name, None)

                resource_started = time.perf_counter()
                resource_result = self._process_resource_with_schema_check(
                    db, resource_name, force_schema_reset, build_id
                )
                duration = time.perf_counter() - resource_started

                outcome = self._build_resource_outcome(resource_name, resource_result, duration)

                if not resource_result.is_valid:
                    result.errors.extend(resource_result.errors)
                    result.tracebacks.extend(resource_result.tracebacks)
                    result.is_valid = False
                else:
                    result.info.extend(resource_result.info)

                    # Process fragments if enabled. By default fragments run
                    # only when the main phase inserted rows ("success").
                    # Resources that opt in via `fragments_on_skip = true` in
                    # zeeker.toml also run the fragments phase when fetch_data
                    # returned no new rows ("skipped") — enrichment-style
                    # resources need this on steady-state builds.
                    resource_config = self.project.resources.get(resource_name, {})
                    fragments_enabled = resource_config.get("fragments", False)
                    run_fragments = fragments_enabled and (
                        outcome.status == "success"
                        or (
                            outcome.status == "skipped"
                            and resource_config.get("fragments_on_skip", False)
                        )
                    )
                    if run_fragments:
                        # Reuse the module and raw fetch_data() output from
                        # the main phase — fetch_data must run once per build.
                        main_data_context = resource_result.raw_data
                        if outcome.status == "skipped" and main_data_context is None:
                            main_data_context = []
                        fragments_result = self._process_fragments_for_resource(
                            db,
                            resource_name,
                            module=resource_result.module,
                            main_data_context=main_data_context,
                        )
                        if not fragments_result.is_valid:
                            result.errors.extend(fragments_result.errors)
                            result.tracebacks.extend(fragments_result.tracebacks)
                            result.is_valid = False
                            outcome.status = "failed"
                            outcome.error_message = (
                                fragments_result.errors[0]
                                if fragments_result.errors
                                else "fragments processing failed"
                            )
                            if fragments_result.tracebacks:
                                outcome.traceback = fragments_result.tracebacks[0]
                        else:
                            result.info.extend(fragments_result.info)
                            outcome.fragments_records = fragments_result.records

                report.resources.append(outcome)
                if progress_callback:
                    progress_callback(resource_name, outcome)

            # Set up FTS after all resources are processed (only if requested)
            if result.is_valid and setup_fts:
                fts_result = self.fts_processor.setup_fts_for_database(db, force_schema_reset)
                if not fts_result.is_valid:
                    result.errors.extend(fts_result.errors)
                    result.is_valid = False
                    report.fts_error = (
                        fts_result.errors[0] if fts_result.errors else "FTS setup failed"
                    )
                else:
                    result.info.extend(fts_result.info)
                    if fts_result.warnings:
                        result.warnings.extend(fts_result.warnings)
            elif result.is_valid and not setup_fts:
                result.info.append("Skipped FTS setup (use --setup-fts flag to enable)")

        except Exception as e:
            result.is_valid = False
            msg = f"Database build failed: {e}"
            result.errors.append(msg)
            result.tracebacks.append(traceback.format_exc())
            report.fatal_error = msg

        finally:
            # Prevent stale pre-warmed data from leaking into a reused builder.
            self.processor.async_executor.clear_prewarmed()

        report.total_duration_s = time.perf_counter() - build_started
        return result

    @staticmethod
    def _build_resource_outcome(
        resource_name: str, resource_result: ValidationResult, duration_s: float
    ) -> ResourceOutcome:
        """Construct a ResourceOutcome from a per-resource ValidationResult."""
        if not resource_result.is_valid:
            return ResourceOutcome(
                name=resource_name,
                status="failed",
                duration_s=duration_s,
                error_message=(
                    resource_result.errors[0] if resource_result.errors else "unknown error"
                ),
                traceback=(resource_result.tracebacks[0] if resource_result.tracebacks else None),
            )

        is_skipped = any("No data returned" in msg for msg in resource_result.info)
        return ResourceOutcome(
            name=resource_name,
            status="skipped" if is_skipped else "success",
            records=resource_result.records or 0,
            duration_s=duration_s,
        )

    def _process_resource_with_schema_check(
        self, db: sqlite_utils.Database, resource_name: str, force_schema_reset: bool, build_id: str
    ) -> ValidationResult:
        """Process a single resource with schema conflict detection and migration support.

        Args:
            db: sqlite-utils Database instance
            resource_name: Name of the resource to process
            force_schema_reset: If True, ignore schema conflicts and rebuild
            build_id: Unique build identifier for tracking

        Returns:
            ValidationResult with processing results
        """
        result = ValidationResult(is_valid=True)
        start_time = time.time()

        # Load resource module
        module_result = self.processor._load_resource_module(resource_name)
        if not module_result.is_valid:
            return module_result

        module = module_result.data
        # Thread the loaded module through to the caller so the fragments
        # phase can reuse it instead of re-importing the resource file.
        result.module = module

        try:
            # Get the fetch_data function
            if not hasattr(module, "fetch_data"):
                result.is_valid = False
                result.errors.append(f"Resource '{resource_name}' missing fetch_data() function")
                return result

            fetch_data = getattr(module, "fetch_data")

            # Check for existing table and schema conflicts
            existing_table = db[resource_name] if db[resource_name].exists() else None

            if existing_table and not force_schema_reset:
                # Check for schema conflicts
                try:
                    sample_data = self.processor.async_executor.call_fetch_data(
                        fetch_data, existing_table, resource_name=resource_name
                    )[
                        :5
                    ]  # Small sample for schema check
                    if sample_data:
                        schema_result = self.schema_manager.check_schema_conflicts(
                            db, resource_name, sample_data, module
                        )
                        result.info.extend(schema_result.info)
                except Exception as e:
                    if isinstance(e, ZeekerSchemaConflictError):
                        raise
                    # Couldn't fetch a sample — surface this as a warning so
                    # the user knows the schema-conflict check ran blind,
                    # instead of a completely silent pass.
                    result.warnings.append(
                        f"Schema sample fetch failed for '{resource_name}' "
                        f"(continuing with build): {e}"
                    )

            # Process the resource (pass pre-loaded module to avoid redundant load)
            resource_result = self.processor.process_resource(db, resource_name, module)
            if not resource_result.is_valid:
                result.errors.extend(resource_result.errors)
                result.tracebacks.extend(resource_result.tracebacks)
                result.is_valid = False
            else:
                result.info.extend(resource_result.info)
                result.records = resource_result.records
                # Thread the raw fetch_data() output through for the
                # fragments phase (main_data_context).
                result.raw_data = resource_result.raw_data

                # Update resource timestamps
                duration_ms = int((time.time() - start_time) * 1000)
                self.schema_manager.update_resource_timestamps(
                    db, resource_name, build_id, duration_ms
                )

        except ZeekerSchemaConflictError as e:
            result.is_valid = False
            result.errors.append(str(e))
            result.tracebacks.append(traceback.format_exc())
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to process resource '{resource_name}': {e}")
            result.tracebacks.append(traceback.format_exc())

        return result

    def _process_fragments_for_resource(
        self,
        db: sqlite_utils.Database,
        resource_name: str,
        module=None,
        main_data_context: list | None = None,
    ) -> ValidationResult:
        """Process fragments data for a fragments-enabled resource.

        Args:
            db: sqlite-utils Database instance
            resource_name: Name of the resource
            module: Already-loaded resource module from the main phase. When
                provided, the module is NOT re-imported (resources may rely on
                module-level state surviving from fetch_data). When None
                (legacy callers), the module is loaded from disk.
            main_data_context: Raw fetch_data() output from the main phase,
                passed to fetch_fragments_data as context. An empty list is a
                valid context (steady-state build with fragments_on_skip).
                When None (legacy callers), fetch_data is re-invoked to build
                the context — the old, duplicate-fetch behavior.

        Returns:
            ValidationResult with fragments processing results
        """
        result = ValidationResult(is_valid=True)

        # Reuse the module from the main phase when provided; only load from
        # disk for legacy callers that don't thread it through.
        if module is None:
            module_result = self.processor._load_resource_module(resource_name)
            if not module_result.is_valid:
                return module_result
            module = module_result.data

        # Check if fragments function exists
        if not hasattr(module, "fetch_fragments_data"):
            result.is_valid = False
            result.errors.append(
                f"Resource '{resource_name}' is configured with fragments=true "
                f"but missing fetch_fragments_data() function"
            )
            return result

        # Build main_data_context only when the caller didn't thread it
        # through from the main phase (legacy behavior: re-run fetch_data).
        if main_data_context is None:
            try:
                fetch_data = getattr(module, "fetch_data")
                existing_table = db[resource_name] if db[resource_name].exists() else None
                main_data_context = self.processor.async_executor.call_fetch_data(
                    fetch_data, existing_table, resource_name=resource_name
                )
            except Exception as e:
                # If we can't get context, fragments will work without it — but
                # surface the reason rather than swallowing the exception silently.
                result.warnings.append(
                    f"Fragments context fetch failed for '{resource_name}' "
                    f"(fragments will run without main-data context): {e}"
                )
                main_data_context = None

        # Process fragments
        fragments_result = self.processor.process_fragments_data(
            db, resource_name, module, main_data_context
        )
        if not fragments_result.is_valid:
            result.errors.extend(fragments_result.errors)
            result.tracebacks.extend(fragments_result.tracebacks)
            result.is_valid = False
        else:
            result.info.extend(fragments_result.info)
            result.records = fragments_result.records

        return result

    def _prewarm_fetches(
        self,
        db: sqlite_utils.Database,
        resources_to_build: list[str],
        max_parallel: int,
    ) -> list[str]:
        """Run ``fetch_data()`` for all resources concurrently and populate
        the processor's executor with pre-warmed results.

        Returns a list of warning strings (one per resource whose pre-fetch
        failed; the sequential loop will re-attempt those and record the
        definitive error).
        """
        # Synchronous prep: module loading and existing-table lookup.
        # Doing this here (not inside the coroutines) avoids racy imports
        # and lets us skip resources that can't even be loaded.
        specs: list[tuple[str, object, object]] = []
        warnings: list[str] = []
        for name in resources_to_build:
            mod_result = self.processor._load_resource_module(name)
            if not mod_result.is_valid:
                # Let the sequential loop produce the canonical error.
                continue
            module = mod_result.data
            if not hasattr(module, "fetch_data"):
                continue
            fetch_data = getattr(module, "fetch_data")
            existing = db[name] if db[name].exists() else None
            specs.append((name, fetch_data, existing))

        if not specs:
            return warnings

        fresh = AsyncExecutor(cache_enabled=False)
        sem = asyncio.Semaphore(max_parallel)

        async def run_one(name: str, fetch_data, existing):
            async with sem:
                try:
                    data = await fresh.acall_fetch_data(fetch_data, existing, name)
                    return name, data, None
                except Exception as e:
                    return name, None, e

        async def run_all():
            return await asyncio.gather(*(run_one(*s) for s in specs))

        results = asyncio.run(run_all())
        for name, data, err in results:
            if err is not None:
                warnings.append(
                    f"Parallel pre-fetch failed for '{name}' "
                    f"(sequential loop will retry): {err}"
                )
                continue
            if data is not None:
                self.processor.async_executor.set_prewarmed(name, data)

        return warnings
