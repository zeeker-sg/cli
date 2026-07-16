"""Tests for build-lifecycle guarantees.

Covers:
- fetch_data() runs exactly once per build for fragments-enabled resources
  (no module reload / duplicate fetch in the fragments phase)
- resource module is imported exactly once per build
- fragments_on_skip opt-in flag runs the fragments phase on steady-state
  builds (fetch_data returned no new rows); flag absent preserves old behavior
- --setup-fts is idempotent (safe on incremental builds)
- sibling imports inside resources/ work without a manual sys.path shim
- the single-load/single-fetch guarantee also holds under --parallel (module
  state written by fetch_data reaches the fragments phase)
- main_data_context is a pre-transform snapshot (in-place transform_data
  cannot corrupt the fragments context)
- resources/ is never left on sys.path, and sibling helper modules do not
  leak across projects via sys.modules
- fetch_data still runs once per build when migrate_schema() changes the
  main table's row count between the schema check and the insert
"""

import sqlite3
import sys
import textwrap
from pathlib import Path

import pytest
import sqlite_utils

from zeeker.core.database.fts_processor import FTSProcessor
from zeeker.core.project import ZeekerProjectManager
from zeeker.core.types import ZeekerProject

pytestmark = pytest.mark.unit


def _make_project(tmp_path: Path, toml_body: str) -> ZeekerProjectManager:
    """Initialize a zeeker project in tmp_path and overwrite its zeeker.toml."""
    manager = ZeekerProjectManager(tmp_path)
    init_result = manager.init_project("test_project")
    assert init_result.is_valid
    (tmp_path / "zeeker.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "test_project"
            database = "test_project.db"

            """
        )
        + textwrap.dedent(toml_body)
    )
    return manager


def _read_count(path: Path) -> int:
    return int(path.read_text()) if path.exists() else 0


COUNTER_HELPERS = """
from pathlib import Path

def _bump(path):
    path = Path(path)
    n = int(path.read_text()) if path.exists() else 0
    path.write_text(str(n + 1))
"""


def test_fetch_data_called_once_per_fragments_build(tmp_path):
    """fetch_data() must run exactly once across a full fragments-enabled build."""
    fetch_counter = tmp_path / "fetch_count.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        fragments = true
        """,
    )

    resource_code = (
        COUNTER_HELPERS
        + f"""
FETCH_COUNTER = {str(fetch_counter)!r}

def fetch_data(existing_table):
    _bump(FETCH_COUNTER)
    return [
        {{"id": 1, "title": "Doc 1", "content": "alpha. beta."}},
        {{"id": 2, "title": "Doc 2", "content": "gamma. delta."}},
    ]

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    # Only produces fragments when context arrives from the main phase —
    # proving the builder threaded the raw fetch_data output through.
    if not main_data_context:
        return []
    return [
        {{"parent_id": doc["id"], "text": part.strip()}}
        for doc in main_data_context
        for part in doc["content"].split(".")
        if part.strip()
    ]
"""
    )
    (tmp_path / "resources" / "docs.py").write_text(resource_code)

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    assert _read_count(fetch_counter) == 1, "fetch_data must run exactly once per build"

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        main_count = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        frag_count = conn.execute("SELECT COUNT(*) FROM docs_fragments").fetchone()[0]
    finally:
        conn.close()
    assert main_count == 2
    assert frag_count == 4, "fragments must be built from the main-phase raw data"


def test_fetch_data_called_once_per_incremental_build(tmp_path):
    """On a rebuild against an existing DB (schema check + insert + fragments),
    fetch_data still runs exactly once per build."""
    fetch_counter = tmp_path / "fetch_count.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        fragments = true
        """,
    )

    resource_code = (
        COUNTER_HELPERS
        + f"""
FETCH_COUNTER = {str(fetch_counter)!r}

def fetch_data(existing_table):
    _bump(FETCH_COUNTER)
    data = [{{"id": 1, "title": "Doc 1", "content": "alpha. beta."}}]
    if existing_table:
        existing_ids = {{row["id"] for row in existing_table.rows}}
        data = [d for d in data if d["id"] not in existing_ids]
    return data

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    if not main_data_context:
        return []
    return [
        {{"parent_id": doc["id"], "text": part.strip()}}
        for doc in main_data_context
        for part in doc["content"].split(".")
        if part.strip()
    ]
"""
    )
    (tmp_path / "resources" / "docs.py").write_text(resource_code)

    first = manager.build_database()
    assert first.is_valid, first.errors
    assert _read_count(fetch_counter) == 1

    second = manager.build_database()
    assert second.is_valid, second.errors
    assert _read_count(fetch_counter) == 2, "each build must invoke fetch_data exactly once"


def test_resource_module_loaded_once_per_build(tmp_path):
    """The resource module must be imported exactly once per fragments build."""
    import_counter = tmp_path / "import_count.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        fragments = true
        """,
    )

    resource_code = (
        COUNTER_HELPERS
        + f"""
IMPORT_COUNTER = {str(import_counter)!r}
_bump(IMPORT_COUNTER)  # module-level side effect: counts imports

def fetch_data(existing_table):
    return [{{"id": 1, "title": "Doc", "content": "alpha. beta."}}]

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    if not main_data_context:
        return []
    return [{{"parent_id": doc["id"], "text": doc["content"]}} for doc in main_data_context]
"""
    )
    (tmp_path / "resources" / "docs.py").write_text(resource_code)

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    assert (
        _read_count(import_counter) == 1
    ), "resource module must be imported exactly once per build"


def test_fragments_on_skip_runs_fragments_on_empty_fetch(tmp_path):
    """fragments_on_skip = true runs the fragments phase with main_data_context=[]
    when fetch_data returns no new rows."""
    context_file = tmp_path / "context.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.enrich]
        description = "Enrichment-style resource"
        fragments = true
        fragments_on_skip = true
        """,
    )

    resource_code = f"""
from pathlib import Path

CONTEXT_FILE = {str(context_file)!r}

def fetch_data(existing_table):
    return []  # steady-state: nothing new discovered

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    Path(CONTEXT_FILE).write_text(repr(main_data_context))
    return [{{"id": 1, "parent_id": 1, "text": "enriched fragment"}}]
"""
    (tmp_path / "resources" / "enrich.py").write_text(resource_code)

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    assert context_file.exists(), "fragments phase must run on skip when opted in"
    assert context_file.read_text() == "[]", "main_data_context must be an empty list, not None"

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        frag_count = conn.execute("SELECT COUNT(*) FROM enrich_fragments").fetchone()[0]
    finally:
        conn.close()
    assert frag_count == 1

    report = build_result.report
    assert report is not None
    assert report.resources[0].status == "skipped"
    assert report.resources[0].fragments_records == 1


def test_fragments_not_run_on_empty_fetch_without_flag(tmp_path):
    """Regression guard: without fragments_on_skip, an empty fetch_data still
    skips the fragments phase entirely (existing downstream behavior)."""
    context_file = tmp_path / "context.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.enrich]
        description = "Enrichment-style resource"
        fragments = true
        """,
    )

    resource_code = f"""
from pathlib import Path

CONTEXT_FILE = {str(context_file)!r}

def fetch_data(existing_table):
    return []

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    Path(CONTEXT_FILE).write_text(repr(main_data_context))
    return [{{"id": 1, "parent_id": 1, "text": "should never be written"}}]
"""
    (tmp_path / "resources" / "enrich.py").write_text(resource_code)

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    assert not context_file.exists(), "fragments phase must NOT run on skip without the flag"

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    assert "enrich_fragments" not in tables


def test_fts_setup_twice_succeeds(tmp_path):
    """--setup-fts must be idempotent: enabling FTS twice on the same db succeeds
    and does not duplicate index entries."""
    project = ZeekerProject(
        name="p",
        database="p.db",
        resources={"docs": {"fts_fields": ["title", "body"]}},
        root_path=tmp_path,
    )
    db = sqlite_utils.Database(str(tmp_path / "p.db"))
    db["docs"].insert_all(
        [
            {"id": 1, "title": "hello world", "body": "first body"},
            {"id": 2, "title": "goodbye", "body": "second body"},
        ]
    )

    processor = FTSProcessor(project)

    first = processor.setup_fts_for_database(db)
    assert first.is_valid, first.errors

    second = processor.setup_fts_for_database(db)
    assert second.is_valid, second.errors

    rows = db.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'hello'").fetchall()
    assert len(rows) == 1, "repeated FTS setup must not duplicate index entries"

    # Triggers must still keep the index current after repeated setup.
    db["docs"].insert({"id": 3, "title": "hello again", "body": "third body"})
    rows = db.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'hello'").fetchall()
    assert len(rows) == 2


def test_fts_setup_twice_via_build(tmp_path):
    """End-to-end: two builds with setup_fts=True against the same database
    (the incremental --sync-from-s3 shape) must both succeed."""
    manager = _make_project(
        tmp_path,
        """\
        [resource.articles]
        description = "Articles"
        fts_fields = ["title"]
        """,
    )

    resource_code = """
def fetch_data(existing_table):
    data = [{"id": 1, "title": "searchable title"}]
    if existing_table:
        existing_ids = {row["id"] for row in existing_table.rows}
        data = [d for d in data if d["id"] not in existing_ids]
    return data
"""
    (tmp_path / "resources" / "articles.py").write_text(resource_code)

    first = manager.build_database(setup_fts=True)
    assert first.is_valid, first.errors

    second = manager.build_database(setup_fts=True)
    assert second.is_valid, second.errors

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        rows = conn.execute(
            "SELECT rowid FROM articles_fts WHERE articles_fts MATCH 'searchable'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1


def test_parallel_build_preserves_module_state_for_fragments(tmp_path):
    """Under --parallel (max_parallel > 1) the module must still be imported
    exactly once, and module-level state written by fetch_data must reach the
    fragments phase (regression: pre-warm used to load a second, virgin
    module instance)."""
    import_counter = tmp_path / "import_count.txt"
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        fragments = true

        [resource.other]
        description = "Second resource so the parallel pre-warm engages"
        """,
    )

    docs_code = (
        COUNTER_HELPERS
        + f"""
IMPORT_COUNTER = {str(import_counter)!r}
_bump(IMPORT_COUNTER)  # module-level side effect: counts imports

_PENDING = []  # module-level bridge: populated by fetch_data, read by fragments


def fetch_data(existing_table):
    rows = [{{"id": 1, "title": "Doc", "content": "alpha beta"}}]
    _PENDING.extend(rows)
    return rows


def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    # Deliberately ignores main_data_context: proves the SAME module
    # instance that ran fetch_data is handed to the fragments phase.
    return [{{"parent_id": r["id"], "text": r["content"]}} for r in _PENDING]
"""
    )
    (tmp_path / "resources" / "docs.py").write_text(docs_code)
    (tmp_path / "resources" / "other.py").write_text(
        """
def fetch_data(existing_table):
    return [{"id": 1, "value": "x"}]
"""
    )

    build_result = manager.build_database(max_parallel=2)
    assert build_result.is_valid, build_result.errors

    assert _read_count(import_counter) == 1, (
        "resource module must be imported exactly once per build, " "including under --parallel"
    )

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        frag_count = conn.execute("SELECT COUNT(*) FROM docs_fragments").fetchone()[0]
    finally:
        conn.close()
    assert frag_count == 1, "module-level state from fetch_data must reach the fragments phase"


def test_inplace_transform_does_not_corrupt_fragments_context(tmp_path):
    """main_data_context must be the PRE-transform data even when
    transform_data mutates rows in place (regression: raw_data used to alias
    the list handed to transform_data)."""
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        fragments = true
        """,
    )

    resource_code = """
def fetch_data(existing_table):
    return [{"id": 1, "title": "Doc", "content": "alpha. beta."}]


def transform_data(data):
    # Common in-place pattern: rename the heavy column before insert.
    for item in data:
        item["content_text"] = item.pop("content")
    return data


def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    if not main_data_context:
        return []
    # Reads the RAW (pre-transform) field, per the documented contract.
    return [
        {"parent_id": doc["id"], "text": part.strip()}
        for doc in main_data_context
        for part in doc["content"].split(".")
        if part.strip()
    ]
"""
    (tmp_path / "resources" / "docs.py").write_text(resource_code)

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(docs)").fetchall()}
        frag_count = conn.execute("SELECT COUNT(*) FROM docs_fragments").fetchone()[0]
    finally:
        conn.close()
    assert "content_text" in cols and "content" not in cols, "transform must apply to main table"
    assert frag_count == 2, "fragments must be built from the pre-transform data"


def test_resources_dir_not_left_on_sys_path(tmp_path):
    """The resources/ directory must not remain on sys.path after a build
    (regression: a permanent sys.path.insert(0, ...) let resources/*.py
    shadow stdlib/site-packages for the whole process)."""
    manager = _make_project(
        tmp_path,
        """\
        [resource.plain]
        description = "Plain resource"
        """,
    )
    (tmp_path / "resources" / "plain.py").write_text(
        """
def fetch_data(existing_table):
    return [{"id": 1}]
"""
    )

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    assert str(tmp_path / "resources") not in sys.path


def test_sibling_modules_do_not_leak_across_projects(tmp_path):
    """Two projects with a same-named helper module must each get their own
    helper (regression: sibling modules stayed in sys.modules under bare
    names, so the second project silently reused the first's helper)."""
    rows = {}
    for label in ("one", "two"):
        project_dir = tmp_path / f"project_{label}"
        project_dir.mkdir()
        manager = _make_project(
            project_dir,
            """\
            [resource.uses_helper]
            description = "Uses a same-named sibling helper"
            """,
        )
        (project_dir / "resources" / "leak_probe_helper_zq.py").write_text(
            f"""
VALUE = {label!r}
"""
        )
        (project_dir / "resources" / "uses_helper.py").write_text(
            """
import leak_probe_helper_zq


def fetch_data(existing_table):
    return [{"id": 1, "value": leak_probe_helper_zq.VALUE}]
"""
        )

        build_result = manager.build_database()
        assert build_result.is_valid, build_result.errors

        conn = sqlite3.connect(project_dir / "test_project.db")
        try:
            rows[label] = conn.execute("SELECT value FROM uses_helper").fetchone()[0]
        finally:
            conn.close()

    assert rows == {"one": "one", "two": "two"}
    assert "leak_probe_helper_zq" not in sys.modules


def test_fetch_runs_once_despite_migrate_schema_row_change(tmp_path):
    """fetch_data must run exactly once per build even when migrate_schema()
    changes the main table's row count between the schema-check fetch and the
    insert fetch (regression: the fetch cache was keyed on live row count)."""
    fetch_counter = tmp_path / "fetch_count.txt"
    phase_file = tmp_path / "phase2.flag"
    manager = _make_project(
        tmp_path,
        """\
        [resource.docs]
        description = "Docs"
        """,
    )

    resource_code = (
        COUNTER_HELPERS
        + f"""
FETCH_COUNTER = {str(fetch_counter)!r}
PHASE_FILE = {str(phase_file)!r}


def fetch_data(existing_table):
    _bump(FETCH_COUNTER)
    if Path(PHASE_FILE).exists():
        data = [{{"id": 3, "title": "c", "extra": 1.5}}]
    else:
        data = [{{"id": 1, "title": "a"}}, {{"id": 2, "title": "b"}}]
    if existing_table:
        existing_ids = {{row["id"] for row in existing_table.rows}}
        data = [d for d in data if d["id"] not in existing_ids]
    return data


def migrate_schema(existing_table, migration):
    # Migration that changes the table's row count AND adapts the schema —
    # the row-count change must not cause a second fetch_data invocation.
    existing_table.db.execute("DELETE FROM docs WHERE id = 2")
    existing_table.db.conn.commit()
    existing_table.add_column("extra", float)
    return True
"""
    )
    (tmp_path / "resources" / "docs.py").write_text(resource_code)

    first = manager.build_database()
    assert first.is_valid, first.errors
    assert _read_count(fetch_counter) == 1

    phase_file.write_text("go")

    second = manager.build_database()
    assert second.is_valid, second.errors
    assert _read_count(fetch_counter) == 2, (
        "each build must invoke fetch_data exactly once, even when "
        "migrate_schema changes the row count mid-build"
    )

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        ids = sorted(r[0] for r in conn.execute("SELECT id FROM docs").fetchall())
    finally:
        conn.close()
    assert ids == [1, 3]


def test_sibling_import_in_resources(tmp_path):
    """A resource module importing a sibling helper module in resources/ must
    load and build without a manual sys.path shim."""
    manager = _make_project(
        tmp_path,
        """\
        [resource.siblings]
        description = "Uses a sibling helper module"
        """,
    )

    (tmp_path / "resources" / "sibling_helper_lib.py").write_text(
        """
def make_rows():
    return [{"id": 1, "name": "from-helper"}]
"""
    )
    (tmp_path / "resources" / "siblings.py").write_text(
        """
import sibling_helper_lib


def fetch_data(existing_table):
    return sibling_helper_lib.make_rows()
"""
    )

    build_result = manager.build_database()
    assert build_result.is_valid, build_result.errors

    conn = sqlite3.connect(tmp_path / "test_project.db")
    try:
        rows = conn.execute("SELECT id, name FROM siblings").fetchall()
    finally:
        conn.close()
    assert rows == [(1, "from-helper")]
