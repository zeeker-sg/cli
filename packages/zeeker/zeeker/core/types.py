"""
Core data types and structures for Zeeker.
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Meta table constants
META_TABLE_SCHEMAS = "_zeeker_schemas"
META_TABLE_UPDATES = "_zeeker_updates"
META_TABLE_NAMES = [META_TABLE_SCHEMAS, META_TABLE_UPDATES]


class ZeekerSchemaConflictError(Exception):
    """Raised when schema changes detected without migration handler."""

    def __init__(self, resource_name: str, old_schema: dict[str, str], new_schema: dict[str, str]):
        self.resource_name = resource_name
        self.old_schema = old_schema
        self.new_schema = new_schema

        # Find schema differences for helpful error message
        old_cols = set(old_schema.keys())
        new_cols = set(new_schema.keys())
        added_cols = new_cols - old_cols
        removed_cols = old_cols - new_cols
        changed_types = {
            col: (old_schema[col], new_schema[col])
            for col in old_cols & new_cols
            if old_schema[col] != new_schema[col]
        }

        msg_parts = [f"Schema conflict detected for resource '{resource_name}'."]

        if added_cols:
            msg_parts.append(f"Added columns: {', '.join(sorted(added_cols))}")
        if removed_cols:
            msg_parts.append(f"Removed columns: {', '.join(sorted(removed_cols))}")
        if changed_types:
            for col, (old_type, new_type) in changed_types.items():
                msg_parts.append(f"Changed '{col}': {old_type} → {new_type}")

        msg_parts.extend(
            [
                "",
                "To resolve this conflict:",
                f"1. Add migrate_schema() function to resources/{resource_name}.py",
                "2. Or delete the database file to rebuild from scratch",
                "3. Or use --force-schema-reset flag",
            ]
        )

        super().__init__("\n".join(msg_parts))


@dataclass
class ResourceOutcome:
    """Per-resource outcome from a build, aggregated by DatabaseBuilder."""

    name: str
    status: Literal["success", "failed", "skipped"]
    records: int = 0
    duration_s: float = 0.0
    error_message: str | None = None
    traceback: str | None = None
    fragments_records: int | None = None


@dataclass
class BuildReport:
    """Structured report of a full database build, one entry per resource."""

    resources: list[ResourceOutcome] = field(default_factory=list)
    total_duration_s: float = 0.0
    fts_error: str | None = None
    fatal_error: str | None = None
    # Set to a PostHookResult dataclass when --post-hook ran. Annotated as
    # ``object`` to avoid a circular import between this module and
    # commands/post_hook.py; dataclasses.asdict() still recurses correctly
    # when the value is itself a dataclass instance.
    post_hook: object | None = None

    @property
    def failed(self) -> list[ResourceOutcome]:
        return [r for r in self.resources if r.status == "failed"]

    @property
    def succeeded(self) -> list[ResourceOutcome]:
        return [r for r in self.resources if r.status == "success"]

    @property
    def skipped(self) -> list[ResourceOutcome]:
        return [r for r in self.resources if r.status == "skipped"]


@dataclass
class ValidationResult:
    """Result of validation operations."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    tracebacks: list[str] = field(default_factory=list)
    report: "BuildReport | None" = None
    records: int | None = None
    # Generic payload (e.g. a loaded resource module from _load_resource_module).
    data: Any = None
    # Loaded resource module from the main build phase. Threaded through to
    # the fragments phase so each resource module is imported exactly once
    # per build.
    module: Any = None
    # Raw fetch_data() output (pre-transform) from the main build phase.
    # Threaded through to the fragments phase as main_data_context so
    # fetch_data() runs exactly once per build.
    raw_data: list[dict[str, Any]] | None = None


@dataclass
class DatabaseCustomization:
    """Represents a complete database customization."""

    database_name: str
    base_path: Path
    templates: dict[str, str] = field(default_factory=dict)
    static_files: dict[str, bytes] = field(default_factory=dict)
    metadata: dict[str, Any] | None = None


@dataclass
class DeploymentChanges:
    """Represents the changes to be made during deployment."""

    uploads: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.uploads or self.updates or self.deletions)

    @property
    def has_destructive_changes(self) -> bool:
        return bool(self.deletions)


@dataclass
class ZeekerProject:
    """Represents a Zeeker project configuration."""

    name: str
    database: str
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    root_path: Path = field(default_factory=Path)

    # Rich metadata fields (optional)
    title: str | None = None
    description: str | None = None
    license: str | None = None
    license_url: str | None = None
    source: str | None = None
    source_url: str | None = None

    @classmethod
    def from_toml(cls, toml_path: Path) -> "ZeekerProject":
        """Load project from zeeker.toml file."""

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        project_data = data.get("project", {})

        # Extract resource sections (resource.*)
        # Handle both inline columns format and separate column sections
        resources = data.get("resource", {})

        # TOML parser automatically handles nested sections like [resource.users.columns]
        # They appear as nested dictionaries in the parsed data
        # No additional processing needed - the structure is preserved

        return cls(
            name=project_data.get("name", ""),
            database=project_data.get("database", ""),
            resources=resources,
            root_path=toml_path.parent,
            # Rich metadata fields (optional)
            title=project_data.get("title"),
            description=project_data.get("description"),
            license=project_data.get("license"),
            license_url=project_data.get("license_url"),
            source=project_data.get("source"),
            source_url=project_data.get("source_url"),
        )

    def save_toml(self, toml_path: Path) -> None:
        """Save project to zeeker.toml file."""
        toml_content = f"""[project]
name = "{self.name}"
database = "{self.database}"
"""

        # Add rich metadata fields if present
        if self.title:
            toml_content += f'title = "{self.title}"\n'
        if self.description:
            toml_content += f'description = "{self.description}"\n'
        if self.license:
            toml_content += f'license = "{self.license}"\n'
        if self.license_url:
            toml_content += f'license_url = "{self.license_url}"\n'
        if self.source:
            toml_content += f'source = "{self.source}"\n'
        if self.source_url:
            toml_content += f'source_url = "{self.source_url}"\n'

        toml_content += "\n"
        for resource_name, resource_config in self.resources.items():
            toml_content += f"[resource.{resource_name}]\n"

            # Write resource config excluding columns metadata
            for key, value in resource_config.items():
                if key != "columns":  # Skip columns - they get their own section
                    toml_content += self._format_toml_value(key, value)
            toml_content += "\n"

            # Write columns metadata in separate section if it exists
            if "columns" in resource_config and resource_config["columns"]:
                toml_content += f"[resource.{resource_name}.columns]\n"
                for column_name, column_description in resource_config["columns"].items():
                    escaped_description = column_description.replace('"', '\\"')
                    toml_content += f'{column_name} = "{escaped_description}"\n'
                toml_content += "\n"

        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(toml_content)

    def _format_toml_value(self, key: str, value: Any) -> str:
        """Format a single TOML key-value pair with proper escaping and structure.

        Args:
            key: The key name
            value: The value to format

        Returns:
            Formatted TOML line with newline
        """
        if isinstance(value, str):
            # Escape quotes in strings
            escaped_value = value.replace('"', '\\"')
            return f'{key} = "{escaped_value}"\n'
        elif isinstance(value, list):
            # Format arrays nicely - handle both strings and other types
            formatted_items = []
            for item in value:
                if isinstance(item, str):
                    escaped_item = item.replace('"', '\\"')
                    formatted_items.append(f'"{escaped_item}"')
                else:
                    formatted_items.append(str(item))
            formatted_list = "[" + ", ".join(formatted_items) + "]"
            return f"{key} = {formatted_list}\n"
        elif isinstance(value, dict):
            # Format inline tables for nested structures like columns metadata
            formatted_pairs = []
            for k, v in value.items():
                if isinstance(v, str):
                    escaped_v = v.replace('"', '\\"')
                    formatted_pairs.append(f'{k} = "{escaped_v}"')
                else:
                    formatted_pairs.append(f"{k} = {v}")
            formatted_dict = "{" + ", ".join(formatted_pairs) + "}"
            return f"{key} = {formatted_dict}\n"
        elif isinstance(value, bool):
            return f"{key} = {str(value).lower()}\n"
        elif isinstance(value, (int, float)):
            return f"{key} = {value}\n"
        else:
            # Fallback for other types - convert to string
            return f'{key} = "{str(value)}"\n'

    def to_datasette_metadata(self) -> dict[str, Any]:
        """Convert project configuration to complete Datasette metadata.json format.

        Follows Datasette metadata specification with proper separation between
        instance-level and database-level metadata.
        """
        # Database name for S3 path (matches .db filename without extension)
        db_name = Path(self.database).stem

        # Generate fallback values
        auto_db_title = f"{self.name.replace('_', ' ').replace('-', ' ').title()} Database"
        auto_db_description = f"Database for {self.name} project"
        auto_source = f"{self.name} project"

        # Instance-level metadata (site-wide)
        instance_title = f"{self.name.replace('_', ' ').replace('-', ' ').title()} Data Portal"
        instance_description = f"Data portal for the {self.name} project"

        metadata = {
            # Instance-level metadata applies site-wide
            "title": instance_title,
            "description": instance_description,
            "license": self.license or "MIT",
            "license_url": self.license_url or "https://opensource.org/licenses/MIT",
            "source": self.source or auto_source,
            "databases": {
                db_name: {
                    # Database-specific metadata
                    "title": self.title or auto_db_title,
                    "description": self.description or auto_db_description,
                    "extra_css_urls": [f"/static/databases/{db_name}/custom.css"],
                    "extra_js_urls": [f"/static/databases/{db_name}/custom.js"],
                    "tables": {},
                }
            },
        }

        # Add source_url if provided (instance-level)
        if self.source_url:
            metadata["source_url"] = self.source_url

        # Add table metadata from resource configurations
        for resource_name, resource_config in self.resources.items():
            table_metadata = {}

            # Copy all Datasette-specific metadata fields directly from resource config
            datasette_fields = [
                "description",
                "description_html",
                "facets",
                "sort",
                "sort_desc",
                "size",
                "sortable_columns",
                "hidden",
                "label_column",
                "columns",
                "units",
            ]

            for field_name in datasette_fields:
                if field_name in resource_config:
                    table_metadata[field_name] = resource_config[field_name]

            # Default description if not provided
            if "description" not in table_metadata:
                table_metadata["description"] = resource_config.get(
                    "description", f"{resource_name.replace('_', ' ').title()} data"
                )

            metadata["databases"][db_name]["tables"][resource_name] = table_metadata

        return metadata


def calculate_schema_hash(column_definitions: dict[str, str]) -> str:
    """Calculate a hash of table schema for change detection.

    Args:
        column_definitions: Dictionary of column_name -> column_type

    Returns:
        Hex string hash of the schema
    """
    # Sort columns for consistent hashing
    sorted_schema = json.dumps(column_definitions, sort_keys=True)
    return hashlib.sha256(sorted_schema.encode()).hexdigest()[:16]


def extract_table_schema(table) -> dict[str, str]:
    """Extract column definitions from a sqlite-utils Table.

    Args:
        table: sqlite-utils Table object

    Returns:
        Dictionary mapping column names to their types
    """
    return {col.name: col.type for col in table.columns}


def infer_schema_from_data(data: list[dict[str, Any]]) -> dict[str, str]:
    """Infer schema from a list of data records.

    Args:
        data: List of dictionary records

    Returns:
        Dictionary mapping column names to their inferred SQLite types
    """
    if not data:
        return {}

    # Get all columns from all records
    all_columns = set()
    for record in data:
        all_columns.update(record.keys())

    schema = {}
    for column in all_columns:
        # Look at values in this column to infer type
        values = [record.get(column) for record in data if column in record]
        non_null_values = [v for v in values if v is not None]

        if not non_null_values:
            schema[column] = "TEXT"  # Default for all NULL
            continue

        # Check types in order of specificity
        if all(isinstance(v, bool) for v in non_null_values):
            schema[column] = "INTEGER"  # bools stored as integers
        elif all(isinstance(v, int) for v in non_null_values):
            schema[column] = "INTEGER"
        elif all(isinstance(v, (int, float)) for v in non_null_values):
            schema[column] = "REAL"
        elif all(isinstance(v, (dict, list)) for v in non_null_values):
            schema[column] = "TEXT"  # JSON stored as text
        else:
            schema[column] = "TEXT"  # Default fallback

    return schema
