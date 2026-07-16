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
Sibling imports work: resource modules can `import helper` for helpers in `resources/` (dir is on sys.path during load)
`--setup-fts` is idempotent (safe on incremental `--sync-from-s3` builds)

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
**Single-fetch lifecycle**: `fetch_data()` runs ONCE per build — the resource module is loaded once and its raw fetch output is threaded to the fragments phase as `main_data_context` (no module reload, no second fetch). Resources may rely on this (no PID sentinels/marker files needed).
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