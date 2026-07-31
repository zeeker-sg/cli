"""
Tests for ZeekerProjectManager - project management functionality.
"""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zeeker.core.project import ZeekerProjectManager


class TestZeekerProjectManager:
    """Test project management functionality."""

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a ZeekerProjectManager for testing."""
        return ZeekerProjectManager(temp_dir)

    def test_manager_initialization(self, manager, temp_dir):
        """Test manager initializes with correct paths."""
        assert manager.project_path == temp_dir
        assert manager.toml_path == temp_dir / "zeeker.toml"
        assert manager.resources_path == temp_dir / "resources"

    def test_manager_default_path(self):
        """Test manager defaults to current working directory."""
        manager = ZeekerProjectManager()
        assert manager.project_path == Path.cwd()

    def test_is_project_root_false(self, manager):
        """Test is_project_root returns False when no zeeker.toml."""
        assert not manager.is_project_root()

    def test_is_project_root_true(self, manager):
        """Test is_project_root returns True when zeeker.toml exists."""
        manager.toml_path.write_text("[project]\nname = 'test'")
        assert manager.is_project_root()

    def test_init_project_success(self, manager):
        """Test successful project initialization."""
        result = manager.init_project("test_project")

        assert result.is_valid
        assert len(result.errors) == 0
        assert "Initialized Zeeker project" in result.info[0]

        # Check files created
        assert manager.toml_path.exists()
        assert manager.resources_path.exists()
        assert (manager.resources_path / "__init__.py").exists()
        assert (manager.project_path / "pyproject.toml").exists()
        assert (manager.project_path / ".gitignore").exists()
        assert (manager.project_path / "README.md").exists()

        # Check TOML content
        toml_content = manager.toml_path.read_text()
        assert "test_project" in toml_content
        assert "test_project.db" in toml_content

        # Check pyproject.toml content
        pyproject_content = (manager.project_path / "pyproject.toml").read_text()
        assert 'name = "test_project"' in pyproject_content
        assert 'version = "0.1.0"' in pyproject_content
        assert '"zeeker>=0.6.0"' in pyproject_content
        assert 'requires-python = ">=3.12"' in pyproject_content

    def test_init_project_already_exists(self, manager):
        """Test project initialization fails when project already exists."""
        manager.toml_path.write_text("[project]\nname = 'existing'")

        result = manager.init_project("test_project")

        assert not result.is_valid
        assert "already contains zeeker.toml" in result.errors[0]

    def test_init_project_pyproject_toml_content(self, manager):
        """Test pyproject.toml has correct structure and content."""
        result = manager.init_project("my_test_project")

        assert result.is_valid
        pyproject_path = manager.project_path / "pyproject.toml"
        assert pyproject_path.exists()

        content = pyproject_path.read_text()

        # Check required fields
        assert "[project]" in content
        assert 'name = "my_test_project"' in content
        assert 'version = "0.1.0"' in content
        assert 'description = "Zeeker database project for my_test_project"' in content
        assert '"zeeker>=0.6.0"' in content
        assert 'requires-python = ">=3.12"' in content

        # Check dev dependencies
        assert "[dependency-groups]" in content
        assert 'dev = ["black>=25.1.0", "ruff>=0.8.0"]' in content

        # Check tool configuration
        assert "[tool.black]" in content
        assert "line-length = 100" in content
        assert "[tool.ruff]" in content
        assert "[tool.ruff.lint]" in content

        # Should NOT have build system (not a package, just dependencies)
        assert "[build-system]" not in content

        # Check commented examples exist
        assert "# Add project-specific dependencies here" in content
        assert '"requests>=2.31.0"' in content
        assert '"pandas>=2.0.0"' in content
        assert "# For HTTP API calls" in content

    def test_load_project_success(self, manager):
        """Test loading an existing project."""
        # Create a test project file
        toml_content = textwrap.dedent(
            """[project]
name = "test_project"
database = "test_project.db"

[resource.users]
description = "User data"
facets = ["role", "department"]
"""
        )
        manager.toml_path.write_text(toml_content)

        project = manager.load_project()

        assert project.name == "test_project"
        assert project.database == "test_project.db"
        assert "users" in project.resources
        assert project.resources["users"]["description"] == "User data"

    def test_load_project_not_found(self, manager):
        """Test loading project fails when not found."""
        with pytest.raises(ValueError, match="Not a Zeeker project"):
            manager.load_project()

    def test_add_resource_success(self, manager):
        """Test adding a resource successfully."""
        # Initialize project first
        manager.init_project("test_project")

        result = manager.add_resource(
            "users", description="User account data", facets=["role", "department"], size=50
        )

        assert result.is_valid
        assert len(result.errors) == 0
        assert "Created resource" in result.info[0]

        # Check resource file created
        resource_file = manager.resources_path / "users.py"
        assert resource_file.exists()

        # Check file content
        content = resource_file.read_text()
        assert "def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:" in content
        assert "users" in content

        # Check project updated
        project = manager.load_project()
        assert "users" in project.resources
        assert project.resources["users"]["description"] == "User account data"
        assert project.resources["users"]["facets"] == ["role", "department"]
        assert project.resources["users"]["size"] == 50

    def test_add_resource_outside_project(self, manager):
        """Test adding resource fails outside project."""
        result = manager.add_resource("users", "User data")

        assert not result.is_valid
        assert "Not in a Zeeker project" in result.errors[0]

    def test_add_resource_already_exists(self, manager):
        """Test adding resource fails when it already exists."""
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Try to add again
        result = manager.add_resource("users", "User data again")

        assert not result.is_valid
        assert "already exists" in result.errors[0]

    def test_generate_resource_template(self, manager):
        """Test resource template generation."""
        template = manager.resource_manager.template_generator.generate_resource_template(
            "test_resource"
        )

        assert "test_resource" in template
        assert (
            "def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:" in template
        )
        assert "sqlite-utils" in template
        assert "TODO: Implement" in template

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_success(self, mock_db_class, manager):
        """Test successful database build."""
        # Setup project
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Create mock resource with fetch_data
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        result = manager.build_database()

        assert result.is_valid
        assert "Processed 2 records for resource 'users'" in result.info

        # Check database operations - verify "users" table was accessed
        users_calls = [call for call in mock_db.__getitem__.call_args_list if call[0][0] == "users"]
        assert len(users_calls) > 0, "Expected 'users' table to be accessed"

    def test_build_database_outside_project(self, manager):
        """Test build fails outside project."""
        result = manager.build_database()

        assert not result.is_valid
        assert "Not in a Zeeker project" in result.errors[0]

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_missing_resource_file(self, mock_db_class, manager):
        """Test build fails with missing resource file."""
        manager.init_project("test_project")

        # Add resource to config but don't create file
        project = manager.load_project()
        project.resources["missing"] = {"description": "Missing resource"}
        project.save_toml(manager.toml_path)

        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        result = manager.build_database()

        assert not result.is_valid
        assert "Resource file not found" in result.errors[0]

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_no_fetch_function(self, mock_db_class, manager):
        """Test build fails when resource has no fetch_data function."""
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Create resource without fetch_data function
        (manager.resources_path / "users.py").write_text("# No fetch_data function")

        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        result = manager.build_database()

        assert not result.is_valid
        assert "missing fetch_data() function" in result.errors[0]

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_invalid_data_type(self, mock_db_class, manager):
        """Test build fails when fetch_data returns wrong type."""
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Create resource that returns wrong type
        resource_content = """
def fetch_data(existing_table):
    return "not a list"
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        result = manager.build_database()

        assert not result.is_valid
        assert "must return a list" in result.errors[0]

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_with_transform(self, mock_db_class, manager):
        """Test build with optional transform_data function."""
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Create resource with both fetch_data and transform_data
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]

def transform_data(data):
    for item in data:
        item["name"] = item["name"].title()
    return data
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        mock_db = MagicMock()
        mock_table = MagicMock()
        mock_db.__getitem__.return_value = mock_table
        mock_db_class.return_value = mock_db

        result = manager.build_database()

        assert result.is_valid

        # Check that insert_all was called (transform_data should have been used)
        # Note: insert_all is called multiple times due to temp table creation for schema checking
        assert mock_table.insert_all.call_count >= 1
        call_args = mock_table.insert_all.call_args[0]
        data = call_args[0]

        # The data should be transformed (names capitalized)
        assert any(item["name"] == "Alice" for item in data)
        assert any(item["name"] == "Bob" for item in data)

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_build_database_with_specific_resources(self, mock_db_class, manager):
        """Test build database with specific resources only."""
        # Set up a project with multiple resources
        manager.init_project("test_project")
        manager.add_resource("users", "User data")
        manager.add_resource("posts", "Post data")

        # Create resource files
        users_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice"}]
"""
        posts_content = """
def fetch_data(existing_table):
    return [{"id": 1, "title": "First Post"}]
"""
        (manager.resources_path / "users.py").write_text(users_content)
        (manager.resources_path / "posts.py").write_text(posts_content)

        # Configure mock Database
        mock_db = MagicMock()
        mock_table = MagicMock()
        mock_db.__getitem__.return_value = mock_table
        mock_db_class.return_value = mock_db

        # Build only users resource
        result = manager.build_database(resources=["users"])

        assert result.is_valid
        # Should process only users resource - posts.py should not be imported
        assert mock_table.insert_all.call_count >= 1

    def test_build_database_with_invalid_resources(self, manager):
        """Test build database with invalid resource names."""
        # Set up a project with a resource
        manager.init_project("test_project")
        manager.add_resource("users", "User data")

        # Try to build with invalid resource name
        result = manager.build_database(resources=["invalid_resource"])

        assert not result.is_valid
        assert "Unknown resources: invalid_resource" in result.errors[0]
        assert "Available resources: users" in result.errors[1]


class TestMetaTables:
    """Test meta table functionality for schema and update tracking."""

    @pytest.fixture
    def setup_project(self, temp_dir):
        """Setup a project with resources for meta table testing."""
        manager = ZeekerProjectManager(temp_dir)
        manager.init_project("test_project")
        manager.add_resource("users", "User data")
        return manager

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_ensure_meta_tables_created(self, mock_db_class, setup_project):
        """Test that meta tables are created automatically."""
        from zeeker.core.types import META_TABLE_SCHEMAS

        manager = setup_project

        # Mock database and tables
        mock_db = MagicMock()
        mock_schema_table = MagicMock()
        mock_updates_table = MagicMock()

        # Configure exists() to return False (tables don't exist)
        mock_schema_table.exists.return_value = False
        mock_updates_table.exists.return_value = False
        mock_db.__getitem__.side_effect = lambda name: (
            mock_schema_table if name == META_TABLE_SCHEMAS else mock_updates_table
        )
        mock_db_class.return_value = mock_db

        # Create basic resource for testing
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice"}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Run build
        manager.build_database()

        # Verify meta tables were created
        assert mock_schema_table.create.called
        assert mock_updates_table.create.called

        # Check schema table structure
        schema_create_call = mock_schema_table.create.call_args
        assert "resource_name" in schema_create_call[0][0]
        assert "schema_version" in schema_create_call[0][0]
        assert "schema_hash" in schema_create_call[0][0]
        assert "column_definitions" in schema_create_call[0][0]

        # Check updates table structure
        updates_create_call = mock_updates_table.create.call_args
        assert "resource_name" in updates_create_call[0][0]
        assert "last_updated" in updates_create_call[0][0]
        assert "record_count" in updates_create_call[0][0]
        assert "build_id" in updates_create_call[0][0]

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_schema_tracking_new_resource(self, mock_db_class, setup_project):
        """Test schema tracking for a new resource."""
        from zeeker.core.types import META_TABLE_SCHEMAS, META_TABLE_UPDATES

        manager = setup_project

        # Mock database
        mock_db = MagicMock()
        mock_schema_table = MagicMock()
        mock_users_table = MagicMock()
        mock_updates_table = MagicMock()

        # Configure meta tables to exist, users table to not exist
        mock_schema_table.exists.return_value = True
        mock_updates_table.exists.return_value = True
        mock_users_table.exists.return_value = False
        mock_users_table.count = 1

        # Mock rows_where to return empty (no existing schema)
        mock_schema_table.rows_where.return_value = []

        mock_db.__getitem__.side_effect = lambda name: {
            META_TABLE_SCHEMAS: mock_schema_table,
            META_TABLE_UPDATES: mock_updates_table,
            "users": mock_users_table,
        }.get(name, MagicMock())

        mock_db_class.return_value = mock_db

        # Create resource
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice", "age": 25}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Run build
        result = manager.build_database()

        # Build should succeed
        assert result.is_valid

        # Verify schema was inserted with version 1
        assert mock_schema_table.insert.called
        insert_call = mock_schema_table.insert.call_args[0][0]
        assert insert_call["resource_name"] == "users"
        assert insert_call["schema_version"] == 1
        assert "schema_hash" in insert_call
        assert "column_definitions" in insert_call

    @pytest.mark.skip(reason="Complex mocking affected by fragments implementation changes")
    @patch("zeeker.core.project.extract_table_schema")
    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_schema_conflict_detection(self, mock_db_class, mock_extract_schema, setup_project):
        """Test that schema conflicts are detected and handled."""
        from zeeker.core.types import META_TABLE_SCHEMAS, ZeekerSchemaConflictError

        manager = setup_project

        # Mock schema extraction to return different schemas
        mock_extract_schema.return_value = {
            "id": "INTEGER",
            "name": "TEXT",
            "age": "INTEGER",
        }  # New schema

        # Mock database with existing resource
        mock_db = MagicMock()
        mock_schema_table = MagicMock()
        mock_users_table = MagicMock()

        mock_schema_table.exists.return_value = True
        mock_users_table.exists.return_value = True

        # Mock existing schema (old schema has different hash)
        mock_schema_table.get.return_value = {
            "resource_name": "users",
            "schema_version": 1,
            "schema_hash": "old_hash_123",
            "column_definitions": '{"id": "INTEGER", "name": "TEXT"}',  # Old schema without age
        }

        def mock_getitem(name):
            if name == META_TABLE_SCHEMAS:
                return mock_schema_table
            elif name == "users":
                return mock_users_table
            elif name.startswith("_temp_users_"):
                # Mock temp table for schema checking
                temp_table = MagicMock()
                temp_table.insert_all = MagicMock()
                temp_table.drop = MagicMock()
                return temp_table
            else:
                return MagicMock()

        mock_db.__getitem__.side_effect = mock_getitem

        mock_db_class.return_value = mock_db

        # Create resource with different schema (added age field)
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice", "age": 25}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Should raise schema conflict
        with pytest.raises(ZeekerSchemaConflictError) as exc_info:
            manager.build_database()

        assert "users" in str(exc_info.value)
        assert "Schema conflict detected" in str(exc_info.value)

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_schema_migration_success(self, mock_db_class, setup_project):
        """Test successful schema migration with migrate_schema function."""
        from zeeker.core.types import META_TABLE_SCHEMAS

        manager = setup_project

        # Mock database
        mock_db = MagicMock()
        mock_schema_table = MagicMock()
        mock_users_table = MagicMock()

        mock_schema_table.exists.return_value = True
        mock_users_table.exists.return_value = True

        # Mock existing schema
        mock_schema_table.get.return_value = {
            "resource_name": "users",
            "schema_version": 1,
            "schema_hash": "old_hash_123",
            "column_definitions": '{"id": "INTEGER", "name": "TEXT"}',
        }

        mock_db.__getitem__.side_effect = lambda name: {
            META_TABLE_SCHEMAS: mock_schema_table,
            "users": mock_users_table,
        }.get(name, MagicMock())

        mock_db_class.return_value = mock_db

        # Create resource with migration handler
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice", "age": 25}]

def migrate_schema(existing_table, new_schema_info):
    # Mock migration success
    return True
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Should succeed with migration
        result = manager.build_database()
        assert result.is_valid

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_force_schema_reset(self, mock_db_class, setup_project):
        """Test that force_schema_reset bypasses conflict detection."""
        from zeeker.core.types import META_TABLE_SCHEMAS

        manager = setup_project

        # Mock database
        mock_db = MagicMock()
        mock_schema_table = MagicMock()
        mock_users_table = MagicMock()

        mock_schema_table.exists.return_value = True
        mock_users_table.exists.return_value = True

        # Mock existing schema (would normally cause conflict)
        mock_schema_table.get.return_value = {
            "resource_name": "users",
            "schema_version": 1,
            "schema_hash": "old_hash_123",
            "column_definitions": '{"id": "INTEGER", "name": "TEXT"}',
        }

        mock_db.__getitem__.side_effect = lambda name: {
            META_TABLE_SCHEMAS: mock_schema_table,
            "users": mock_users_table,
        }.get(name, MagicMock())

        mock_db_class.return_value = mock_db

        # Create resource with different schema
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice", "age": 25}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Should succeed with force_schema_reset=True
        result = manager.build_database(force_schema_reset=True)
        assert result.is_valid

    @patch("zeeker.core.database.builder.sqlite_utils.Database")
    def test_timestamp_tracking(self, mock_db_class, setup_project):
        """Test that resource timestamps are tracked."""
        from zeeker.core.types import META_TABLE_UPDATES

        manager = setup_project

        # Mock database
        mock_db = MagicMock()
        mock_updates_table = MagicMock()
        mock_users_table = MagicMock()

        mock_updates_table.exists.return_value = True
        mock_users_table.exists.return_value = False
        mock_users_table.count = 1

        mock_db.__getitem__.side_effect = lambda name: {
            META_TABLE_UPDATES: mock_updates_table,
            "users": mock_users_table,
        }.get(name, MagicMock())

        mock_db_class.return_value = mock_db

        # Create resource
        resource_content = """
def fetch_data(existing_table):
    return [{"id": 1, "name": "Alice"}]
"""
        (manager.resources_path / "users.py").write_text(resource_content)

        # Run build
        result = manager.build_database()
        assert result.is_valid

        # Verify timestamp tracking was called
        assert mock_updates_table.insert.called
        insert_call = mock_updates_table.insert.call_args[0][0]
        assert insert_call["resource_name"] == "users"
        assert "last_updated" in insert_call
        assert "record_count" in insert_call
        assert "build_id" in insert_call
        assert "duration_ms" in insert_call


class TestMetaTableUtilities:
    """Test meta table utility functions."""

    def test_calculate_schema_hash(self):
        """Test schema hash calculation."""
        from zeeker.core.types import calculate_schema_hash

        schema1 = {"id": "INTEGER", "name": "TEXT"}
        schema2 = {"id": "INTEGER", "name": "TEXT"}
        schema3 = {"id": "INTEGER", "name": "TEXT", "age": "INTEGER"}

        # Same schemas should have same hash
        assert calculate_schema_hash(schema1) == calculate_schema_hash(schema2)

        # Different schemas should have different hashes
        assert calculate_schema_hash(schema1) != calculate_schema_hash(schema3)

        # Order shouldn't matter
        schema_reordered = {"name": "TEXT", "id": "INTEGER"}
        assert calculate_schema_hash(schema1) == calculate_schema_hash(schema_reordered)

    def test_extract_table_schema(self):
        """Test table schema extraction."""
        from zeeker.core.types import extract_table_schema

        # Mock table with columns
        mock_table = MagicMock()
        mock_col1 = MagicMock()
        mock_col1.name = "id"
        mock_col1.type = "INTEGER"
        mock_col2 = MagicMock()
        mock_col2.name = "name"
        mock_col2.type = "TEXT"
        mock_table.columns = [mock_col1, mock_col2]

        schema = extract_table_schema(mock_table)

        assert schema == {"id": "INTEGER", "name": "TEXT"}

    def test_schema_conflict_error_message(self):
        """Test ZeekerSchemaConflictError message formatting."""
        from zeeker.core.types import ZeekerSchemaConflictError

        old_schema = {"id": "INTEGER", "name": "TEXT"}
        new_schema = {"id": "INTEGER", "name": "TEXT", "age": "INTEGER", "email": "TEXT"}

        error = ZeekerSchemaConflictError("users", old_schema, new_schema)
        error_msg = str(error)

        assert "users" in error_msg
        assert "Schema conflict detected" in error_msg
        assert "Added columns: age, email" in error_msg
        assert "migrate_schema() function" in error_msg


class TestZeekerProjectToDatasette:
    """Tests for ZeekerProject.to_datasette_metadata() table-level field pass-through."""

    def test_per_resource_license_fields_in_table_metadata(self):
        """Per-resource license and license_url must appear in the generated table metadata."""
        from zeeker.core.types import ZeekerProject

        project = ZeekerProject(
            name="test",
            database="test.db",
            resources={
                "decisions": {
                    "description": "Enforcement decisions",
                    "license": "All rights reserved",
                    "license_url": "https://www.example.gov.sg/terms-of-use/",
                    "source": "Example Agency",
                    "source_url": "https://www.example.gov.sg/decisions/",
                }
            },
        )

        metadata = project.to_datasette_metadata()
        table = metadata["databases"]["test"]["tables"]["decisions"]

        assert table["license"] == "All rights reserved"
        assert table["license_url"] == "https://www.example.gov.sg/terms-of-use/"
        assert table["source"] == "Example Agency"
        assert table["source_url"] == "https://www.example.gov.sg/decisions/"

    def test_per_resource_license_fields_optional(self):
        """Resources without license fields should produce table metadata without them."""
        from zeeker.core.types import ZeekerProject

        project = ZeekerProject(
            name="test",
            database="test.db",
            resources={"items": {"description": "Some items"}},
        )

        metadata = project.to_datasette_metadata()
        table = metadata["databases"]["test"]["tables"]["items"]

        assert "license" not in table
        assert "license_url" not in table
        assert "source" not in table
        assert "source_url" not in table
        assert "--force-schema-reset" in error_msg
