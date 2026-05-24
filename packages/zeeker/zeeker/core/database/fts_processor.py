"""
Full-Text Search processor for Zeeker databases.

This module handles enabling and configuring FTS on tables based on
zeeker.toml configuration using sqlite-utils.
"""

from typing import Any, Dict, List

import sqlite_utils

from ..types import ValidationResult, ZeekerProject


class FTSProcessor:
    """Handles full-text search setup for database tables."""

    def __init__(self, project: ZeekerProject):
        """Initialize FTS processor.

        Args:
            project: ZeekerProject configuration
        """
        self.project = project

    def setup_fts_for_database(
        self, db: sqlite_utils.Database, force_schema_reset: bool = False
    ) -> ValidationResult:
        """Set up FTS for all configured resources in the database.

        Args:
            db: sqlite-utils Database instance
            force_schema_reset: If True, drop existing FTS tables before recreating

        Returns:
            ValidationResult with FTS setup results
        """
        result = ValidationResult(is_valid=True)

        for resource_name, resource_config in self.project.resources.items():
            fts_fields = resource_config.get("fts_fields", [])
            if fts_fields:
                fts_result = self._setup_fts_for_table(
                    db, resource_name, fts_fields, force_schema_reset
                )
                if not fts_result.is_valid:
                    result.errors.extend(fts_result.errors)
                    result.is_valid = False
                else:
                    result.info.extend(fts_result.info)
                # Always extend warnings regardless of success/failure
                result.warnings.extend(fts_result.warnings)

            # Handle fragments table FTS - enabled by default on text content
            if resource_config.get("fragments", False):
                fragments_table_name = f"{resource_name}_fragments"

                if db[fragments_table_name].exists():
                    # Default to enabling FTS on common text field names if not explicitly configured
                    fragments_fts_fields = resource_config.get("fragments_fts_fields", None)

                    if fragments_fts_fields is None:
                        # Auto-detect text content fields in fragments table
                        fragments_fts_fields = self._detect_fragments_text_fields(
                            db, fragments_table_name
                        )

                    if fragments_fts_fields:
                        fts_result = self._setup_fts_for_table(
                            db, fragments_table_name, fragments_fts_fields, force_schema_reset
                        )
                        if not fts_result.is_valid:
                            result.errors.extend(fts_result.errors)
                            result.is_valid = False
                        else:
                            result.info.extend(fts_result.info)
                        # Always extend warnings regardless of success/failure
                        result.warnings.extend(fts_result.warnings)

        return result

    def _detect_fragments_text_fields(
        self, db: sqlite_utils.Database, fragments_table_name: str
    ) -> List[str]:
        """Auto-detect text content fields in fragments table for FTS.

        Args:
            db: sqlite-utils Database instance
            fragments_table_name: Name of the fragments table

        Returns:
            List of field names suitable for FTS
        """
        table = db[fragments_table_name]
        columns = [col.name for col in table.columns]

        # Common text field names in fragments tables, in order of preference
        text_field_candidates = [
            "text",  # Most common
            "content",  # Alternative common name
            "chunk",  # For document chunks
            "fragment",  # Generic fragment text
            "body",  # Body text
            "description",  # Description field
            "summary",  # Summary field
        ]

        # Return the first matching field, or all text-like fields if none of the common names match
        for candidate in text_field_candidates:
            if candidate in columns:
                return [candidate]

        # If no common text fields found, look for any TEXT columns that might contain searchable content
        # Exclude common metadata fields that shouldn't be searched
        excluded_fields = {
            "id",
            "parent_id",
            "created_at",
            "updated_at",
            "timestamp",
            "index",
            "position",
        }

        text_fields = []
        for col in table.columns:
            if (
                col.name not in excluded_fields
                and col.type in ("TEXT", "text")
                and len(col.name) > 2
            ):  # Avoid single-char fields
                text_fields.append(col.name)

        return text_fields

    def _setup_fts_for_table(
        self,
        db: sqlite_utils.Database,
        table_name: str,
        fts_fields: List[str],
        force_schema_reset: bool = False,
    ) -> ValidationResult:
        """Set up FTS for a specific table.

        Args:
            db: sqlite-utils Database instance
            table_name: Name of the table
            fts_fields: List of column names to enable FTS on
            force_schema_reset: If True, drop existing FTS table before recreating

        Returns:
            ValidationResult with FTS setup results
        """
        result = ValidationResult(is_valid=True)

        if not db[table_name].exists():
            result.warnings.append(f"Table '{table_name}' does not exist, skipping FTS setup")
            return result

        table = db[table_name]

        # Clean up existing FTS infrastructure if force_schema_reset is enabled
        if force_schema_reset:
            fts_table_name = f"{table_name}_fts"

            # Check if any FTS tables exist for this table
            fts_tables = [name for name in db.table_names() if name.startswith(fts_table_name)]

            if fts_tables:
                try:
                    # Disable FTS first to clean up triggers and related objects
                    if fts_table_name in db.table_names():
                        table.disable_fts()
                        result.info.append(
                            f"Disabled existing FTS for table '{table_name}' due to schema reset"
                        )
                except Exception as e:
                    result.warnings.append(
                        f"Failed to disable existing FTS for table '{table_name}': {e}"
                    )

                # Drop any remaining FTS tables
                for fts_table in fts_tables:
                    try:
                        if fts_table in db.table_names():
                            db[fts_table].drop()
                            result.info.append(
                                f"Dropped FTS table '{fts_table}' due to schema reset"
                            )
                    except Exception as e:
                        result.warnings.append(f"Failed to drop FTS table '{fts_table}': {e}")

        try:
            # Check if columns exist in the table
            existing_columns = [col.name for col in table.columns]
            valid_fts_fields = []

            for field in fts_fields:
                if field in existing_columns:
                    valid_fts_fields.append(field)
                else:
                    result.warnings.append(
                        f"Column '{field}' not found in table '{table_name}', skipping"
                    )

            if not valid_fts_fields:
                result.warnings.append(f"No valid FTS fields found for table '{table_name}'")
                return result

            # Enable FTS5 once with triggers; sqlite-utils' replace=True makes
            # this idempotent. If the FTS table already exists with the same
            # columns + triggers, enable_fts returns early without doing any
            # work. Otherwise it drops and recreates (and populates internally).
            # The triggers (<table>_ai/_ad/_au) keep the index in sync as rows
            # change, so we don't need to populate on every subsequent build.
            table.enable_fts(valid_fts_fields, create_triggers=True, replace=True)
            result.info.append(
                f"Enabled FTS on table '{table_name}' for fields: {', '.join(valid_fts_fields)}"
            )

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to setup FTS for table '{table_name}': {e}")

        return result

    def get_fts_config_for_resource(self, resource_name: str) -> Dict[str, Any]:
        """Get FTS configuration for a specific resource.

        Args:
            resource_name: Name of the resource

        Returns:
            Dictionary with FTS configuration
        """
        resource_config = self.project.resources.get(resource_name, {})
        has_fragments = resource_config.get("fragments", False)

        # For fragments, return None to indicate auto-detection should be used
        # unless explicitly configured
        fragments_fts_fields = []
        if has_fragments:
            if "fragments_fts_fields" in resource_config:
                fragments_fts_fields = resource_config["fragments_fts_fields"]
            else:
                fragments_fts_fields = None  # Will trigger auto-detection

        return {
            "fts_fields": resource_config.get("fts_fields", []),
            "fragments_fts_fields": fragments_fts_fields,
            "has_fragments": has_fragments,
            "auto_detect_fragments_fts": has_fragments
            and "fragments_fts_fields" not in resource_config,
        }
