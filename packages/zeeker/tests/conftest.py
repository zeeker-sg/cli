"""
Test configuration and shared fixtures for Zeeker tests.
"""

import json
import os
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test file operations."""
    with tempfile.TemporaryDirectory() as temp_path:
        yield Path(temp_path)


@pytest.fixture
def sample_project_dir(temp_dir):
    """Create a sample project directory structure."""
    project_dir = temp_dir / "test_project"
    project_dir.mkdir()

    # Create zeeker.toml
    toml_content = textwrap.dedent("""[project]
name = "test_project"
database = "test_project.db"

[resource.users]
description = "User account data"
facets = ["role", "department"]
size = 50

[resource.posts]
description = "Blog posts"
sort = "created_date desc"
""")
    (project_dir / "zeeker.toml").write_text(toml_content)

    # Create resources directory
    resources_dir = project_dir / "resources"
    resources_dir.mkdir()
    (resources_dir / "__init__.py").write_text("")

    return project_dir


@pytest.fixture
def sample_resource_file(sample_project_dir):
    """Create a sample resource file."""
    resource_content = '''"""
Sample resource for testing.
"""

def fetch_data(existing_table):
    """Fetch sample data."""
    return [
        {"id": 1, "name": "Alice", "role": "admin"},
        {"id": 2, "name": "Bob", "role": "user"},
    ]
'''
    resource_file = sample_project_dir / "resources" / "users.py"
    resource_file.write_text(resource_content)
    return resource_file


@pytest.fixture
def sample_assets_dir(temp_dir):
    """Create a sample assets directory with templates and static files."""
    assets_dir = temp_dir / "assets"
    assets_dir.mkdir()

    # Create templates directory
    templates_dir = assets_dir / "templates"
    templates_dir.mkdir()

    # Create static directory
    static_dir = assets_dir / "static"
    static_dir.mkdir()

    # Create sample metadata.json
    metadata = {
        "title": "Test Database",
        "description": "Test database for validation",
        "extra_css_urls": ["/static/databases/test_db/custom.css"],
        "extra_js_urls": ["/static/databases/test_db/custom.js"],
        "databases": {"test_db": {"description": "Test database", "title": "Test DB"}},
    }
    (assets_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return assets_dir


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client for testing deployment."""
    mock_client = MagicMock()

    # Mock successful upload
    mock_client.upload_file.return_value = None

    # Mock list_objects_v2 for empty bucket
    mock_client.list_objects_v2.return_value = {"Contents": []}

    # Mock get_paginator
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{"Contents": []}]
    mock_client.get_paginator.return_value = mock_paginator

    return mock_client


@pytest.fixture
def s3_env_vars():
    """Set up S3 environment variables for testing."""
    env_vars = {
        "S3_BUCKET": "test-bucket",
        "AWS_ACCESS_KEY_ID": "test-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret",
        "S3_ENDPOINT_URL": "https://test.endpoint.com",
    }

    # Store original values
    original_values = {}
    for key in env_vars:
        original_values[key] = os.environ.get(key)
        os.environ[key] = env_vars[key]

    yield env_vars

    # Restore original values
    for key, original_value in original_values.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture
def sample_database_file(temp_dir):
    """Create a sample SQLite database file for testing."""
    import sqlite3

    db_path = temp_dir / "sample.db"
    conn = sqlite3.connect(str(db_path))

    # Create a simple table with data
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT, role TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Alice', 'admin')")
    conn.execute("INSERT INTO users VALUES (2, 'Bob', 'user')")
    conn.commit()
    conn.close()

    return db_path


# Markers for test categorization
pytest_markers = [
    "unit: Unit tests for individual components",
    "integration: Integration tests for component interactions",
    "cli: CLI interface tests",
    "slow: Tests that take longer to run",
]


def pytest_configure(config):
    """Configure pytest with custom markers."""
    for marker in pytest_markers:
        config.addinivalue_line("markers", marker)
