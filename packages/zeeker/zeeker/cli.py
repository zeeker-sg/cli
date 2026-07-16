"""
Zeeker CLI - Database customization tool with project management.

Clean CLI interface that imports functionality from core modules.
"""

import subprocess
import traceback as tb_mod
from pathlib import Path

import click
from rich.console import Console

from .commands.assets import assets
from .commands.backup import backup
from .commands.helpers import (
    create_deployer,
    echo_errors,
    echo_warnings,
    load_env,
    render_build_report,
    render_resource_event,
    require_database,
    require_project,
)
from .commands.metadata import metadata
from .commands.runbook import runbook
from .core.project import ZeekerProjectManager
from .core.types import BuildReport, ValidationResult, ZeekerSchemaConflictError


# Main CLI group
@click.group()
def cli():
    """Zeeker Database Management Tool."""
    pass


# Project management commands
@cli.command()
@click.argument("project_name")
@click.option(
    "--path", type=click.Path(), help="Project directory path (default: ./{project_name})"
)
def init(project_name, path):
    """Initialize a new Zeeker project.

    Creates zeeker.toml, resources/ directory, .gitignore, and README.md.

    Example:
        zeeker init my-project
    """
    project_path = Path(path) if path else Path.cwd() / project_name
    manager = ZeekerProjectManager(project_path)

    result = manager.init_project(project_name)

    if result.errors:
        echo_errors(result)
        return

    for info in result.info:
        click.echo(f"✅ {info}")

    # Run uv sync to create virtual environment and install dependencies
    click.echo("\n🔄 Setting up virtual environment...")
    try:
        sync_result = subprocess.run(
            ["uv", "sync"], cwd=project_path, capture_output=True, text=True, check=False
        )

        if sync_result.returncode == 0:
            click.echo("✅ Virtual environment created and dependencies installed")
        else:
            click.echo(f"⚠️  uv sync failed: {sync_result.stderr.strip()}")
            click.echo("   You can run 'uv sync' manually in the project directory")
    except FileNotFoundError:
        click.echo("⚠️  uv not found - skipping virtual environment setup")
        click.echo(
            "   Install uv (https://docs.astral.sh/uv/) or use pip/poetry for dependency management"
        )

    click.echo("\nNext steps:")
    try:
        relative_path = project_path.relative_to(Path.cwd())
        click.echo(f"  1. cd {relative_path}")
    except ValueError:
        click.echo(f"  1. cd {project_path}")
    click.echo("  2. uv run zeeker add <resource_name>")
    click.echo("  3. uv run zeeker build")
    click.echo("  4. uv run zeeker deploy")


@cli.command()
@click.argument("resource_name")
@click.option("--description", help="Resource description")
@click.option("--facets", multiple=True, help="Datasette facets (can be used multiple times)")
@click.option("--sort", help="Default sort order")
@click.option("--size", type=int, help="Default page size")
@click.option(
    "--fragments", is_flag=True, help="Create a complementary fragments table for large documents"
)
@click.option(
    "--async",
    "is_async",
    is_flag=True,
    help="Generate async templates for concurrent data fetching",
)
@click.option(
    "--fts-fields",
    multiple=True,
    help="Fields to enable full-text search on (can be used multiple times)",
)
@click.option(
    "--fragments-fts-fields",
    multiple=True,
    help="Fields to enable FTS on fragments table (auto-detects text content if not specified)",
)
def add(
    resource_name,
    description,
    facets,
    sort,
    size,
    fragments,
    is_async,
    fts_fields,
    fragments_fts_fields,
):
    """Add a new resource to the project.

    Creates a Python file in resources/ with a template for data fetching.

    Examples:
        zeeker add users --description "User account data" --facets role --size 50
        zeeker add legal_docs --fragments --description "Legal documents"
        zeeker add api_data --async --description "Data from external APIs"
    """
    manager = ZeekerProjectManager()

    kwargs = {}
    if facets:
        kwargs["facets"] = list(facets)
    if sort:
        kwargs["sort"] = sort
    if size:
        kwargs["size"] = size
    if fragments:
        kwargs["fragments"] = True
    if fts_fields:
        kwargs["fts_fields"] = list(fts_fields)
    if fragments_fts_fields:
        kwargs["fragments_fts_fields"] = list(fragments_fts_fields)
    if is_async:
        kwargs["is_async"] = True

    result = manager.add_resource(resource_name, description, **kwargs)

    if result.errors:
        echo_errors(result)
        return

    for info in result.info:
        click.echo(f"✅ {info}")

    click.echo("\nNext steps:")
    click.echo(f"  1. Edit resources/{resource_name}.py")
    click.echo("  2. Implement the fetch_data() function")
    click.echo("  3. zeeker build")


@cli.command()
@click.argument("resources", nargs=-1)
@click.option(
    "--force-schema-reset", is_flag=True, help="Ignore schema conflicts and rebuild tables"
)
@click.option(
    "--sync-from-s3", is_flag=True, help="Download existing database from S3 before building"
)
@click.option(
    "--setup-fts", is_flag=True, help="Set up full-text search (FTS) indexes on configured fields"
)
@click.option("-v", "--verbose", is_flag=True, help="Show full Python tracebacks for failures")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit a single structured JSON BuildReport to stdout (tracebacks always included)",
)
@click.option(
    "--fail-on-empty",
    is_flag=True,
    help="Treat resources that returned no data as failures (exit 1 instead of passing)",
)
@click.option(
    "--fail-on-blocked",
    is_flag=True,
    help="Exit 1 if any resource skipped with kind 'blocked' (raised Skip(..., kind='blocked'))",
)
@click.option(
    "--progress-file",
    type=click.Path(),
    help="Write a JSON BuildReport snapshot to this path after each resource (atomic overwrite). "
    "Useful for trigger-and-wait callers that poll externally.",
)
@click.option(
    "--parallel",
    type=int,
    default=1,
    show_default=True,
    metavar="N",
    help="Run up to N resource fetches concurrently (I/O only; DB writes stay sequential).",
)
@click.option(
    "--post-hook",
    "post_hook",
    type=str,
    default=None,
    metavar="CMD",
    help="Shell command to run after a successful build. See `zeeker build --help` for env vars.",
)
@click.option(
    "--force-sync",
    is_flag=True,
    help="With --sync-from-s3, overwrite an existing local DB instead of refusing.",
)
def build(
    resources,
    force_schema_reset,
    sync_from_s3,
    setup_fts,
    verbose,
    as_json,
    fail_on_empty,
    fail_on_blocked,
    progress_file,
    parallel,
    post_hook,
    force_sync,
):
    """Build database from resources using sqlite-utils.

    Runs fetch_data() for specified resources and creates/updates the SQLite database.
    If no resources are specified, builds all resources in the project.

    Exit codes:
        0  all resources succeeded
        1  one or more resources failed, FTS setup failed, post-hook exited non-zero,
           --fail-on-empty with a skipped resource, or --fail-on-blocked with a
           resource that skipped with kind "blocked"
        2  fatal error (schema conflict, DB open failure, config error, local-diverged sync)

    The --post-hook command receives these env vars:
        ZEEKER_DB_PATH, ZEEKER_DB_NAME, ZEEKER_PROJECT_PATH,
        ZEEKER_BUILD_STATUS (success|partial_failure), ZEEKER_BUILD_REPORT (JSON tempfile)

    Examples:
        zeeker build                                  # Build all resources
        zeeker build --parallel 4                     # Fetch 4 resources concurrently
        zeeker build users posts                      # Build specific resources
        zeeker build --json | jq                      # Machine-readable output
        zeeker build --fail-on-empty                  # Empty fetch_data() -> exit 1
        zeeker build --progress-file build.json       # Watchable progress from outside
        zeeker build --post-hook 'sqlite3 mydb.db < patch.sql'
    """
    from .commands.helpers import write_progress_file
    from .commands.post_hook import run_post_hook

    load_env()

    resource_list = list(resources) if resources else None

    # Route any non-JSON chatter through the console; JSON mode keeps stdout clean.
    console = Console()
    if resource_list and not as_json:
        console.print(f"Building specific resources: {', '.join(resource_list)}")

    manager = ZeekerProjectManager()

    # A BuildReport we can mutate progressively for --progress-file watchers.
    progress_report = BuildReport() if progress_file else None

    def _callback(name, outcome):
        # Stream per-resource line unless emitting JSON.
        if not as_json:
            render_resource_event(name, outcome, console=console)

        # Update the progress file atomically on finish events.
        if progress_file and outcome is not None and progress_report is not None:
            progress_report.resources.append(outcome)
            write_progress_file(progress_file, progress_report)

    # Write an initial (empty) snapshot so watchers see the file exist immediately.
    if progress_file and progress_report is not None:
        write_progress_file(progress_file, progress_report)

    progress_callback = None if (as_json and not progress_file) else _callback

    try:
        result = manager.build_database(
            force_schema_reset=force_schema_reset,
            sync_from_s3=sync_from_s3,
            resources=resource_list,
            setup_fts=setup_fts,
            progress_callback=progress_callback,
            max_parallel=parallel,
            force_sync=force_sync,
        )
    except ZeekerSchemaConflictError as e:
        result = ValidationResult(is_valid=False)
        result.errors.append(str(e))
        result.tracebacks.append(tb_mod.format_exc())
        result.report = BuildReport(fatal_error=str(e))
        if progress_file:
            write_progress_file(progress_file, result.report)
        render_build_report(result, verbose=verbose, as_json=as_json, console=console)
        raise click.exceptions.Exit(2)
    except Exception as e:
        result = ValidationResult(is_valid=False)
        result.errors.append(f"Build failed: {e}")
        result.tracebacks.append(tb_mod.format_exc())
        result.report = BuildReport(fatal_error=f"Build failed: {e}")
        if progress_file:
            write_progress_file(progress_file, result.report)
        render_build_report(result, verbose=verbose, as_json=as_json, console=console)
        raise click.exceptions.Exit(2)

    # Pre-flight failures (e.g., "Unknown resources") return a ValidationResult with no
    # report — treat them as fatal so agents get a structured fatal_error message.
    if result.report is None:
        fatal_msg = result.errors[0] if result.errors else "build failed"
        result.report = BuildReport(fatal_error=fatal_msg)

    # In plain (non-TTY) text mode, warnings already stream as WARN[...] lines
    # via render_resource_event/_emit_plain; in verbose rich mode _emit_rich
    # lists them under the summary table — avoid printing them twice.
    if result.warnings and not as_json and console.is_terminal and not verbose:
        echo_warnings(result)

    report = result.report

    # Run the post-hook after the build settles but before the final render,
    # so its outcome is part of the reported payload. Skip on fatal state —
    # there's no coherent DB to patch.
    if post_hook and not report.fatal_error:
        project = manager.load_project()
        db_path = manager.project_path / project.database
        db_name = Path(project.database).stem
        hook_outcome = run_post_hook(
            post_hook,
            project_path=manager.project_path,
            db_path=db_path,
            db_name=db_name,
            report=report,
        )
        report.post_hook = hook_outcome

    # Final progress-file snapshot reflects the completed state (including
    # any post-hook outcome).
    if progress_file:
        write_progress_file(progress_file, report)

    render_build_report(result, verbose=verbose, as_json=as_json, console=console)

    if report.fatal_error:
        raise click.exceptions.Exit(2)
    if report.failed or report.fts_error:
        raise click.exceptions.Exit(1)
    if report.post_hook is not None and report.post_hook.exit_code != 0:
        raise click.exceptions.Exit(1)
    if fail_on_empty and report.skipped:
        if not as_json:
            console.print(
                f"[red]Exiting non-zero: {len(report.skipped)} resource(s) returned no data "
                "and --fail-on-empty is set.[/red]"
            )
        raise click.exceptions.Exit(1)
    blocked = [r for r in report.skipped if r.skip_kind == "blocked"]
    if fail_on_blocked and blocked:
        if not as_json:
            console.print(
                f"[red]Exiting non-zero: {len(blocked)} resource(s) skipped as blocked "
                "and --fail-on-blocked is set.[/red]"
            )
        raise click.exceptions.Exit(1)


@cli.command("deploy")
@click.option("--dry-run", is_flag=True, help="Show what would be uploaded without uploading")
@click.option("-v", "--verbose", is_flag=True, help="Show full Python traceback on failure")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit a single structured JSON deploy result to stdout",
)
def deploy_database(dry_run, verbose, as_json):
    """Deploy the project database to S3.

    Uploads the generated .db file to S3:
    s3://bucket/latest/{database_name}.db

    Exit codes:
        0  upload succeeded (or dry-run completed)
        1  upload failed
        2  configuration or setup error (missing project, env vars, db file)
    """
    import json as _json

    manager = ZeekerProjectManager()
    project = require_project(manager)
    if not project:
        if as_json:
            click.echo(_json.dumps({"status": "fatal", "error": "not_a_zeeker_project"}))
        raise click.exceptions.Exit(2)

    deployer = create_deployer()
    if not deployer:
        if as_json:
            click.echo(_json.dumps({"status": "fatal", "error": "missing_configuration"}))
        raise click.exceptions.Exit(2)

    db_path = require_database(manager, project)
    if not db_path:
        if as_json:
            click.echo(_json.dumps({"status": "fatal", "error": "database_not_found"}))
        raise click.exceptions.Exit(2)

    database_name = Path(project.database).stem
    result = deployer.upload_database(db_path, database_name, dry_run)

    if as_json:
        payload = {
            "status": "success" if result.is_valid else "failed",
            "dry_run": dry_run,
            "database": database_name,
            "destination": f"s3://{deployer.bucket_name}/latest/{database_name}.db",
            "info": list(result.info),
            "errors": list(result.errors),
            "tracebacks": list(result.tracebacks),
        }
        click.echo(_json.dumps(payload, indent=2))
        if not result.is_valid:
            raise click.exceptions.Exit(1)
        return

    if result.errors:
        echo_errors(result)
        if verbose and result.tracebacks:
            for tb in result.tracebacks:
                click.echo(tb)
        raise click.exceptions.Exit(1)

    for info in result.info:
        click.echo(f"✅ {info}")

    if not dry_run:
        click.echo("\n🚀 Database deployed successfully!")
        click.echo(f"📍 Location: s3://{deployer.bucket_name}/latest/{database_name}.db")
        click.echo("💡 For UI customizations, use: zeeker assets deploy")


# Register command groups
cli.add_command(assets)
cli.add_command(backup)
cli.add_command(metadata)
cli.add_command(runbook)


if __name__ == "__main__":
    cli()
