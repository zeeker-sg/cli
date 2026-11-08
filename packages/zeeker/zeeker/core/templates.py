"""
Template generation for Zeeker resources.

This module handles generating Python resource files from Jinja2 templates.
Extracted from project.py to follow separation of concerns.
"""

from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader

    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


class ResourceTemplateGenerator:
    """Generates Python resource files from Jinja2 templates."""

    def __init__(self):
        """Initialize the template generator."""
        self.templates_dir = Path(__file__).parent.parent / "templates"
        if HAS_JINJA2 and self.templates_dir.exists():
            self.env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                trim_blocks=True,
                lstrip_blocks=True,
            )
        else:
            self.env = None

    def generate_resource_template(
        self, resource_name: str, fragments: bool = False, is_async: bool = False
    ) -> str:
        """Generate a Python template for a resource.

        Args:
            resource_name: Name of the resource
            fragments: Whether to generate fragments-enabled template
            is_async: Whether to generate async-enabled template

        Returns:
            Generated Python code as string
        """
        if self.env and HAS_JINJA2:
            return self._generate_jinja2_template(resource_name, fragments, is_async)
        else:
            # Fallback to string-based templates if Jinja2 not available
            return self._generate_fallback_template(resource_name, fragments, is_async)

    def _generate_jinja2_template(self, resource_name: str, fragments: bool, is_async: bool) -> str:
        """Generate template using Jinja2."""
        try:
            template = self.env.get_template("resource_template.py.j2")
            return template.render(
                resource_name=resource_name,
                fragments=fragments,
                is_async=is_async,
            )
        except Exception:
            # Fall back to string-based templates if Jinja2 fails
            return self._generate_fallback_template(resource_name, fragments, is_async)

    def _generate_fallback_template(
        self, resource_name: str, fragments: bool = False, is_async: bool = False
    ) -> str:
        """Generate template using string formatting (fallback).

        Args:
            resource_name: Name of the resource
            fragments: Whether to generate fragments-enabled template
            is_async: Whether to generate async-enabled template

        Returns:
            Generated Python code as string
        """
        title = resource_name.replace("_", " ").title()
        fragments_table = f"{resource_name}_fragments"

        # Build module docstring
        if fragments:
            async_suffix = " (async version)" if is_async else ""
            docstring = f'''"""
{title} resource with fragments support for large documents{async_suffix}.

This module implements TWO tables:
1. '{resource_name}' - Main table (schema determined by your fetch_data function)
2. '{fragments_table}' - Fragments table (schema determined by your fetch_fragments_data function)

IMPORTANT: You define both table schemas through your returned data structure.
Zeeker does not enforce any specific field names or relationships.

The database is built using sqlite-utils with automatic schema detection.
"""'''
        else:
            async_suffix = " (async version)" if is_async else ""
            docstring = f'''"""
{title} resource for fetching and processing data{async_suffix}.

This module should implement {"an async " if is_async else "a "}fetch_data() function that returns
a list of dictionaries to be inserted into the '{resource_name}' table.

The database is built using sqlite-utils, which provides:
\u2022 Automatic table creation from your data structure
\u2022 Type inference (integers \u2192 INTEGER, floats \u2192 REAL, strings \u2192 TEXT)
\u2022 JSON support for complex data (lists, dicts stored as JSON)
\u2022 Safe data insertion without SQL injection risks
"""'''

        # Build imports
        if is_async:
            imports = """import asyncio
import aiohttp
from sqlite_utils.db import Table, NotFoundError
from typing import Optional, List, Dict, Any, Awaitable"""
        else:
            imports = """from sqlite_utils.db import Table, NotFoundError
from typing import Optional, List, Dict, Any"""

        # Build fetch_data function
        async_prefix = "async " if is_async else ""
        fetch_data = self._build_fetch_data(resource_name, fragments, is_async)

        # Build fragments functions
        fragments_funcs = ""
        if fragments:
            fragments_funcs = self._build_fragments_functions(resource_name, is_async)

        # Build transform_data
        transform_data = self._build_transform_data(fragments, is_async)

        # Build transform_fragments_data
        transform_fragments = ""
        if fragments:
            transform_fragments = self._build_transform_fragments_data(is_async)

        # Build helper comments/functions
        helpers = self._build_helpers(fragments, is_async)

        # Assemble parts
        parts = [docstring, imports]
        if not fragments:
            parts.append("""
# Optional: Import common utilities from zeeker-common package
# Install with: uv add zeeker-common
# from zeeker_common import get_hash_id, get_jina_reader_content, async_retry""")
        parts.append(fetch_data)
        if fragments_funcs:
            parts.append(fragments_funcs)
        parts.append(transform_data)
        if transform_fragments:
            parts.append(transform_fragments)
        parts.append(helpers)

        return "\n".join(parts)

    def _build_fetch_data(self, resource_name: str, fragments: bool, is_async: bool) -> str:
        """Build the fetch_data function string."""
        async_prefix = "async " if is_async else ""

        if fragments and is_async:
            return f'''
{async_prefix}def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """
    Async fetch data for the {resource_name} table.

    Args:
        existing_table: sqlite-utils Table object if table exists, None for new table
                       Use this to check for existing data and avoid duplicates

    Returns:
        List[Dict[str, Any]]: Records for the main table

    IMPORTANT - Schema Considerations:
    Your FIRST fetch_data() call determines the column types permanently!
    sqlite-utils infers types from the first ~100 records and locks them in.

    You have complete freedom to define your schema. Common patterns:
    - Simple: {{"id": 1, "title": "Doc 1", "content": "..."}}
    - Metadata focused: {{"id": 1, "title": "Doc 1", "source": "...", "date": "..."}}
    - Complex: {{"id": 1, "title": "Doc 1", "metadata": {{"tags": ["tag1"]}}, "status": "active"}}

    Accessing metadata for incremental updates:
        if existing_table:
            db = existing_table.db
            if "_zeeker_updates" in db.table_names():
                updates_table = db["_zeeker_updates"]
                try:
                    metadata = updates_table.get(existing_table.name)
                    last_updated = metadata["last_updated"]  # ISO datetime string
                    record_count = metadata["record_count"]  # Current row count
                    print(f"Last updated: {{last_updated}}, Records: {{record_count}}")
                except NotFoundError:
                    print("No metadata found - first run")
    """
    # TODO: Implement your async data fetching logic
    # This is just an example - replace with your actual schema and data

    # Example async document fetching
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com/documents") as response:
            if response.status == 200:
                documents = await response.json()
                return [
                    {{
                        "id": doc["id"],  # Required: some kind of identifier
                        "title": doc["title"],  # Your field names and types
                        "content": doc["content"],  # You decide what goes in main vs fragments
                        "source": doc.get("source", "api"),
                        "created_date": doc.get("created", "2024-01-01"),
                        # Add any other fields your project needs
                    }}
                    for doc in documents
                ]

    # Fallback example data
    return [
        {{
            "id": 1,  # Required: some kind of identifier
            "title": "Example Document",  # Your field names and types
            "content": "Document content...",  # You decide what goes in main vs fragments
            # Add any other fields your project needs
        }},
        # Add more records...
    ]'''
        elif fragments and not is_async:
            return f'''
{async_prefix}def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """
    Fetch data for the {resource_name} table.

    Args:
        existing_table: sqlite-utils Table object if table exists, None for new table
                       Use this to check for existing data and avoid duplicates

    Returns:
        List[Dict[str, Any]]: Records for the main table

    IMPORTANT - Schema Considerations:
    Your FIRST fetch_data() call determines the column types permanently!
    sqlite-utils infers types from the first ~100 records and locks them in.

    You have complete freedom to define your schema. Common patterns:
    - Simple: {{"id": 1, "title": "Doc 1", "content": "..."}}
    - Metadata focused: {{"id": 1, "title": "Doc 1", "source": "...", "date": "..."}}
    - Complex: {{"id": 1, "title": "Doc 1", "metadata": {{"tags": ["tag1"]}}, "status": "active"}}

    CRITICAL - Duplicate Handling:
    Your function MUST NOT return records with IDs that already exist in the database.
    sqlite-utils will throw a UNIQUE constraint error if you do!

    Example usage:
        if existing_table:
            # REQUIRED: Get existing IDs to avoid duplicates
            existing_ids = {{row["id"] for row in existing_table.rows}}
            print(f"Found {{len(existing_ids)}} existing records")

            # Fetch fresh data and filter duplicates
            fresh_data = get_documents_from_source()
            new_records = [
                record for record in fresh_data
                if record["id"] not in existing_ids
            ]
            print(f"Adding {{len(new_records)}} new records")

            # Optional: Access metadata for incremental updates
            db = existing_table.db
            if "_zeeker_updates" in db.table_names():
                updates_table = db["_zeeker_updates"]
                try:
                    metadata = updates_table.get(existing_table.name)
                    last_updated = metadata["last_updated"]  # ISO datetime string
                    record_count = metadata["record_count"]  # Current row count
                    print(f"Last updated: {{last_updated}}, Records: {{record_count}}")
                except NotFoundError:
                    print("No metadata found - first run")

            return new_records
        else:
            print("Creating new table")
            return get_documents_from_source()
    """
    # TODO: Implement your data fetching logic
    # This is just an example - replace with your actual schema and data
    return [
        {{
            "id": 1,  # Required: some kind of identifier
            "title": "Example Document",  # Your field names and types
            "content": "Document content...",  # You decide what goes in main vs fragments
            # Add any other fields your project needs
        }},
        # Add more records...
    ]'''
        elif is_async and not fragments:
            return f'''
{async_prefix}def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """
    Async fetch data for the {resource_name} table.

    Args:
        existing_table: sqlite-utils Table object if table exists, None for new table
                       Use this to check for existing data and avoid duplicates

    Returns:
        List[Dict[str, Any]]: List of records to insert into database

    IMPORTANT - Schema Considerations:
    Your FIRST fetch_data() call determines the column types permanently!
    sqlite-utils infers types from the first ~100 records and locks them in.
    Later runs cannot change existing column types, only add new columns.

    Python Type \u2192 SQLite Column Type:
    \u2022 int          \u2192 INTEGER
    \u2022 float        \u2192 REAL
    \u2022 str          \u2192 TEXT
    \u2022 bool         \u2192 INTEGER (stored as 0/1)
    \u2022 dict/list    \u2192 TEXT (stored as JSON)
    \u2022 None values  \u2192 Can cause type inference issues

    Best Practices:
    1. Make sure your first batch has correct Python types
    2. Use consistent data types across all records
    3. Avoid None/null values in key columns on first run
    4. Use float (not int) for numbers that might have decimals later

    CRITICAL - Duplicate Handling:
    Your function MUST NOT return records with IDs that already exist in the database.
    sqlite-utils will throw a UNIQUE constraint error if you do!

    Example usage:
        if existing_table:
            # REQUIRED: Get existing IDs to avoid duplicates
            existing_ids = {{row["id"] for row in existing_table.rows}}
            print(f"Found {{len(existing_ids)}} existing records")

            # Fetch fresh data from your async source
            fresh_data = await fetch_from_api()  # Your async data source

            # CRITICAL: Filter out existing records
            new_records = [
                record for record in fresh_data
                if record["id"] not in existing_ids
            ]
            print(f"Adding {{len(new_records)}} new records, skipping {{len(fresh_data) - len(new_records)}} duplicates")

            # Optional: Access metadata for time-based incremental updates
            db = existing_table.db
            if "_zeeker_updates" in db.table_names():
                updates_table = db["_zeeker_updates"]
                try:
                    metadata = updates_table.get(existing_table.name)
                    last_updated = metadata["last_updated"]  # ISO datetime string
                    print(f"Last updated: {{last_updated}}")
                    # Use last_updated for incremental fetching
                except NotFoundError:
                    print("No metadata found - first run")

            return new_records
        else:
            # Fresh table - CRITICAL: Set schema correctly with first batch!
            print("Creating new table")
            return await fetch_from_api()  # Get all data for first run
    """
    # TODO: Implement your async data fetching logic here
    # This could be:
    # - Async API calls (aiohttp.get, httpx.get, etc.)
    # - Async file reading (aiofiles.open, etc.)
    # - Async database queries (asyncpg, aiomysql, etc.)
    # - Async web scraping (playwright, selenium, etc.)
    # - Any other async data source

    # Example async API call using aiohttp with duplicate handling
    async with aiohttp.ClientSession() as session:
        # Replace with your actual API endpoint
        async with session.get("https://api.example.com/data") as response:
            if response.status == 200:
                api_data = await response.json()
                # Process API data into standard format
                raw_data = [
                    # Example data showing proper types for schema inference:
                    {{
                        "id": 1,                           # int \u2192 INTEGER (good for primary keys)
                        "title": "Example Title",          # str \u2192 TEXT
                        "score": 85.5,                     # float \u2192 REAL (use float even for whole numbers!)
                        "view_count": 100,                 # int \u2192 INTEGER
                        "is_published": True,              # bool \u2192 INTEGER (0/1)
                        "created_date": "2024-01-15",      # str \u2192 TEXT (ISO date format recommended)
                        "tags": ["news", "technology"],    # list \u2192 TEXT (stored as JSON)
                        "metadata": {{"priority": "high"}},  # dict \u2192 TEXT (stored as JSON)
                    }},
                    # Add more example records with same structure...
                ]

                # Handle duplicates properly
                if existing_table:
                    existing_ids = {{row["id"] for row in existing_table.rows}}
                    raw_data = [record for record in raw_data if record["id"] not in existing_ids]
                    print(f"{resource_name}: Adding {{len(raw_data)}} new records")

                return raw_data
            else:
                print(f"API request failed with status {{response.status}}")
                return []

    # Fallback should never be reached due to above return statements
    return []'''
        else:
            # Standard sync, no fragments
            return f'''
{async_prefix}def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """
    Fetch data for the {resource_name} table.

    Args:
        existing_table: sqlite-utils Table object if table exists, None for new table
                       Use this to check for existing data and avoid duplicates

    Returns:
        List[Dict[str, Any]]: List of records to insert into database

    IMPORTANT - Schema Considerations:
    Your FIRST fetch_data() call determines the column types permanently!
    sqlite-utils infers types from the first ~100 records and locks them in.
    Later runs cannot change existing column types, only add new columns.

    Python Type \u2192 SQLite Column Type:
    \u2022 int          \u2192 INTEGER
    \u2022 float        \u2192 REAL
    \u2022 str          \u2192 TEXT
    \u2022 bool         \u2192 INTEGER (stored as 0/1)
    \u2022 dict/list    \u2192 TEXT (stored as JSON)
    \u2022 None values  \u2192 Can cause type inference issues

    Best Practices:
    1. Make sure your first batch has correct Python types
    2. Use consistent data types across all records
    3. Avoid None/null values in key columns on first run
    4. Use float (not int) for numbers that might have decimals later

    CRITICAL - Duplicate Handling:
    Your function MUST NOT return records with IDs that already exist in the database.
    sqlite-utils will throw a UNIQUE constraint error if you do!

    Example usage:
        if existing_table:
            # REQUIRED: Get existing IDs to avoid duplicates
            existing_ids = {{row["id"] for row in existing_table.rows}}
            print(f"Found {{len(existing_ids)}} existing records")

            # Fetch fresh data from your source
            fresh_data = fetch_from_api()  # Your data source

            # CRITICAL: Filter out existing records
            new_records = [
                record for record in fresh_data
                if record["id"] not in existing_ids
            ]
            print(f"Adding {{len(new_records)}} new records, skipping {{len(fresh_data) - len(new_records)}} duplicates")

            # Optional: Access metadata for time-based incremental updates
            db = existing_table.db
            if "_zeeker_updates" in db.table_names():
                updates_table = db["_zeeker_updates"]
                try:
                    metadata = updates_table.get(existing_table.name)
                    last_updated = metadata["last_updated"]  # ISO datetime string
                    print(f"Last updated: {{last_updated}}")
                    # Use last_updated for incremental fetching
                except NotFoundError:
                    print("No metadata found - first run")

            return new_records
        else:
            # Fresh table - CRITICAL: Set schema correctly with first batch!
            print("Creating new table")
            return fetch_from_api()  # Get all data for first run
    """
    # TODO: Implement your data fetching logic here
    # This could be:
    # - API calls (requests.get, etc.)
    # - File reading (CSV, JSON, XML, etc.)
    # - Database queries (from other sources)
    # - Web scraping (BeautifulSoup, Scrapy, etc.)
    # - Any other data source

    # Example implementation with proper duplicate handling:
    raw_data = [
        # Example data showing proper types for schema inference:
        {{
            "id": 1,                           # int \u2192 INTEGER (good for primary keys)
            "title": "Example Title",          # str \u2192 TEXT
            "score": 85.5,                     # float \u2192 REAL (use float even for whole numbers!)
            "view_count": 100,                 # int \u2192 INTEGER
            "is_published": True,              # bool \u2192 INTEGER (0/1)
            "created_date": "2024-01-15",      # str \u2192 TEXT (ISO date format recommended)
            "tags": ["news", "technology"],    # list \u2192 TEXT (stored as JSON)
            "metadata": {{"priority": "high"}},  # dict \u2192 TEXT (stored as JSON)
        }},
        # Add more example records with same structure...
    ]

    # Handle duplicates properly
    if existing_table:
        existing_ids = {{row["id"] for row in existing_table.rows}}
        raw_data = [record for record in raw_data if record["id"] not in existing_ids]
        print(f"{resource_name}: Adding {{len(raw_data)}} new records")

    return raw_data'''

    def _build_fragments_functions(self, resource_name: str, is_async: bool) -> str:
        """Build the fetch_fragments_data function string."""
        async_prefix = "async " if is_async else ""
        fragments_table = f"{resource_name}_fragments"

        if is_async:
            return f'''

{async_prefix}def fetch_fragments_data(existing_fragments_table: Optional[Table], main_data_context: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Async fetch fragments data for the {fragments_table} table.

    This is called automatically after fetch_data().

    Args:
        existing_fragments_table: sqlite-utils Table object if exists, None for new table
                                 Use this to check existing fragments and avoid duplicates
        main_data_context: Raw data from fetch_data() to avoid duplicate API calls (optional)
                          Contains the same data returned by your fetch_data() function

    Returns:
        List[Dict[str, Any]]: Fragment records with YOUR chosen schema

    IMPORTANT: You have complete freedom to define the fragments schema.
    Common patterns include:

    1. Simple text chunks:
       {{"parent_id": 1, "text": "fragment content"}}

    2. Positional fragments:
       {{"doc_id": 1, "position": 0, "content": "...", "length": 500}}

    3. Semantic fragments:
       {{"document_id": 1, "section_type": "intro", "text": "...", "page": 1}}

    4. Custom fragments:
       {{"source_id": 1, "fragment_data": "...", "metadata": {{"type": "citation"}}}}

    The only requirement: some way to link fragments back to main records.
    """
    # TODO: Implement your async fragments logic
    # This is just an example - replace with your actual implementation

    # OPTION 1: Use main_data_context to avoid duplicate API calls
    if main_data_context:
        fragments = []
        for main_record in main_data_context:
            # Use data already fetched in fetch_data() - no duplicate API calls!
            doc_content = main_record.get("content", "")  # Or however you store content
            doc_id = main_record.get("id")  # Or your identifier field

            # Async text processing (e.g., AI-based chunking)
            chunks = await async_split_content(doc_content)

            for i, chunk in enumerate(chunks):
                if chunk.strip():
                    fragments.append(
                        {{
                            "parent_id": doc_id,  # Link to main table record
                            "fragment_num": i,  # Fragment ordering
                            "text": chunk.strip(),  # Fragment content
                            "char_count": len(chunk),  # Your metadata
                        }}
                    )
        return fragments

    # OPTION 2: Fallback to independent async data fetch (for backward compatibility)
    # This runs when main_data_context is None (e.g., testing, old resources)
    example_text = \"\"\"
    This is an example document that will be split into fragments.
    You can implement any splitting logic you need.

    Maybe you want sentence-based fragments, paragraph-based,
    or even semantic chunks based on document structure.

    The choice is entirely yours based on your project needs.
    \"\"\"

    # Your async splitting logic goes here
    fragments = []
    chunks = await async_split_content(example_text)

    for i, chunk in enumerate(chunks):
        if chunk.strip():
            fragments.append(
                {{
                    "parent_id": 1,  # Link to main table (your choice of field name)
                    "sequence": i,  # Your choice of ordering
                    "text": chunk.strip(),  # Your choice of content field name
                    # Add any other fields your fragments need
                }}
            )

    return fragments'''
        else:
            return f'''

{async_prefix}def fetch_fragments_data(existing_fragments_table: Optional[Table], main_data_context: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Fetch fragments data for the {fragments_table} table.

    This is called automatically after fetch_data().

    Args:
        existing_fragments_table: sqlite-utils Table object if exists, None for new table
                                 Use this to check existing fragments and avoid duplicates
        main_data_context: Raw data from fetch_data() to avoid duplicate API calls (optional)
                          Contains the same data returned by your fetch_data() function

    Returns:
        List[Dict[str, Any]]: Fragment records with YOUR chosen schema

    IMPORTANT: You have complete freedom to define the fragments schema.
    Common patterns include:

    1. Simple text chunks:
       {{"parent_id": 1, "text": "fragment content"}}

    2. Positional fragments:
       {{"doc_id": 1, "position": 0, "content": "...", "length": 500}}

    3. Semantic fragments:
       {{"document_id": 1, "section_type": "intro", "text": "...", "page": 1}}

    4. Custom fragments:
       {{"source_id": 1, "fragment_data": "...", "metadata": {{"type": "citation"}}}}

    The only requirement: some way to link fragments back to main records.
    """
    # TODO: Implement your fragments logic
    # This is just an example - replace with your actual implementation

    # OPTION 1: Use main_data_context to avoid duplicate API calls
    if main_data_context:
        fragments = []
        for main_record in main_data_context:
            # Use data already fetched in fetch_data() - no duplicate API calls!
            doc_content = main_record.get("content", "")  # Or however you store content
            doc_id = main_record.get("id")  # Or your identifier field

            # Split the content into fragments
            chunks = doc_content.split("\\n\\n")  # Or your preferred splitting logic

            for i, chunk in enumerate(chunks):
                if chunk.strip():
                    fragments.append(
                        {{
                            "parent_id": doc_id,  # Link to main table record
                            "fragment_num": i,  # Fragment ordering
                            "text": chunk.strip(),  # Fragment content
                            "char_count": len(chunk),  # Your metadata
                        }}
                    )
        return fragments

    # OPTION 2: Fallback to independent data fetch (for backward compatibility)
    # This runs when main_data_context is None (e.g., testing, old resources)
    example_text = \"\"\"
    This is an example document that will be split into fragments.
    You can implement any splitting logic you need.

    Maybe you want sentence-based fragments, paragraph-based,
    or even semantic chunks based on document structure.

    The choice is entirely yours based on your project needs.
    \"\"\"

    # Your splitting logic goes here
    fragments = []
    sentences = example_text.split(".")
    for i, sentence in enumerate(sentences):
        if sentence.strip():
            fragments.append(
                {{
                    "parent_id": 1,  # Link to main table (your choice of field name)
                    "sequence": i,  # Your choice of ordering
                    "text": sentence.strip(),  # Your choice of content field name
                    # Add any other fields your fragments need
                }}
            )

    return fragments'''

    def _build_transform_data(self, fragments: bool, is_async: bool) -> str:
        """Build the transform_data function string."""
        async_prefix = "async " if is_async else ""
        desc = "main table" if fragments else "/clean the raw"

        if fragments:
            body = f'''

{async_prefix}def transform_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optional: Transform main table data before database insertion.

    Args:
        raw_data: The data returned from fetch_data()

    Returns:
        List[Dict[str, Any]]: Transformed data
    """
    # TODO: Add any {"async " if is_async else ""}data transformation logic here
{"    await asyncio.sleep(0)  # Placeholder for async operations" if is_async else ""}
    return raw_data'''
        else:
            body = f'''

{async_prefix}def transform_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optional: Transform/clean the raw data before database insertion.

    Args:
        raw_data: The data returned from fetch_data()

    Returns:
        List[Dict[str, Any]]: Transformed data

    Examples:
        # Clean strings
        for item in raw_data:
            item['name'] = item['name'].strip().title()

        # Parse dates
        for item in raw_data:
            item['created_date'] = datetime.fromisoformat(item['date_string'])

        # Handle complex data (sqlite-utils stores as JSON)
        for item in raw_data:
            item['metadata'] = {{"tags": ["news", "tech"], "priority": 1}}
    """
    # TODO: Add any {"async " if is_async else ""}data transformation logic here
{"    await asyncio.sleep(0)  # Placeholder for async operations" if is_async else ""}
    return raw_data'''
        return body

    def _build_transform_fragments_data(self, is_async: bool) -> str:
        """Build the transform_fragments_data function string."""
        async_prefix = "async " if is_async else ""
        return f'''

{async_prefix}def transform_fragments_data(raw_fragments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optional: Transform fragment data before database insertion.

    Args:
        raw_fragments: The data returned from fetch_fragments_data()

    Returns:
        List[Dict[str, Any]]: Transformed fragment data
    """
    # TODO: Add any {"async " if is_async else ""}fragment processing logic here
{"    await asyncio.sleep(0)  # Placeholder for async operations" if is_async else ""}
    return raw_fragments'''

    def _build_helpers(self, fragments: bool, is_async: bool) -> str:
        """Build helper comments and functions string."""
        if is_async and not fragments:
            return '''

# TODO: Add any helper functions your project needs
# Examples:
# - Async API client functions
# - Async data parsing utilities
# - Async validation functions
# - Custom async data transformation functions

async def fetch_from_api():
    """Example async helper function."""
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com/data") as response:
            return await response.json()

async def fetch_initial_data():
    """Example async helper for initial data fetch."""
    # Your initial data fetching logic here
    await asyncio.sleep(0.1)  # Simulate async operation
    return [
        {"id": 1, "name": "Initial Record", "created": "2024-01-01"},
        {"id": 2, "name": "Another Record", "created": "2024-01-02"},
    ]'''
        elif is_async and fragments:
            return """

# TODO: Add any async helper functions your project needs
# Examples:
# - Async document parsing functions
# - Async text splitting utilities
# - Async data validation functions
# - Async API client functions

async def async_split_content(content: str) -> List[str]:
    \"\"\"Example async text splitting function.\"\"\"
    # Simulate async processing (e.g., AI-based chunking)
    await asyncio.sleep(0.1)

    # Simple paragraph-based splitting for example
    paragraphs = content.split('\\n\\n')
    return [p.strip() for p in paragraphs if p.strip()]

async def async_fetch_documents():
    \"\"\"Example async document fetching.\"\"\"
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com/documents") as response:
            return await response.json()

async def async_process_document(doc_content: str) -> List[str]:
    \"\"\"Example async document processing.\"\"\"
    # Could call AI services, external APIs, etc.
    await asyncio.sleep(0.1)
    return doc_content.split('\\n\\n')"""
        elif not is_async and not fragments:
            return """

# TODO: Add any helper functions your project needs
# Examples:
# - API client functions
# - Data parsing utilities
# - Validation functions
# - Custom data transformation functions"""
        else:
            return """

# TODO: Add any helper functions your project needs
# Examples:
# - Document parsing functions
# - Text splitting utilities
# - Data validation functions
# - API client functions"""
