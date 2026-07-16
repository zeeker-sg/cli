# CLAUDE.md

## Commands
- `uv run pytest [-m unit|integration|cli]` `uv run black .` 
- `uv run zeeker init|add|build|deploy` `--fragments --async --sync-from-s3 --force-schema-reset`
- `uv run zeeker build [resource1] [resource2]` (selective building)
- `uv run zeeker assets generate|validate|deploy|list`
- `uv run zeeker metadata generate|show` `--all --dry-run --force --project --resource`

## Architecture
**Workspace structure**: Core CLI (zeeker) + shared utilities (zeeker-common) + deployment (zeeker-datasette)
CLI tool: database projects (init→add→build→deploy) + UI assets (generate→validate→deploy) + metadata generation
S3 three-pass: Database files → base assets → database-specific customizations
Fragments: main table (metadata) + fragments table (searchable chunks)
Safety: Template validation, CSS scoping `[data-database="name"]`
CLI structure: Modular commands in `zeeker/commands/` (assets.py, metadata.py, helpers.py)

## Structure
```
workspace/
├── packages/
│   ├── zeeker/              # Core CLI package
│   ├── zeeker-common/       # Shared utilities (hash, jina, openai, retry)
│   └── zeeker-datasette/    # Datasette deployment (templates, plugins, Docker)
└── examples/                # Example data projects

project/{pyproject.toml,zeeker.toml,resources/resource_name.py,project_name.db,metadata.json}
zeeker/{cli.py,commands/{assets.py,metadata.py,helpers.py}}
```

## Functions
`fetch_data(existing_table)` → List[Dict] (existing_table=Table|None, filter duplicates)
`async fetch_data(existing_table)` (concurrent I/O)
`fetch_fragments_data(existing_fragments_table, main_data_context=None)` (main_data_context avoids duplicate API calls)
`transform_data()` (optional)
Sibling imports work: resource modules can `import helper` for helpers in `resources/` — import at module top level only (dir is appended to sys.path just for the load, lowest precedence, then removed; stdlib/site-packages always win name clashes)
`--setup-fts` is idempotent (safe on incremental `--sync-from-s3` builds)

## Status Contract (unambiguous build output)
**Skip with reason**: raise `Skip` from fetch_data instead of returning `[]` to say WHY:
```python
from zeeker import Skip  # kinds: "up_to_date" (default), "blocked", "disabled"

def fetch_data(existing_table):
    if not os.environ.get("TAILSCALE_PROXY"):
        raise Skip("TAILSCALE_PROXY unset — proxy required", kind="blocked")
    return []  # plain [] still works → skip with kind "up_to_date", no reason
```
Renders `[SKIP] name  <reason> (kind)  (1.2s)`; `skip_reason`/`skip_kind` in `--json`. Works in sync + async fetch_data; safe with `fragments_on_skip` (fragments run with context `[]`). `zeeker build --fail-on-blocked` → exit 1 if any resource skipped with kind "blocked".

**Enrichment counters** (`__zeeker_report__`): multi-phase resources that UPDATE rows (0 records inserted) report work via a module-level dict, read + cleared once per build:
```python
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {"updated": 50, "enriched": 25, "notes": "phase2 drained 25"}
    return []  # renders "[SKIP] judgments  no data returned; updated=50 enriched=25"
```
Int values only (others ignored, never fails the build); totals appear in the SUMMARY footer; `extra_counts`/`notes` in `--json`.

**Warnings are machine-readable**: per-resource warnings → `ResourceOutcome.warnings` (`WARN[resource]: ...` lines in plain mode), build-level warnings (e.g. S3 sync) → `BuildReport.build_warnings` (`WARN[build]: ...`); both in the `--json` payload.

**Resource logging** (zeeker-common): consistent per-resource log lines + optional JSONL sink (`ZEEKER_BUILDLOG_JSONL=/path/to/file.jsonl`):
```python
from zeeker_common import resource_logger

log = resource_logger("judgments")
log.info("discovery starting")            # stdout: "judgments: discovery starting"
log.warn("proxy slow"); log.error("boom") # stderr
log.done(new=3, updated=50)               # "judgments: done — new=3, updated=50"
log.aborted("circuit breaker", failed=5)  # stderr: "judgments: ABORTED (circuit breaker) — failed=5"
log.skipped("nothing new")                # stderr: "judgments: SKIPPED (nothing new)"
```

## CRITICAL: Duplicate Handling
MUST filter existing IDs to avoid UNIQUE constraint errors:
```python
def fetch_data(existing_table):
    data = get_fresh_data()
    if existing_table:
        existing_ids = {row["id"] for row in existing_table.rows}
        data = [item for item in data if item["id"] not in existing_ids]
    return data
```
Time-based: `existing_table.db["_zeeker_updates"].get(table_name)["last_updated"]`
Fixes: Delete .db file or `--force-schema-reset`

## Async
`--async` for concurrent I/O (100 sequential calls = ~100s, concurrent = ~5-10s)

## Schema
Meta tables: `_zeeker_schemas` (versions), `_zeeker_updates` (timestamps, counts)
Type inference locks on first batch: int→INTEGER, float→REAL, str→TEXT, bool→INTEGER, list/dict→JSON
Schema conflicts: Add `migrate_schema()`, use `--force-schema-reset`, or delete .db
CRITICAL: Use `float` for potential decimals, consistent types, no type mixing

## Fragments
`--fragments`: Two tables (main: metadata, fragments: chunks). Context passing via `main_data_context` avoids duplicate API calls.
**Single-fetch lifecycle**: `fetch_data()` runs ONCE per build — the resource module is loaded once (also under `--parallel`) and its raw fetch output (pre-`transform_data`, snapshotted) is threaded to the fragments phase as `main_data_context` (no module reload, no second fetch). Resources may rely on this (no PID sentinels/marker files needed).
**`fragments_on_skip = true`** (per-resource in zeeker.toml, opt-in): run the fragments phase even when `fetch_data()` returns no new rows (steady-state builds), with `main_data_context=[]`. Default (flag absent): fragments only run when new main rows were inserted (unchanged behavior).
```python
def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    if main_data_context:
        return [{"parent_id": doc["id"], "text": chunk} 
                for doc in main_data_context for chunk in split_document(doc["content"])]
```
Search: `WHERE fragments_table.text MATCH 'terms'`

## S3 & Environment
Three-pass: Database files → base assets → database customizations
Template safety: ❌ Banned `database.html,table.html,index.html,query.html` ✅ Safe `database-{DBNAME}.html,custom-*.html`
Env (auto-loads `.env`): `S3_BUCKET,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY,JINA_API_TOKEN,OPENAI_API_KEY`

## Testing
Markers: `unit,integration,cli,slow,anyio` (`pytest -m marker`)
Coverage: 65% threshold, excludes templates and test files
Test organization: packages/zeeker/tests, packages/zeeker-common/tests, packages/zeeker-datasette/tests

## Selective Building
`zeeker build users posts` (builds specific resources)
`zeeker build` (builds all resources)

## Code Recipes
**Note**: These utilities are now available in `zeeker-common` package:
```python
from zeeker_common import get_hash_id, get_jina_reader_content, async_retry
from zeeker_common.openai import get_summary  # requires zeeker-common[openai]

# Jina Reader (web extraction) - now in zeeker_common.jina
@retry(stop=stop_after_attempt(3))
async def get_jina_reader_content(link: str) -> str:
    headers = {"Authorization": f"Bearer {os.environ.get('JINA_API_TOKEN')}"}
    async with httpx.AsyncClient(timeout=90) as client:
        return (await client.get(f"https://r.jina.ai/{link}", headers=headers)).text

# Hash IDs (deterministic from multiple fields) - now in zeeker_common.hashing
def get_hash_id(elements: list[str]) -> str:
    return hashlib.md5("|".join(str(e) for e in elements).encode()).hexdigest()

# OpenAI summarization - now in zeeker_common.openai
async def get_summary(text: str, system_prompt: str = None) -> str:
    client = AsyncOpenAI(max_retries=3, timeout=60)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt or "Summarize the following text concisely."},
            {"role": "user", "content": f"Summarize:\n{text}"}
        ]
    )
    return response.choices[0].message.content

# Retry decorators - now in zeeker_common.retry
from zeeker_common.retry import async_retry, sync_retry
```