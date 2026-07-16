"""
RUNBOOK.md generation command.

Generates the operational document that humans AND AI monitoring agents read
to run, monitor, and interpret builds of a Zeeker data project. The file mixes
auto-generated facts (project/resource config, command reference, the build
status contract baked in verbatim from this zeeker version) with clearly
marked TODO placeholder sections for per-project operational knowledge.
"""

from datetime import date
from pathlib import Path

import click

from .. import __version__
from ..core.project import ZeekerProjectManager
from .helpers import require_project

# Resource config keys rendered as dedicated table columns.
_TABLE_KEYS = {"description", "fragments", "fragments_on_skip", "fts_fields"}

# Additional well-known keys listed as per-resource detail bullets when set.
_DETAIL_KEYS = [
    "facets",
    "sort",
    "size",
    "fragments_fts_fields",
    "sortable_columns",
    "label_column",
    "hidden",
    "units",
]

_TODO_MARKER = "<!-- TODO: fill in -->"


def _yes_no(value) -> str:
    return "yes" if value else "no"


def _fts_fields_cell(config: dict) -> str:
    fields = config.get("fts_fields") or []
    return ", ".join(f"`{f}`" for f in fields) if fields else "—"


def _resource_table(resources: dict[str, dict]) -> str:
    lines = [
        "| Resource | Description | Fragments | Fragments on skip | FTS fields |",
        "|---|---|---|---|---|",
    ]
    for name, config in resources.items():
        lines.append(
            f"| `{name}` "
            f"| {config.get('description') or '—'} "
            f"| {_yes_no(config.get('fragments'))} "
            f"| {_yes_no(config.get('fragments_on_skip'))} "
            f"| {_fts_fields_cell(config)} |"
        )
    return "\n".join(lines)


def _resource_details(resources: dict[str, dict]) -> str:
    """Bullet list of remaining known config per resource (only what exists)."""
    blocks = []
    for name, config in resources.items():
        bullets = []
        for key in _DETAIL_KEYS:
            if key in config:
                bullets.append(f"- {key.replace('_', ' ')}: `{config[key]}`")
        if config.get("fragments"):
            bullets.append(f"- fragments table: `{name}_fragments`")
        if bullets:
            blocks.append(f"**`{name}`**\n\n" + "\n".join(bullets))
    return "\n\n".join(blocks)


def _todo_section(title: str, hint: str) -> str:
    return f"## {title}\n\n{_TODO_MARKER}\n\n> {hint}\n"


def generate_runbook_content(project) -> str:
    """Render the full RUNBOOK.md content for a loaded ZeekerProject."""
    db_name = Path(project.database).stem
    today = date.today().isoformat()

    facts = [
        f"- **Project:** `{project.name}`",
        f"- **Database file:** `{project.database}` (Datasette database name: `{db_name}`)",
    ]
    if project.title:
        facts.append(f"- **Title:** {project.title}")
    if project.description:
        facts.append(f"- **Description:** {project.description}")
    if project.source:
        facts.append(f"- **Source:** {project.source}")
    if project.source_url:
        facts.append(f"- **Source URL:** {project.source_url}")
    if project.license:
        facts.append(f"- **License:** {project.license}")
    if project.license_url:
        facts.append(f"- **License URL:** {project.license_url}")

    facts_block = "\n".join(facts)
    details = _resource_details(project.resources)
    details_block = f"\n{details}\n" if details else ""

    todo_sections = "\n".join(
        [
            _todo_section(
                "What happens during a run",
                "Describe the per-resource phase narrative: what each resource fetches, "
                "in what order, which phases run inside a single build (discovery, "
                "enrichment, summarisation, fragments), and what a typical healthy log "
                "looks like end to end.",
            ),
            _todo_section(
                "Environment variables",
                "List every env var the build reads: required vs optional, what breaks "
                "or degrades when each is unset, and where secrets live (.env, CI "
                "secrets).",
            ),
            _todo_section(
                "Cadence & expected yield",
                "Build schedule, normal new-rows-per-run per resource, expected build "
                "duration ranges, and what counts as an anomaly worth flagging.",
            ),
            _todo_section(
                "Failure modes & recovery",
                "Known failure modes and how to recover: quarantines, checkpoint files, "
                "on-disk caches (what is safe to delete, what forces a re-crawl), retry "
                "behaviour, and circuit breakers.",
            ),
            _todo_section(
                "Backlog / progress queries",
                "SQL queries that show real progress (e.g. `SELECT COUNT(*) FROM t WHERE "
                "content IS NULL`), backlog sizes, and how to verify a build actually "
                "advanced the pipeline.",
            ),
            _todo_section(
                "Escalation",
                "Who/what to notify when builds fail repeatedly, thresholds for paging a "
                "human, and any dashboards or alert channels tied to this project.",
            ),
        ]
    )

    resource_table = _resource_table(project.resources)

    return f"""# RUNBOOK — {project.name}

<!-- Generated by `zeeker runbook` (zeeker {__version__}) on {today}. -->

> **Regeneration policy:** this file is generated ONCE and then hand-maintained.
> Re-running `zeeker runbook --force` overwrites the ENTIRE file — including
> everything written into the TODO sections below. Nothing is preserved on
> regeneration. To refresh the auto-generated facts without losing hand-written
> content, generate a fresh copy elsewhere (`zeeker runbook --output RUNBOOK.new.md`)
> and merge manually.

This runbook is the operational document for humans and AI monitoring agents:
how to run builds, what healthy output looks like, and how to interpret
failures and skips.

## Project facts (auto-generated)

{facts_block}

### Resources

{resource_table}
{details_block}
## Command reference (auto-generated)

```bash
uv run zeeker build                        # build all resources
uv run zeeker build <resource> [...]       # selective build
uv run zeeker build --sync-from-s3         # incremental: download existing DB from S3 first
uv run zeeker build --setup-fts            # (re)create FTS indexes on configured fields (idempotent)
uv run zeeker build --json                 # machine-readable BuildReport JSON on stdout
uv run zeeker build --progress-file p.json # atomic JSON snapshot after each resource (for watchers)
uv run zeeker build --fail-on-blocked      # exit 1 if any resource skipped with kind "blocked"
uv run zeeker deploy                       # upload the built .db to S3
```

## Status contract (auto-generated — zeeker {__version__})

This section is baked in verbatim from the installed zeeker version. Monitors
should parse builds against this contract, not against ad-hoc log scraping.

### Exit codes (`zeeker build`)

| Code | Meaning |
|---|---|
| `0` | All resources succeeded (skips are not failures). |
| `1` | One or more resources failed, FTS setup failed, post-hook exited non-zero, `--fail-on-empty` with a skipped resource, or `--fail-on-blocked` with a resource that skipped with kind `blocked`. |
| `2` | Fatal error: schema conflict, DB open failure, config error, local-diverged sync. No coherent build ran. |

### Non-TTY line grammar (plain text output, what agents see)

One status line per resource, streamed as each finishes:

```
[OK  ] <resource>  <N> records  (<T>s)
[FAIL] <resource>  <error message>  (<T>s)
[SKIP] <resource>  <reason> (<kind>)  (<T>s)
[SKIP] <resource>  no data returned  (<T>s)
WARN[<resource>]: <message>
WARN[build]: <message>
SUMMARY: <S> succeeded, <F> failed, <K> skipped in <T>s | <k1>=<v1> <k2>=<v2>
FTS_ERROR: <message>
POST_HOOK: <command> exit=<code>
FATAL: <message>
```

- `[SKIP] name  <reason> (kind)` — the resource raised `Skip(reason, kind=...)`;
  the reason says WHY. `[SKIP] name  no data returned` is a plain `return []`
  skip (implicit kind `up_to_date`, no reason).
- Enrichment counters (see below) are appended to `[OK]`/`[SKIP]` lines as
  `; key=value key=value` (never to `[FAIL]` lines), e.g.
  `[SKIP] judgments  no data returned; updated=50 enriched=25  (12.3s)`.
- `WARN[<resource>]:` lines follow that resource's status line; `WARN[build]:`
  lines are build-level warnings (e.g. S3 sync issues).
- The `SUMMARY:` footer aggregates `extra_counts` across all resources after
  a ` | ` separator (omitted when there are no counters).

### Skip kinds and what each means for a monitor

| Kind | Meaning | Bumps `_zeeker_updates.last_updated`? | Monitor action |
|---|---|---|---|
| `up_to_date` | Source was checked; nothing new. The healthy steady state. | Yes | None. |
| `blocked` | A precondition failed (proxy down, missing env var) — the source was NOT checked. | No (time-based incremental resources stay safe) | Actionable: investigate the precondition. Use `--fail-on-blocked` to turn this into exit 1. |
| `disabled` | Intentionally switched off (feature flag / config). | No | None — not an incident. |

### Enrichment counters (`__zeeker_report__`)

Multi-phase resources that UPDATE existing rows (0 records inserted) report
work via a module-level dict in the resource module:

```python
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {{"updated": 50, "enriched": 25, "notes": "phase2 drained 25"}}
    return []
```

- Read and cleared on EVERY exit path — success, skip, even a fetch_data crash
  (work done before the crash stays visible).
- Re-read after the fragments phase; counters set in `fetch_fragments_data`
  merge in, summing on key collision.
- Int values only (other value types are ignored, never fail the build).
- Rendered as `key=value` on status lines, aggregated totals in the `SUMMARY:`
  footer, and carried as `extra_counts` / `notes` in `--json`.
- A "0 succeeded" SUMMARY with non-zero counters means real enrichment work
  happened — do not read it as a dead build.

### JSON payload (`--json` and `--progress-file` share the same schema)

Top-level fields:

| Field | Type | Notes |
|---|---|---|
| `status` | string | `success` \\| `partial_failure` \\| `failed` \\| `fatal` |
| `total_duration_s` | float | Whole-build wall time. |
| `resources` | array | One object per resource (fields below). |
| `build_warnings` | array of strings | Build-level warnings (`WARN[build]:` lines). |
| `fts_error` | string or null | FTS setup failure, if any. |
| `fatal_error` | string or null | Set when the build died before/without a per-resource report. |
| `post_hook` | object or null | `{{command, exit_code, stdout, stderr}}` when `--post-hook` ran. |

Per-resource object fields:

| Field | Type | Notes |
|---|---|---|
| `name` | string | Resource name. |
| `status` | string | `success` \\| `failed` \\| `skipped` |
| `records` | int | New main-table rows inserted. |
| `duration_s` | float | Per-resource wall time. |
| `error_message` | string or null | Set on failure. |
| `traceback` | string or null | Full Python traceback on failure (paths CWD-relativized). |
| `fragments_records` | int or null | Fragment rows inserted, when a fragments phase ran. |
| `skip_reason` | string or null | The `Skip(...)` reason; null for plain returned-`[]` skips. |
| `skip_kind` | string or null | `up_to_date` \\| `blocked` \\| `disabled` (only meaningful when skipped). |
| `warnings` | array of strings | Per-resource warnings (`WARN[<resource>]:` lines). |
| `extra_counts` | object | Int counters from `__zeeker_report__`. |
| `notes` | string or null | Free-text note from `__zeeker_report__`. |

---

{todo_sections}"""


@click.command()
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    metavar="PATH",
    help="Where to write the runbook (default: RUNBOOK.md in the project root).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file at the output path.")
def runbook(output_path, force):
    """Generate RUNBOOK.md — the operational doc for humans and monitoring agents.

    Combines auto-generated facts (project/resource config from zeeker.toml,
    the zeeker command reference, and this zeeker version's build status
    contract) with TODO placeholder sections to be filled in per project.

    The file is generated once and then hand-maintained. Re-running with
    --force overwrites the ENTIRE file, including hand-written TODO content.

    Examples:
        zeeker runbook
        zeeker runbook --output docs/RUNBOOK.md
        zeeker runbook --force
    """
    manager = ZeekerProjectManager()
    project = require_project(manager)
    if not project:
        raise click.exceptions.Exit(1)

    target = Path(output_path) if output_path else manager.project_path / "RUNBOOK.md"

    if target.exists() and not force:
        click.echo(f"❌ {target} already exists — use --force to overwrite")
        click.echo(
            "   Note: --force replaces the ENTIRE file, including hand-written TODO sections."
        )
        raise click.exceptions.Exit(1)

    content = generate_runbook_content(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    click.echo(f"✅ Generated runbook: {target}")
    click.echo("\nNext steps:")
    click.echo("  1. Fill in the '<!-- TODO: fill in -->' sections")
    click.echo("  2. Commit RUNBOOK.md alongside the project")
