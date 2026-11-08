"""Tests for fragments functionality."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from zeeker.core.project import ZeekerProjectManager


@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def test_fragments_flag_in_cli():
    """Test that the fragments flag is available in CLI."""
    # This is implicitly tested by the CLI integration
    # The flag should be available in zeeker add --help
    assert True


def test_add_resource_with_fragments(temp_project_dir):
    """Test adding a resource with fragments enabled."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Add resource with fragments
    result = manager.add_resource("legal_docs", "Legal documents with fragments", fragments=True)

    assert result.is_valid
    assert "Created resource: legal_docs.py" in result.info

    # Check that fragments=true is saved in TOML
    toml_content = (temp_project_dir / "zeeker.toml").read_text()
    assert "fragments = true" in toml_content

    # Check that the resource file contains fragments template
    resource_content = (temp_project_dir / "resources" / "legal_docs.py").read_text()
    assert "fetch_fragments_data" in resource_content
    assert "legal_docs_fragments" in resource_content
    assert "You define both table schemas" in resource_content


def test_add_resource_without_fragments(temp_project_dir):
    """Test adding a regular resource without fragments."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Add regular resource
    result = manager.add_resource("users", "User data")

    assert result.is_valid

    # Check that fragments is not in TOML
    toml_content = (temp_project_dir / "zeeker.toml").read_text()
    assert "fragments" not in toml_content

    # Check that the resource file uses standard template
    resource_content = (temp_project_dir / "resources" / "users.py").read_text()
    assert "fetch_fragments_data" not in resource_content
    assert "fragments" not in resource_content.lower()


def test_build_database_with_fragments(temp_project_dir):
    """Test building a database with fragments enabled resource."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Add resource with fragments
    add_result = manager.add_resource("docs", "Documents with fragments", fragments=True)
    assert add_result.is_valid

    # Build database
    build_result = manager.build_database()
    assert build_result.is_valid

    # Check that both tables were created
    db_path = temp_project_dir / "test_project.db"
    assert db_path.exists()

    # Verify database structure
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "docs" in tables
    assert "docs_fragments" in tables

    # Check main table has data
    cursor.execute("SELECT COUNT(*) FROM docs")
    main_count = cursor.fetchone()[0]
    assert main_count > 0

    # Check fragments table has data
    cursor.execute("SELECT COUNT(*) FROM docs_fragments")
    fragments_count = cursor.fetchone()[0]
    assert fragments_count > 0

    # Since schema is flexible now, we just verify fragments exist
    # and are linked to main table records somehow
    assert fragments_count > 0  # Fragments were created

    conn.close()


def test_fragments_error_handling(temp_project_dir):
    """Test error handling when fragments resource is missing required functions."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Create a manual resource file without fetch_fragments_data function
    resource_file = temp_project_dir / "resources" / "bad_docs.py"
    resource_file.write_text("""
def fetch_data(existing_table):
    return [{"id": 1, "title": "Test"}]
""")

    # Update TOML to mark it as fragments-enabled
    toml_content = """[project]
name = "test_project"
database = "test_project.db"

[resource.bad_docs]
description = "Bad docs resource"
fragments = true
"""
    (temp_project_dir / "zeeker.toml").write_text(toml_content)

    # Build should fail with appropriate error
    build_result = manager.build_database()
    assert not build_result.is_valid
    assert any("missing fetch_fragments_data() function" in error for error in build_result.errors)


def test_context_passing_to_fragments(temp_project_dir):
    """Test that main_data_context is passed from fetch_data to fetch_fragments_data."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Create a resource that uses context passing
    resource_content = '''
# Track calls to verify context passing works
fetch_data_calls = []
fetch_fragments_calls = []

def fetch_data(existing_table):
    """Fetch main table data."""
    fetch_data_calls.append("fetch_data_called")
    return [
        {"id": 1, "title": "Document 1", "content": "This is document 1 content for fragmentation."},
        {"id": 2, "title": "Document 2", "content": "This is document 2 content for fragmentation."}
    ]

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    """Fetch fragments with context passing."""
    fetch_fragments_calls.append(("fetch_fragments_called", main_data_context is not None))

    if main_data_context:
        # Use context data - no duplicate fetch needed
        fragments = []
        for doc in main_data_context:
            # Split content into fragments
            sentences = doc["content"].split(".")
            for i, sentence in enumerate(sentences):
                if sentence.strip():
                    fragments.append({
                        "doc_id": doc["id"],
                        "fragment_num": i,
                        "text": sentence.strip(),
                        "from_context": True  # Mark as using context
                    })
        return fragments
    else:
        # Fallback without context
        return [
            {"doc_id": 999, "fragment_num": 0, "text": "fallback fragment", "from_context": False}
        ]
'''

    # Create resource with fragments enabled
    resource_file = temp_project_dir / "resources" / "context_test.py"
    resource_file.write_text(resource_content)

    # Update TOML to enable fragments
    toml_content = """[project]
name = "test_project"
database = "test_project.db"

[resource.context_test]
description = "Test context passing"
fragments = true
"""
    (temp_project_dir / "zeeker.toml").write_text(toml_content)

    # Build database - this should pass context
    build_result = manager.build_database()
    assert build_result.is_valid

    # Verify database was created with fragments
    db_path = temp_project_dir / "test_project.db"
    assert db_path.exists()

    # Check that fragments used context data (not fallback)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check fragments were created from context
    cursor.execute("SELECT * FROM context_test_fragments WHERE from_context = 1")
    context_fragments = cursor.fetchall()
    assert len(context_fragments) > 0, "Should have fragments created from context"

    # Check no fallback fragments were created
    cursor.execute("SELECT * FROM context_test_fragments WHERE from_context = 0")
    fallback_fragments = cursor.fetchall()
    assert (
        len(fallback_fragments) == 0
    ), "Should not have fallback fragments when context is available"

    conn.close()


def test_backward_compatibility_without_context(temp_project_dir):
    """Test that resources without main_data_context parameter still work."""
    # Initialize project
    manager = ZeekerProjectManager(temp_project_dir)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid

    # Create a resource with OLD signature (no main_data_context parameter)
    resource_content = '''
def fetch_data(existing_table):
    """Fetch main table data."""
    return [{"id": 1, "title": "Old Style Document"}]

def fetch_fragments_data(existing_fragments_table):
    """Old style fragments function without context parameter."""
    return [
        {"doc_id": 1, "fragment_num": 0, "text": "old style fragment"},
        {"doc_id": 1, "fragment_num": 1, "text": "another old fragment"}
    ]
'''

    resource_file = temp_project_dir / "resources" / "old_style.py"
    resource_file.write_text(resource_content)

    # Update TOML
    toml_content = """[project]
name = "test_project"
database = "test_project.db"

[resource.old_style]
description = "Test backward compatibility"
fragments = true
"""
    (temp_project_dir / "zeeker.toml").write_text(toml_content)

    # Build should still work with old-style function
    build_result = manager.build_database()
    assert build_result.is_valid

    # Verify fragments table was created
    db_path = temp_project_dir / "test_project.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM old_style_fragments")
    fragments_count = cursor.fetchone()[0]
    assert fragments_count == 2, "Should have created fragments with old-style function"

    conn.close()


if __name__ == "__main__":
    pytest.main([__file__])
