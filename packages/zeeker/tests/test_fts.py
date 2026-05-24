"""Tests for FTS (Full-Text Search) functionality."""

import tempfile
from pathlib import Path

import pytest
import sqlite_utils

from zeeker.core.database.fts_processor import FTSProcessor
from zeeker.core.project import ZeekerProjectManager
from zeeker.core.types import ZeekerProject


@pytest.fixture
def temp_project_dir():
    """Create temporary project directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def test_fts_processor_setup(temp_project_dir):
    """Test FTS processor can set up FTS on tables."""
    # Create a project with FTS configuration
    project = ZeekerProject(
        name="test_fts",
        database="test_fts.db",
        resources={
            "documents": {"description": "Test documents", "fts_fields": ["title", "content"]}
        },
        root_path=temp_project_dir,
    )

    # Create test database and table
    db_path = temp_project_dir / "test_fts.db"
    db = sqlite_utils.Database(str(db_path))

    # Insert test data
    test_data = [
        {"id": 1, "title": "First Document", "content": "This is the first document content"},
        {"id": 2, "title": "Second Document", "content": "This is the second document content"},
    ]
    db["documents"].insert_all(test_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    assert "Enabled FTS on table 'documents' for fields: title, content" in result.info

    # Verify FTS table was created
    assert "documents_fts" in db.table_names()

    # Test FTS search works
    search_results = list(
        db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'first'")
    )
    assert len(search_results) == 1


def test_fts_with_fragments(temp_project_dir):
    """Test FTS setup with fragments table using explicit configuration."""
    project = ZeekerProject(
        name="test_fragments_fts",
        database="test_fragments_fts.db",
        resources={
            "docs": {
                "description": "Test documents with fragments",
                "fragments": True,
                "fts_fields": ["title"],
                "fragments_fts_fields": ["text"],  # Explicitly configured
            }
        },
        root_path=temp_project_dir,
    )

    # Create test database with main and fragments tables
    db_path = temp_project_dir / "test_fragments_fts.db"
    db = sqlite_utils.Database(str(db_path))

    # Insert main table data
    main_data = [{"id": 1, "title": "Document 1", "summary": "Summary 1"}]
    db["docs"].insert_all(main_data)

    # Insert fragments data
    fragments_data = [
        {"parent_id": 1, "text": "This is the first fragment of the document"},
        {"parent_id": 1, "text": "This is the second fragment with different content"},
    ]
    db["docs_fragments"].insert_all(fragments_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    assert "Enabled FTS on table 'docs' for fields: title" in result.info
    assert "Enabled FTS on table 'docs_fragments' for fields: text" in result.info

    # Verify both FTS tables were created
    assert "docs_fts" in db.table_names()
    assert "docs_fragments_fts" in db.table_names()


def test_fts_auto_detect_fragments_text_field(temp_project_dir):
    """Test FTS auto-detection on fragments table with 'text' field."""
    project = ZeekerProject(
        name="test_auto_fts",
        database="test_auto_fts.db",
        resources={
            "docs": {
                "description": "Test documents with fragments",
                "fragments": True,
                # No fragments_fts_fields specified - should auto-detect
            }
        },
        root_path=temp_project_dir,
    )

    # Create test database with fragments table containing "text" field
    db_path = temp_project_dir / "test_auto_fts.db"
    db = sqlite_utils.Database(str(db_path))

    # Insert fragments data with "text" field
    fragments_data = [
        {"parent_id": 1, "text": "This is automatically detected text content"},
        {"parent_id": 1, "text": "Another fragment with searchable content"},
    ]
    db["docs_fragments"].insert_all(fragments_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    assert "Enabled FTS on table 'docs_fragments' for fields: text" in result.info

    # Verify FTS table was created
    assert "docs_fragments_fts" in db.table_names()

    # Test that search works
    search_results = list(
        db.execute(
            "SELECT * FROM docs_fragments_fts WHERE docs_fragments_fts MATCH 'automatically'"
        )
    )
    assert len(search_results) == 1


def test_fts_auto_detect_fragments_content_field(temp_project_dir):
    """Test FTS auto-detection on fragments table with 'content' field."""
    project = ZeekerProject(
        name="test_auto_content",
        database="test_auto_content.db",
        resources={
            "pages": {
                "description": "Test pages with fragments",
                "fragments": True,
                # No fragments_fts_fields specified - should auto-detect "content"
            }
        },
        root_path=temp_project_dir,
    )

    # Create test database with fragments table containing "content" field
    db_path = temp_project_dir / "test_auto_content.db"
    db = sqlite_utils.Database(str(db_path))

    # Insert fragments data with "content" field (no "text" field present)
    fragments_data = [
        {"parent_id": 1, "content": "Page content for searching"},
        {"parent_id": 1, "content": "More searchable page content"},
    ]
    db["pages_fragments"].insert_all(fragments_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    assert "Enabled FTS on table 'pages_fragments' for fields: content" in result.info

    # Verify FTS table was created
    assert "pages_fragments_fts" in db.table_names()


def test_fts_auto_detect_fallback_to_text_columns(temp_project_dir):
    """Test FTS auto-detection falls back to any TEXT columns when no common fields found."""
    project = ZeekerProject(
        name="test_fallback",
        database="test_fallback.db",
        resources={
            "custom": {
                "description": "Custom fragments table",
                "fragments": True,
            }
        },
        root_path=temp_project_dir,
    )

    # Create test database with fragments table with custom field names
    db_path = temp_project_dir / "test_fallback.db"
    db = sqlite_utils.Database(str(db_path))

    # Insert fragments data with custom text field names
    fragments_data = [
        {
            "parent_id": 1,
            "searchable_data": "Custom searchable content",
            "metadata": "non-searchable",
        },
        {"parent_id": 1, "searchable_data": "More custom content", "metadata": "more-meta"},
    ]
    db["custom_fragments"].insert_all(fragments_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    # Should find and use the searchable_data field
    assert "Enabled FTS on table 'custom_fragments'" in result.info[0]
    assert "searchable_data" in result.info[0]


def test_fts_no_auto_detect_when_explicitly_configured(temp_project_dir):
    """Test that auto-detection is skipped when fragments_fts_fields is explicitly set."""
    project = ZeekerProject(
        name="test_explicit",
        database="test_explicit.db",
        resources={
            "docs": {
                "description": "Test documents",
                "fragments": True,
                "fragments_fts_fields": ["custom_field"],  # Explicitly configured
            }
        },
        root_path=temp_project_dir,
    )

    # Create test database with both "text" and "custom_field"
    db_path = temp_project_dir / "test_explicit.db"
    db = sqlite_utils.Database(str(db_path))

    fragments_data = [
        {
            "parent_id": 1,
            "text": "This should NOT be used for FTS",
            "custom_field": "This should be used for FTS",
        }
    ]
    db["docs_fragments"].insert_all(fragments_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    # Should use the explicitly configured field, not auto-detected "text"
    assert "Enabled FTS on table 'docs_fragments' for fields: custom_field" in result.info


def test_fts_invalid_fields_warning(temp_project_dir):
    """Test FTS processor handles invalid field names gracefully."""
    project = ZeekerProject(
        name="test_invalid_fts",
        database="test_invalid_fts.db",
        resources={
            "docs": {"description": "Test documents", "fts_fields": ["title", "nonexistent_field"]}
        },
        root_path=temp_project_dir,
    )

    # Create test database with limited columns
    db_path = temp_project_dir / "test_invalid_fts.db"
    db = sqlite_utils.Database(str(db_path))

    test_data = [{"id": 1, "title": "Test Doc"}]
    db["docs"].insert_all(test_data)

    # Set up FTS
    fts_processor = FTSProcessor(project)
    result = fts_processor.setup_fts_for_database(db)

    assert result.is_valid
    assert "Column 'nonexistent_field' not found in table 'docs', skipping" in result.warnings
    assert "Enabled FTS on table 'docs' for fields: title" in result.info


def test_add_resource_with_fts_fields(temp_project_dir):
    """Test adding a resource with FTS fields through CLI-like interface."""
    import os

    # Change to temp directory first
    original_dir = os.getcwd()
    os.chdir(temp_project_dir)

    try:
        manager = ZeekerProjectManager()

        # Initialize project
        init_result = manager.init_project("test_fts_project")
        assert init_result.is_valid

        # Add resource with FTS fields
        add_result = manager.add_resource(
            "searchable_docs",
            "Searchable documents",
            fts_fields=["title", "content"],
            fragments=True,
            fragments_fts_fields=["text", "summary"],
        )
        assert add_result.is_valid

        # Check zeeker.toml contains FTS configuration
        toml_content = (temp_project_dir / "zeeker.toml").read_text()
        assert 'fts_fields = ["title", "content"]' in toml_content
        assert 'fragments_fts_fields = ["text", "summary"]' in toml_content
        assert "fragments = true" in toml_content
    finally:
        os.chdir(original_dir)


def test_get_fts_config_for_resource():
    """Test getting FTS configuration for a resource."""
    project = ZeekerProject(
        name="test_config",
        database="test.db",
        resources={
            "docs": {
                "description": "Documents",
                "fragments": True,
                "fts_fields": ["title", "content"],
                "fragments_fts_fields": ["text"],  # Explicitly configured
            },
            "auto_docs": {
                "description": "Auto-detect docs",
                "fragments": True,
                "fts_fields": ["title"],
                # No fragments_fts_fields - should auto-detect
            },
            "simple": {"description": "Simple table", "fts_fields": ["name"]},
        },
    )

    fts_processor = FTSProcessor(project)

    # Test resource with explicit fragments FTS configuration
    docs_config = fts_processor.get_fts_config_for_resource("docs")
    assert docs_config["fts_fields"] == ["title", "content"]
    assert docs_config["fragments_fts_fields"] == ["text"]
    assert docs_config["has_fragments"] is True
    assert docs_config["auto_detect_fragments_fts"] is False

    # Test resource with auto-detect fragments FTS
    auto_config = fts_processor.get_fts_config_for_resource("auto_docs")
    assert auto_config["fts_fields"] == ["title"]
    assert auto_config["fragments_fts_fields"] is None  # Will trigger auto-detection
    assert auto_config["has_fragments"] is True
    assert auto_config["auto_detect_fragments_fts"] is True

    # Test simple resource
    simple_config = fts_processor.get_fts_config_for_resource("simple")
    assert simple_config["fts_fields"] == ["name"]
    assert simple_config["fragments_fts_fields"] == []
    assert simple_config["has_fragments"] is False
    assert simple_config["auto_detect_fragments_fts"] is False

    # Test non-existent resource
    missing_config = fts_processor.get_fts_config_for_resource("missing")
    assert missing_config["fts_fields"] == []
    assert missing_config["fragments_fts_fields"] == []
    assert missing_config["has_fragments"] is False
    assert missing_config["auto_detect_fragments_fts"] is False


def test_fts_processor_idempotent(temp_project_dir):
    """FTS only needs to be enabled once. Subsequent runs must be no-ops; the
    triggers created on the first run keep the index in sync as rows change.
    """
    project = ZeekerProject(
        name="test_fts_idempotent",
        database="test_fts_idempotent.db",
        resources={
            "docs": {"description": "Test documents", "fts_fields": ["title", "content"]}
        },
        root_path=temp_project_dir,
    )

    db_path = temp_project_dir / "test_fts_idempotent.db"
    db = sqlite_utils.Database(str(db_path))
    db["docs"].insert_all(
        [
            {"id": 1, "title": "Hello world", "content": "first body"},
            {"id": 2, "title": "Goodbye world", "content": "second body"},
        ]
    )

    fts_processor = FTSProcessor(project)

    # First run: creates docs_fts, populates from existing rows, installs triggers.
    first = fts_processor.setup_fts_for_database(db)
    assert first.is_valid, first.errors
    assert "docs_fts" in db.table_names()
    initial_count = db.execute("SELECT count(*) FROM docs_fts").fetchone()[0]
    assert initial_count == 2

    # Insert a new row through the source table — the AFTER INSERT trigger
    # should add it to the FTS index without us doing anything.
    db["docs"].insert({"id": 3, "title": "Trigger test", "content": "third body"})
    rows = list(db.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'trigger'"))
    assert len(rows) == 1, "AFTER INSERT trigger should have indexed the new row"

    # Second run: docs_fts already exists with matching schema + triggers.
    # sqlite-utils' enable_fts(replace=True) must early-return without
    # rebuilding (which would otherwise duplicate or churn the index).
    second = fts_processor.setup_fts_for_database(db)
    assert second.is_valid, second.errors
    assert db.execute("SELECT count(*) FROM docs_fts").fetchone()[0] == 3
    rows = list(db.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'hello'"))
    assert len(rows) == 1
    rows = list(db.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'trigger'"))
    assert len(rows) == 1
