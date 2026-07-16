"""
Shared helper functions for CLI commands.
"""

import json
import os
import re
from dataclasses import asdict
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ..core.types import BuildReport, ResourceOutcome, ValidationResult


def echo_errors(result: ValidationResult) -> None:
    """Display errors from a ValidationResult."""
    for error in result.errors:
        click.echo(f"❌ {error}")


def echo_warnings(result: ValidationResult) -> None:
    """Display warnings from a ValidationResult."""
    for warning in result.warnings:
        click.echo(f"⚠️ {warning}")


def load_env() -> None:
    """Load .env file from current directory if present."""
    load_dotenv(dotenv_path=Path.cwd() / ".env")


def require_project(manager) -> object | None:
    """Validate project root and load project, or print error and return None."""
    if not manager.is_project_root():
        click.echo("❌ Not in a Zeeker project directory (no zeeker.toml found)")
        return None
    try:
        return manager.load_project()
    except Exception as e:
        click.echo(f"❌ Error loading project: {e}")
        return None


def require_database(manager, project) -> Path | None:
    """Validate database file exists, or print error and return None."""
    db_path = manager.project_path / project.database
    if not db_path.exists():
        click.echo(f"❌ Database not found: {project.database}")
        click.echo("Run 'zeeker build' first to build the database")
        return None
    return db_path


def create_deployer():
    """Create a ZeekerDeployer, loading .env first. Returns None on config error."""
    from ..core.deployer import ZeekerDeployer

    load_env()
    try:
        return ZeekerDeployer()
    except ValueError as e:
        click.echo(f"❌ Configuration error: {e}")
        click.echo("Please set the required environment variables:")
        click.echo("  - S3_BUCKET")
        click.echo("  - AWS_ACCESS_KEY_ID")
        click.echo("  - AWS_SECRET_ACCESS_KEY")
        click.echo("  - S3_ENDPOINT_URL (optional)")
        return None


def show_generated_metadata(table_name: str, metadata: dict, dry_run: bool = False):
    """Helper to display generated metadata in a nice format."""
    prefix = "📋" if dry_run else "✨"
    action = "Would generate" if dry_run else "Generated"

    click.echo(f"\n{prefix} {action} metadata for '{table_name}':")

    if "columns" in metadata:
        click.echo("   Column descriptions:")
        for col_name, description in metadata["columns"].items():
            click.echo(f"     • {col_name}: {description}")

    if "suggested_facets" in metadata:
        facets = ", ".join(metadata["suggested_facets"])
        click.echo(f"   💡 Suggested facets: {facets}")

    if "suggested_sortable" in metadata:
        sortable = ", ".join(metadata["suggested_sortable"])
        click.echo(f"   💡 Suggested sortable columns: {sortable}")

    if "suggested_label" in metadata:
        click.echo(f"   💡 Suggested label column: {metadata['suggested_label']}")


def show_resource_metadata(resource_name: str, resource_config: dict):
    """Helper to display current resource metadata."""
    click.echo(f"📊 Resource: {resource_name}")

    if "description" in resource_config:
        click.echo(f"   Description: {resource_config['description']}")

    if "columns" in resource_config:
        click.echo("   Column descriptions:")
        for col_name, description in resource_config["columns"].items():
            click.echo(f"     • {col_name}: {description}")
    else:
        click.echo("   No column descriptions")

    metadata_fields = [
        "facets",
        "sort",
        "size",
        "sortable_columns",
        "label_column",
        "units",
        "hidden",
    ]
    for field in metadata_fields:
        if field in resource_config:
            click.echo(f"   {field.replace('_', ' ').title()}: {resource_config[field]}")


# ----------------------------------------------------------------------------
# Build report rendering
# ----------------------------------------------------------------------------

# Matches `File "<path>"` lines in Python tracebacks so we can rewrite absolute
# paths to be relative to CWD for agent consumption.
_TRACEBACK_PATH_RE = re.compile(r'File "([^"]+)"')

_STATUS_GLYPHS = {
    "success": ("[green]✓[/green]", "OK"),
    "failed": ("[red]✗[/red]", "FAIL"),
    "skipped": ("[yellow]−[/yellow]", "SKIP"),
}


def _relativize_traceback(tb: str) -> str:
    """Rewrite absolute paths in a traceback to be CWD-relative where possible."""
    if not tb:
        return tb
    cwd = os.getcwd()

    def _sub(match: re.Match) -> str:
        raw = match.group(1)
        try:
            rel = os.path.relpath(raw, start=cwd)
        except ValueError:
            return match.group(0)
        # Prefer relative only when it doesn't escape too far upward
        if rel.startswith(".." + os.sep + ".." + os.sep + ".."):
            return match.group(0)
        return f'File "{rel}"'

    return _TRACEBACK_PATH_RE.sub(_sub, tb)


def _format_counts(counts: dict[str, int]) -> str:
    """Render extra counts as ``k1=v1 k2=v2`` (insertion order preserved)."""
    return " ".join(f"{k}={v}" for k, v in counts.items())


def _skip_note(outcome: ResourceOutcome) -> str:
    """Human-readable note for a skipped resource.

    With a Skip-provided reason: ``<reason> (<kind>)``. Otherwise the classic
    ``no data returned`` (a plain returned-[] skip).
    """
    if outcome.skip_reason:
        return f"{outcome.skip_reason} ({outcome.skip_kind or 'up_to_date'})"
    return "no data returned"


def _aggregate_extra_counts(report: BuildReport) -> dict[str, int]:
    """Sum extra_counts across all resources (for the SUMMARY footer)."""
    totals: dict[str, int] = {}
    for r in report.resources:
        for k, v in r.extra_counts.items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _report_overall_status(report: BuildReport) -> str:
    if report.fatal_error:
        return "fatal"
    if report.failed or report.fts_error:
        return "partial_failure" if report.succeeded else "failed"
    return "success"


def render_resource_event(
    name: str,
    outcome: ResourceOutcome | None,
    *,
    console: Console,
) -> None:
    """Stream a per-resource line during the build.

    Called by the CLI on both start (outcome=None) and finish events. On start,
    emits a dim "building" hint in TTY mode only. On finish, emits a colored
    glyph line in TTY mode or a stable ``[OK]/[FAIL]/[SKIP]`` prefix in non-TTY
    mode for agent parsing.
    """
    if outcome is None:
        if console.is_terminal:
            console.print(f"[dim]→ Building [cyan]{escape(name)}[/cyan]...[/dim]")
        return

    counts = _format_counts(outcome.extra_counts) if outcome.extra_counts else ""

    if console.is_terminal:
        # User-controlled strings (skip reasons, error messages, count keys)
        # must be markup-escaped: a reason like "proxy down [/socks5]" would
        # otherwise raise MarkupError inside the progress callback and turn a
        # healthy build into a fatal error.
        glyph, _ = _STATUS_GLYPHS[outcome.status]
        if outcome.status == "success":
            detail = f"{outcome.records} records"
        elif outcome.status == "failed":
            detail = f"[red]{escape(outcome.error_message or 'failed')}[/red]"
        else:  # skipped
            detail = f"[yellow]{escape(_skip_note(outcome))}[/yellow]"
        if counts and outcome.status != "failed":
            detail += f"; [cyan]{escape(counts)}[/cyan]"
        console.print(
            f"{glyph} [bold]{escape(name)}[/bold]  {detail}  "
            f"[dim]({outcome.duration_s:.1f}s)[/dim]"
        )
    else:
        prefix = _STATUS_GLYPHS[outcome.status][1]
        if outcome.status == "success":
            note = f"{outcome.records} records"
        elif outcome.status == "failed":
            note = outcome.error_message or "failed"
        else:  # skipped
            note = _skip_note(outcome)
        if counts and outcome.status != "failed":
            note += f"; {counts}"
        console.print(
            f"[{prefix:<4}] {name:<24} {note}  ({outcome.duration_s:.1f}s)",
            markup=False,
            highlight=False,
        )
        for warning in outcome.warnings:
            console.print(f"WARN[{name}]: {warning}", markup=False, highlight=False)


def render_build_report(
    result: ValidationResult,
    *,
    verbose: bool,
    as_json: bool,
    console: Console,
) -> None:
    """Emit the build outcome in the requested format.

    - ``as_json``: single JSON object to stdout. Tracebacks always included.
    - TTY text mode: rich summary table + optional traceback panels when ``verbose``.
    - Non-TTY text mode: one ``[OK]`` / ``[FAIL]`` / ``[SKIP]`` line per resource
      (already streamed during the build) + a ``SUMMARY:`` footer. With ``verbose``,
      tracebacks printed under failures.
    """
    report = result.report or BuildReport()

    if as_json:
        _emit_json(report, console=console)
        return

    if console.is_terminal:
        _emit_rich(report, verbose=verbose, console=console)
    else:
        _emit_plain(report, verbose=verbose, console=console)


def _build_report_payload(report: BuildReport) -> dict:
    """Serialize a BuildReport to the stable JSON schema (used by both --json and
    --progress-file so external watchers and CLI consumers see identical shape)."""
    payload = {
        "status": _report_overall_status(report),
        "total_duration_s": round(report.total_duration_s, 3),
        "resources": [asdict(r) for r in report.resources],
        "build_warnings": list(report.build_warnings),
        "fts_error": report.fts_error,
        "fatal_error": report.fatal_error,
        "post_hook": asdict(report.post_hook) if report.post_hook is not None else None,
    }
    for item in payload["resources"]:
        if item.get("traceback"):
            item["traceback"] = _relativize_traceback(item["traceback"])
    return payload


def write_progress_file(path: str | os.PathLike, report: BuildReport) -> None:
    """Atomically overwrite ``path`` with a JSON snapshot of ``report``.

    Writes to a sibling ``.tmp`` file then renames, so external watchers never
    see a truncated file. Swallows I/O errors silently — a progress file failure
    must never fail the build.
    """
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(_build_report_payload(report), indent=2))
        os.replace(tmp, target)
    except Exception:
        # Progress reporting is best-effort — never fail a build on it.
        pass


def _emit_json(report: BuildReport, *, console: Console) -> None:
    console.print(
        json.dumps(_build_report_payload(report), indent=2),
        markup=False,
        highlight=False,
    )


def _emit_rich(report: BuildReport, *, verbose: bool, console: Console) -> None:
    if report.fatal_error:
        console.print(
            Panel(escape(report.fatal_error), title="[red]Fatal error[/red]", border_style="red")
        )
        return

    if not report.resources and not report.fts_error:
        console.print("[yellow]No resources built.[/yellow]")
        return

    table = Table(title="Build report", show_lines=False)
    table.add_column("Resource", style="bold")
    table.add_column("Status")
    table.add_column("Records", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Notes")

    for r in report.resources:
        glyph, _ = _STATUS_GLYPHS[r.status]
        if r.status == "success":
            notes = ""
            if r.fragments_records is not None:
                notes = f"+{r.fragments_records} fragments"
            records = str(r.records)
        elif r.status == "failed":
            notes = r.error_message or ""
            records = ""
        else:  # skipped
            notes = _skip_note(r)
            records = ""
        if r.extra_counts and r.status != "failed":
            counts = _format_counts(r.extra_counts)
            notes = f"{notes}; {counts}" if notes else counts
        if r.warnings:
            warn_note = f"⚠ {len(r.warnings)} warning{'s' if len(r.warnings) != 1 else ''}"
            notes = f"{notes}; {warn_note}" if notes else warn_note
        # Escape user-controlled cell content (skip reasons, error messages,
        # count keys) so bracketed tokens can't raise MarkupError or vanish.
        table.add_row(escape(r.name), glyph, records, f"{r.duration_s:.1f}s", escape(notes))

    console.print(table)

    succeeded = len(report.succeeded)
    failed = len(report.failed)
    skipped = len(report.skipped)
    total = len(report.resources)
    totals = _aggregate_extra_counts(report)
    totals_note = f" | {escape(_format_counts(totals))}" if totals else ""
    console.print(
        f"[bold]{succeeded} of {total} resources succeeded[/bold] "
        f"({failed} failed, {skipped} skipped) in {report.total_duration_s:.1f}s{totals_note}"
    )

    if verbose:
        for r in report.resources:
            for warning in r.warnings:
                console.print(f"[yellow]⚠ {escape(r.name)}:[/yellow] {escape(warning)}")
        for warning in report.build_warnings:
            console.print(f"[yellow]⚠ build:[/yellow] {escape(warning)}")

    if report.fts_error:
        console.print(f"[red]FTS setup failed:[/red] {escape(report.fts_error)}")

    if report.post_hook is not None:
        hook = report.post_hook
        colour = "green" if hook.exit_code == 0 else "red"
        console.print(
            f"[bold]post-hook:[/bold] [dim]{escape(hook.command)}[/dim] "
            f"→ [{colour}]exit {hook.exit_code}[/{colour}]"
        )
        if verbose and hook.exit_code != 0:
            body = ""
            if hook.stdout:
                body += f"[bold]stdout[/bold]\n{escape(hook.stdout)}"
            if hook.stderr:
                if body:
                    body += "\n"
                body += f"[bold]stderr[/bold]\n{escape(hook.stderr)}"
            if body:
                console.print(Panel(body, title="[red]post-hook output[/red]", border_style="red"))

    if verbose:
        for r in report.failed:
            if r.traceback:
                console.print(
                    Panel(
                        escape(_relativize_traceback(r.traceback)),
                        title=f"[red]Traceback · {escape(r.name)}[/red]",
                        border_style="red",
                    )
                )


def _emit_plain(report: BuildReport, *, verbose: bool, console: Console) -> None:
    # Per-resource lines already streamed via render_resource_event during the build,
    # so here we only emit the summary + verbose tracebacks + fatal/FTS errors.
    if report.fatal_error:
        console.print(f"FATAL: {report.fatal_error}", markup=False, highlight=False)
        return

    for warning in report.build_warnings:
        console.print(f"WARN[build]: {warning}", markup=False, highlight=False)

    succeeded = len(report.succeeded)
    failed = len(report.failed)
    skipped = len(report.skipped)
    totals = _aggregate_extra_counts(report)
    totals_note = f" | {_format_counts(totals)}" if totals else ""
    console.print(
        f"SUMMARY: {succeeded} succeeded, {failed} failed, {skipped} skipped "
        f"in {report.total_duration_s:.1f}s{totals_note}",
        markup=False,
        highlight=False,
    )

    if report.fts_error:
        console.print(f"FTS_ERROR: {report.fts_error}", markup=False, highlight=False)

    if report.post_hook is not None:
        hook = report.post_hook
        console.print(
            f"POST_HOOK: {hook.command} exit={hook.exit_code}",
            markup=False,
            highlight=False,
        )
        if verbose and hook.exit_code != 0:
            if hook.stdout:
                console.print(f"POST_HOOK_STDOUT:\n{hook.stdout}", markup=False, highlight=False)
            if hook.stderr:
                console.print(f"POST_HOOK_STDERR:\n{hook.stderr}", markup=False, highlight=False)

    if verbose:
        for r in report.failed:
            if r.traceback:
                console.print(
                    f"TRACEBACK: {r.name}\n{_relativize_traceback(r.traceback)}",
                    markup=False,
                    highlight=False,
                )
