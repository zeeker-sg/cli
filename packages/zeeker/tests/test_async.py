"""Tests for async resource functionality."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from zeeker.core.database import DatabaseBuilder
from zeeker.core.database.async_executor import AsyncExecutor
from zeeker.core.project import ZeekerProjectManager
from zeeker.core.types import ZeekerProject


class TestAsyncExecutor:
    """Test AsyncExecutor functionality."""

    def test_sync_function_execution(self):
        """Test that sync functions are executed correctly."""
        executor = AsyncExecutor()

        def sync_fetch_data(existing_table):
            return [{"id": 1, "name": "test"}]

        # Should not be detected as coroutine function
        assert not asyncio.iscoroutinefunction(sync_fetch_data)

        # Should call sync function directly
        result = executor.call_fetch_data(sync_fetch_data, None)
        assert result == [{"id": 1, "name": "test"}]

    def test_async_function_execution(self):
        """Test that async functions are executed correctly."""
        executor = AsyncExecutor()

        async def async_fetch_data(existing_table):
            await asyncio.sleep(0.001)  # Minimal async operation
            return [{"id": 1, "name": "async_test"}]

        # Should be detected as coroutine function
        assert asyncio.iscoroutinefunction(async_fetch_data)

        # Should execute async function and return result
        result = executor.call_fetch_data(async_fetch_data, None)
        assert result == [{"id": 1, "name": "async_test"}]

    def test_async_fragments_function_execution(self):
        """Test async fragments function execution."""
        executor = AsyncExecutor()

        async def async_fetch_fragments_data(existing_fragments_table, main_data_context=None):
            await asyncio.sleep(0.001)
            if main_data_context:
                return [{"parent_id": 1, "text": "fragment from context"}]
            return [{"parent_id": 1, "text": "fragment"}]

        # Test without context
        result = executor.call_fetch_fragments_data(async_fetch_fragments_data, None)
        assert result == [{"parent_id": 1, "text": "fragment"}]

        # Test with context
        context = [{"id": 1, "content": "test content"}]
        result = executor.call_fetch_fragments_data(async_fetch_fragments_data, None, context)
        assert result == [{"parent_id": 1, "text": "fragment from context"}]


class TestAsyncTemplateGeneration:
    """Test async template generation."""

    def test_add_async_resource(self, tmp_path):
        """Test adding async resource generates correct template."""
        manager = ZeekerProjectManager(tmp_path)

        # Create basic project structure
        (tmp_path / "zeeker.toml").write_text("""
[project]
name = "test_project"
database = "test.db"

[resources]
""")
        (tmp_path / "resources").mkdir()

        # Add async resource
        result = manager.add_resource("async_test", "Async test resource", is_async=True)

        assert result.is_valid
        assert len(result.errors) == 0

        # Check that async template was generated
        resource_file = tmp_path / "resources" / "async_test.py"
        assert resource_file.exists()

        content = resource_file.read_text()
        assert "async def fetch_data" in content
        assert "import asyncio" in content
        assert "import aiohttp" in content

    def test_add_async_fragments_resource(self, tmp_path):
        """Test adding async fragments resource generates correct template."""
        manager = ZeekerProjectManager(tmp_path)

        # Create basic project structure
        (tmp_path / "zeeker.toml").write_text("""
[project]
name = "test_project"
database = "test.db"

[resources]
""")
        (tmp_path / "resources").mkdir()

        # Add async fragments resource
        result = manager.add_resource(
            "async_fragments_test", "Async fragments test resource", fragments=True, is_async=True
        )

        assert result.is_valid
        assert len(result.errors) == 0

        # Check that async fragments template was generated
        resource_file = tmp_path / "resources" / "async_fragments_test.py"
        assert resource_file.exists()

        content = resource_file.read_text()
        assert "async def fetch_data" in content
        assert "async def fetch_fragments_data" in content
        assert "import asyncio" in content
        assert "import aiohttp" in content


class TestAsyncDatabaseBuilding:
    """Test building databases with async resources."""

    def test_build_with_async_resource(self, tmp_path):
        """Test building database with async resource."""
        # Create project structure
        (tmp_path / "zeeker.toml").write_text("""
[project]
name = "test_project"
database = "test.db"

[resources.async_users]
description = "Async users resource"
""")

        resources_dir = tmp_path / "resources"
        resources_dir.mkdir()
        (resources_dir / "__init__.py").write_text("")

        # Create async resource file
        async_resource_content = '''
import asyncio
from sqlite_utils.db import Table
from typing import Optional, List, Dict, Any

async def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """Async fetch data function."""
    await asyncio.sleep(0.001)  # Minimal async operation
    return [
        {"id": 1, "name": "Alice", "age": 30},
        {"id": 2, "name": "Bob", "age": 25}
    ]
'''
        (resources_dir / "async_users.py").write_text(async_resource_content)

        # Build database
        project = ZeekerProject(
            name="test_project",
            database="test.db",
            resources={"async_users": {"description": "Async users resource"}},
        )

        builder = DatabaseBuilder(tmp_path, project)
        result = builder.build_database()

        assert result.is_valid
        assert len(result.errors) == 0

        # Check that database was created
        db_path = tmp_path / "test.db"
        assert db_path.exists()

        # Verify data was inserted
        import sqlite_utils

        db = sqlite_utils.Database(db_path)
        assert "async_users" in db.table_names()

        users_table = db["async_users"]
        rows = list(users_table.rows)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[1]["name"] == "Bob"

    def test_build_with_async_fragments_resource(self, tmp_path):
        """Test building database with async fragments resource."""
        # Create project structure
        (tmp_path / "zeeker.toml").write_text("""
[project]
name = "test_project"
database = "test.db"

[resources.async_docs]
description = "Async documents resource"
fragments = true
""")

        resources_dir = tmp_path / "resources"
        resources_dir.mkdir()
        (resources_dir / "__init__.py").write_text("")

        # Create async fragments resource file
        async_fragments_content = '''
import asyncio
from sqlite_utils.db import Table
from typing import Optional, List, Dict, Any

async def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """Async fetch documents."""
    await asyncio.sleep(0.001)
    return [
        {"id": 1, "title": "Doc 1", "content": "This is document one content."},
        {"id": 2, "title": "Doc 2", "content": "This is document two content."}
    ]

async def fetch_fragments_data(existing_fragments_table: Optional[Table], main_data_context: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Async fetch fragments."""
    await asyncio.sleep(0.001)

    if main_data_context:
        fragments = []
        for doc in main_data_context:
            doc_id = doc.get("id")
            content = doc.get("content", "")

            # Simple splitting for test
            words = content.split()
            for i, word in enumerate(words):
                fragments.append({
                    "parent_id": doc_id,
                    "fragment_num": i,
                    "text": word
                })
        return fragments

    return []
'''
        (resources_dir / "async_docs.py").write_text(async_fragments_content)

        # Build database
        project = ZeekerProject(
            name="test_project",
            database="test.db",
            resources={
                "async_docs": {"description": "Async documents resource", "fragments": True}
            },
        )

        builder = DatabaseBuilder(tmp_path, project)
        result = builder.build_database()

        assert result.is_valid
        assert len(result.errors) == 0

        # Check that database was created
        db_path = tmp_path / "test.db"
        assert db_path.exists()

        # Verify both tables were created
        import sqlite_utils

        db = sqlite_utils.Database(db_path)
        assert "async_docs" in db.table_names()
        assert "async_docs_fragments" in db.table_names()

        # Verify main table data
        docs_table = db["async_docs"]
        docs = list(docs_table.rows)
        assert len(docs) == 2
        assert docs[0]["title"] == "Doc 1"

        # Verify fragments table data
        fragments_table = db["async_docs_fragments"]
        fragments = list(fragments_table.rows)
        assert len(fragments) > 0
        assert all(frag["parent_id"] in [1, 2] for frag in fragments)


@pytest.fixture
def tmp_path():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
