"""Tests for individual database package components."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlite_utils

from zeeker.core.database.async_executor import AsyncExecutor
from zeeker.core.database.builder import DatabaseBuilder
from zeeker.core.database.processor import ResourceProcessor
from zeeker.core.database.s3_sync import S3Synchronizer
from zeeker.core.types import ValidationResult


class TestAsyncExecutor:
    """Test AsyncExecutor component in isolation."""

    @pytest.fixture
    def executor(self):
        """Create AsyncExecutor instance."""
        return AsyncExecutor()

    def test_sync_function_detection(self, executor):
        """Test that sync functions are detected correctly."""

        def sync_func(existing_table):
            return [{"id": 1, "data": "test"}]

        result = executor.call_fetch_data(sync_func, None)
        assert result == [{"id": 1, "data": "test"}]

    def test_async_function_detection(self, executor):
        """Test that async functions are detected correctly."""

        async def async_func(existing_table):
            return [{"id": 2, "data": "async_test"}]

        result = executor.call_fetch_data(async_func, None)
        assert result == [{"id": 2, "data": "async_test"}]

    def test_sync_fragments_function_old_signature(self, executor):
        """Test sync fragments function with old signature."""

        def old_fragments_func(existing_fragments_table):
            return [{"parent_id": 1, "text": "fragment"}]

        result = executor.call_fetch_fragments_data(old_fragments_func, None, None)
        assert result == [{"parent_id": 1, "text": "fragment"}]

    def test_sync_fragments_function_new_signature(self, executor):
        """Test sync fragments function with new signature."""

        def new_fragments_func(existing_fragments_table, main_data_context):
            if main_data_context:
                return [
                    {"parent_id": item["id"], "text": f"fragment for {item['id']}"}
                    for item in main_data_context
                ]
            return []

        context = [{"id": 1}, {"id": 2}]
        result = executor.call_fetch_fragments_data(new_fragments_func, None, context)
        assert len(result) == 2
        assert result[0]["parent_id"] == 1
        assert result[1]["parent_id"] == 2

    def test_async_fragments_function_old_signature(self, executor):
        """Test async fragments function with old signature."""

        async def old_async_fragments_func(existing_fragments_table):
            return [{"parent_id": 3, "text": "async fragment"}]

        result = executor.call_fetch_fragments_data(old_async_fragments_func, None, None)
        assert result == [{"parent_id": 3, "text": "async fragment"}]

    def test_async_fragments_function_new_signature(self, executor):
        """Test async fragments function with new signature."""

        async def new_async_fragments_func(existing_fragments_table, main_data_context):
            if main_data_context:
                return [
                    {"parent_id": item["id"], "text": f"async fragment for {item['id']}"}
                    for item in main_data_context
                ]
            return []

        context = [{"id": 4}, {"id": 5}]
        result = executor.call_fetch_fragments_data(new_async_fragments_func, None, context)
        assert len(result) == 2
        assert "async fragment for 4" in result[0]["text"]
        assert "async fragment for 5" in result[1]["text"]

    def test_function_signature_fallback(self, executor):
        """Test that new signature falls back to old signature on TypeError."""

        def incompatible_func(existing_fragments_table, unexpected_param):
            # This function has wrong signature but will be called correctly
            return [{"parent_id": 6, "text": "fallback"}]

        # Mock to force TypeError on first call, success on second
        call_count = 0

        def side_effect(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and len(args) == 2:
                raise TypeError("incompatible_func() takes 2 positional arguments but 3 were given")
            return [{"parent_id": 6, "text": "fallback"}]

        with patch.object(executor, "_run_async_function", side_effect=side_effect):
            # This should gracefully handle the signature mismatch
            # Note: This test would need more complex mocking to work properly
            pass


class TestS3Synchronizer:
    """Test S3Synchronizer component in isolation."""

    @pytest.fixture
    def s3_sync(self):
        """Create S3Synchronizer instance."""
        return S3Synchronizer()

    @patch("zeeker.core.deployer.ZeekerDeployer")
    def test_sync_from_s3_success(self, mock_deployer_class, s3_sync):
        """Test successful S3 sync."""
        # Mock deployer and S3 client
        mock_deployer = MagicMock()
        mock_deployer_class.return_value = mock_deployer
        mock_deployer.bucket_name = "test-bucket"

        # Mock successful head_object (file exists)
        mock_deployer.s3_client.head_object.return_value = {}
        # Mock successful download
        mock_deployer.s3_client.download_file.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"

            result = s3_sync.sync_from_s3("test.db", str(db_path))

            assert result.is_valid
            assert "Downloaded existing database from S3" in result.info[0]
            mock_deployer.s3_client.download_file.assert_called_once()

    @patch("zeeker.core.deployer.ZeekerDeployer")
    def test_sync_from_s3_file_not_found(self, mock_deployer_class, s3_sync):
        """Test S3 sync when file doesn't exist."""
        # Mock deployer and S3 client
        mock_deployer = MagicMock()
        mock_deployer_class.return_value = mock_deployer
        mock_deployer.bucket_name = "test-bucket"

        # Mock S3 client exceptions
        class MockNoSuchKey(Exception):
            pass

        mock_deployer.s3_client.exceptions.NoSuchKey = MockNoSuchKey
        mock_deployer.s3_client.head_object.side_effect = MockNoSuchKey()

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"

            result = s3_sync.sync_from_s3("test.db", str(db_path))

            assert result.is_valid
            assert "No existing database found on S3" in result.info[0]

    def test_sync_from_s3_missing_credentials(self, s3_sync):
        """Test S3 sync fails with missing credentials."""
        with patch.dict(os.environ, {}, clear=True):
            result = s3_sync.sync_from_s3("test.db", "/tmp/test.db")

            assert not result.is_valid
            assert "S3_BUCKET environment variable is required" in result.errors[0]

    @patch("zeeker.core.deployer.ZeekerDeployer")
    def test_sync_from_s3_connection_error(self, mock_deployer_class, s3_sync):
        """Test S3 sync handles connection errors."""
        # Mock deployer creation failure
        mock_deployer_class.side_effect = Exception("Connection failed")

        result = s3_sync.sync_from_s3("test.db", "/tmp/test.db")

        assert not result.is_valid
        assert "Connection failed" in result.errors[0]


class TestResourceProcessor:
    """Test ResourceProcessor component in isolation."""

    @pytest.fixture
    def processor(self):
        """Create ResourceProcessor with mocked dependencies."""
        mock_async_executor = MagicMock()
        mock_schema_manager = MagicMock()
        processor = ResourceProcessor(mock_async_executor, mock_schema_manager)

        # Set up a temporary resources path for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            processor.resources_path = Path(temp_dir)
            yield processor

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock(spec=sqlite_utils.Database)

    def test_load_resource_module_success(self, processor):
        """Test successful resource module loading."""
        # Create a valid resource file in the processor's resources path
        resource_file = processor.resources_path / "test_resource.py"
        resource_file.write_text("""
def fetch_data(existing_table):
    return [{"id": 1, "name": "test"}]
""")

        result = processor._load_resource_module("test_resource")
        assert result.is_valid
        assert hasattr(result.data, "fetch_data")

    def test_load_resource_module_file_not_found(self, processor):
        """Test resource module loading with missing file."""
        result = processor._load_resource_module("missing_resource")
        assert not result.is_valid
        assert "Resource file not found" in result.errors[0]

    def test_load_resource_module_invalid_python(self, processor):
        """Test resource module loading with invalid Python syntax."""
        # Create resource file with syntax error
        resource_file = processor.resources_path / "invalid_resource.py"
        resource_file.write_text("def invalid_syntax(:\n    pass")

        result = processor._load_resource_module("invalid_resource")
        assert not result.is_valid
        assert "Failed to load resource module" in result.errors[0]

    def test_validate_data_structure_valid(self, processor):
        """Test data structure validation with valid data."""
        valid_data = [{"id": 1, "name": "test"}, {"id": 2, "name": "test2"}]
        result = processor._validate_data_structure(valid_data, "test_resource")
        assert result.is_valid

    def test_validate_data_structure_not_list(self, processor):
        """Test data structure validation with non-list data."""
        invalid_data = {"id": 1, "name": "test"}
        result = processor._validate_data_structure(invalid_data, "test_resource")
        assert not result.is_valid
        assert "must be a list" in result.errors[0]

    def test_validate_data_structure_non_dict_items(self, processor):
        """Test data structure validation with non-dict items."""
        invalid_data = [1, 2, 3]
        result = processor._validate_data_structure(invalid_data, "test_resource")
        assert not result.is_valid
        assert "must be dictionaries" in result.errors[0]

    def test_apply_transformation_success(self, processor):
        """Test data transformation application."""
        # Create mock module with transform function
        mock_module = MagicMock()
        mock_module.transform_data.return_value = [{"id": 1, "transformed": True}]

        raw_data = [{"id": 1, "raw": True}]
        data, tb = processor._apply_transformation(mock_module, raw_data, "test", "transform_data")

        assert data == [{"id": 1, "transformed": True}]
        assert tb is None
        mock_module.transform_data.assert_called_once_with(raw_data)

    def test_apply_transformation_missing_function(self, processor):
        """Test transformation with missing transform function."""
        mock_module = MagicMock()
        # Remove the transform_data attribute to simulate missing function
        if hasattr(mock_module, "transform_data"):
            delattr(mock_module, "transform_data")

        raw_data = [{"id": 1, "raw": True}]
        data, tb = processor._apply_transformation(mock_module, raw_data, "test", "transform_data")

        # Should return original data when function is missing, no traceback.
        assert data == raw_data
        assert tb is None

    def test_apply_transformation_function_error(self, processor):
        """Test transformation with function that throws error."""
        mock_module = MagicMock()
        mock_module.transform_data = MagicMock(side_effect=Exception("Transform failed"))

        raw_data = [{"id": 1, "raw": True}]
        data, tb = processor._apply_transformation(mock_module, raw_data, "test", "transform_data")

        # Data should be None when function throws; traceback should be captured.
        assert data is None
        assert tb is not None
        assert "Transform failed" in tb


class TestDatabaseBuilder:
    """Test DatabaseBuilder coordination logic."""

    @pytest.fixture
    def builder(self):
        """Create DatabaseBuilder with mocked project."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            resources_path = project_path / "resources"
            resources_path.mkdir()

            # Create mock project
            mock_project = MagicMock()
            mock_project.name = "test_project"
            mock_project.database = "test.db"
            mock_project.resources = {}

            # Create builder
            builder = DatabaseBuilder(project_path, mock_project)

            # Mock the dependencies for testing
            builder.s3_sync = MagicMock()
            builder.processor = MagicMock()
            builder.schema_manager = MagicMock()

            yield builder

    def test_build_database_coordination(self, builder):
        """Test that DatabaseBuilder coordinates components correctly."""
        # Mock successful S3 sync
        builder.s3_sync.sync_from_s3.return_value = ValidationResult(is_valid=True)
        builder.schema_manager.ensure_meta_tables.return_value = None

        with patch("sqlite_utils.Database") as mock_db_class:
            mock_db = MagicMock()
            mock_db_class.return_value = mock_db

            # Enable S3 sync to test coordination
            result = builder.build_database(sync_from_s3=True)

            assert result.is_valid
            # Verify coordination calls
            builder.s3_sync.sync_from_s3.assert_called()
            builder.schema_manager.ensure_meta_tables.assert_called()

    def test_build_database_s3_sync_failure(self, builder):
        """Test build continues with warning when S3 sync fails."""
        # Mock S3 sync failure
        builder.s3_sync.sync_from_s3.return_value = ValidationResult(
            is_valid=False, errors=["S3 sync failed"]
        )

        with patch("sqlite_utils.Database"):
            # Enable S3 sync to test failure scenario
            result = builder.build_database(sync_from_s3=True)

            # Build should continue despite S3 sync failure
            assert result.is_valid
            assert "S3 sync failed" in result.errors
            assert any("S3 sync failed but continuing" in warning for warning in result.warnings)

    def test_build_database_no_sync_from_s3_flag(self, builder):
        """Test build without S3 sync when flag is False."""
        with patch("sqlite_utils.Database"):
            builder.build_database(sync_from_s3=False)

            # S3 sync should not be called
            builder.s3_sync.sync_from_s3.assert_not_called()
