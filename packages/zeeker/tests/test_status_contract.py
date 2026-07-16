"""Tests for the build "status contract" — unambiguous machine-readable output.

Covers:
- Skip(reason, kind) raised from fetch_data (sync + async) → status "skipped"
  with skip_reason / skip_kind on the ResourceOutcome
- returning [] still maps to a skip with kind "up_to_date" and no reason
- Skip raised during the schema-check sample fetch is not a schema error and
  does not fail the build (and fetch_data still runs exactly once)
- skip detection no longer string-matches "No data returned" info messages
- --fail-on-blocked exit code
- warnings threaded into ResourceOutcome.warnings and BuildReport.build_warnings,
  and both present in the JSON payload
- __zeeker_report__ extra counters: read leniently, rendered, reset per build
- fragments_on_skip runs fragments with context [] for Skip-raised skips
- rendering of skip reasons / counts / warnings in plain (non-TTY) mode
"""

import io
import json
import re
import sqlite3
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from zeeker import Skip
from zeeker.cli import cli
from zeeker.commands.helpers import (
    _build_report_payload,
    _emit_plain,
    render_resource_event,
)
from zeeker.core.database.builder import DatabaseBuilder
from zeeker.core.project import ZeekerProjectManager
from zeeker.core.types import BuildReport, ResourceOutcome, ValidationResult

pytestmark = pytest.mark.unit


def _make_project(tmp_path: Path, toml_body: str) -> ZeekerProjectManager:
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


def _plain_console(buffer: io.StringIO) -> Console:
    return Console(file=buffer, force_terminal=False, width=200)


BLOCKED_RESOURCE = """
from zeeker import Skip

def fetch_data(existing_table):
    raise Skip("TAILSCALE_PROXY unset — proxy required", kind="blocked")
"""


class TestSkipException:
    def test_skip_default_kind(self):
        skip = Skip("nothing new")
        assert skip.reason == "nothing new"
        assert skip.kind == "up_to_date"
        assert str(skip) == "nothing new"

    def test_skip_invalid_kind_rejected(self):
        with pytest.raises(ValueError):
            Skip("reason", kind="bogus")

    def test_skip_importable_from_zeeker(self):
        from zeeker import Skip as TopLevelSkip
        from zeeker.core.types import Skip as TypesSkip

        assert TopLevelSkip is TypesSkip


class TestSkipInBuild:
    def test_sync_fetch_raising_skip_maps_to_skipped_outcome(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.proxy_bound]\ndescription = 'x'\n")
        (tmp_path / "resources" / "proxy_bound.py").write_text(BLOCKED_RESOURCE)

        result = manager.build_database()
        assert result.is_valid, result.errors

        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.skip_kind == "blocked"
        assert outcome.skip_reason == "TAILSCALE_PROXY unset — proxy required"
        assert outcome.records == 0

    def test_async_fetch_raising_skip_maps_to_skipped_outcome(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.async_skip]\ndescription = 'x'\n")
        (tmp_path / "resources" / "async_skip.py").write_text(
            """
from zeeker import Skip

async def fetch_data(existing_table):
    raise Skip("feature flag off", kind="disabled")
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors

        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.skip_kind == "disabled"
        assert outcome.skip_reason == "feature flag off"

    def test_empty_return_maps_to_up_to_date_skip_without_reason(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.quiet]\ndescription = 'x'\n")
        (tmp_path / "resources" / "quiet.py").write_text(
            "def fetch_data(existing_table):\n    return []\n"
        )

        result = manager.build_database()
        assert result.is_valid, result.errors

        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.skip_kind == "up_to_date"
        assert outcome.skip_reason is None

    def test_skip_during_schema_check_does_not_fail_build_and_fetch_runs_once(self, tmp_path):
        """On an incremental build (existing table), the schema-check sample
        fetch observes the Skip first — it must not be treated as a schema
        error, must not fail the build, and fetch_data must run once."""
        fetch_counter = tmp_path / "count.txt"
        flag = tmp_path / "skip_now.flag"
        manager = _make_project(tmp_path, "[resource.docs]\ndescription = 'x'\n")
        (tmp_path / "resources" / "docs.py").write_text(
            f"""
from pathlib import Path
from zeeker import Skip

COUNTER = {str(fetch_counter)!r}
FLAG = {str(flag)!r}

def fetch_data(existing_table):
    p = Path(COUNTER)
    p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))
    if Path(FLAG).exists():
        raise Skip("source unreachable", kind="blocked")
    return [{{"id": 1, "title": "seed"}}]
"""
        )

        first = manager.build_database()
        assert first.is_valid, first.errors
        assert first.report.resources[0].status == "success"
        assert int(fetch_counter.read_text()) == 1

        flag.write_text("skip")
        second = manager.build_database()
        assert second.is_valid, second.errors
        outcome = second.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.skip_kind == "blocked"
        assert outcome.skip_reason == "source unreachable"
        # No spurious schema warnings from the Skip.
        assert not outcome.warnings
        assert int(fetch_counter.read_text()) == 2, "fetch_data must run once per build"

    def test_skip_with_fragments_on_skip_runs_fragments_with_empty_context(self, tmp_path):
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
        (tmp_path / "resources" / "enrich.py").write_text(
            f"""
from pathlib import Path
from zeeker import Skip

CONTEXT_FILE = {str(context_file)!r}

def fetch_data(existing_table):
    raise Skip("nothing new upstream")

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    Path(CONTEXT_FILE).write_text(repr(main_data_context))
    return [{{"id": 1, "parent_id": 1, "text": "enriched fragment"}}]
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors

        assert context_file.exists(), "fragments must run for a Skip-raised skip"
        assert context_file.read_text() == "[]"

        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.skip_reason == "nothing new upstream"
        assert outcome.fragments_records == 1

        conn = sqlite3.connect(tmp_path / "test_project.db")
        try:
            frag_count = conn.execute("SELECT COUNT(*) FROM enrich_fragments").fetchone()[0]
        finally:
            conn.close()
        assert frag_count == 1

    def test_parallel_prewarm_handles_skip_without_warning(self, tmp_path):
        """Under --parallel, a Skip in the pre-warm phase must not produce a
        'pre-fetch failed' warning and must still land as a skipped outcome."""
        manager = _make_project(
            tmp_path,
            """\
            [resource.blocked_one]
            description = "x"

            [resource.normal_one]
            description = "y"
            """,
        )
        (tmp_path / "resources" / "blocked_one.py").write_text(BLOCKED_RESOURCE)
        (tmp_path / "resources" / "normal_one.py").write_text(
            "def fetch_data(existing_table):\n    return [{'id': 1}]\n"
        )

        result = manager.build_database(max_parallel=2)
        assert result.is_valid, result.errors
        assert not any("pre-fetch failed" in w for w in result.warnings)
        assert not result.report.build_warnings

        by_name = {r.name: r for r in result.report.resources}
        assert by_name["blocked_one"].status == "skipped"
        assert by_name["blocked_one"].skip_kind == "blocked"
        assert by_name["normal_one"].status == "success"


class TestNoStringMatchSkipDetection:
    def test_outcome_uses_typed_flag_not_info_strings(self):
        """Regression: a successful resource whose info happens to contain
        'No data returned' must NOT be classified as skipped."""
        rr = ValidationResult(is_valid=True, records=5)
        rr.info.append("No data returned for resource 'other' - skipping")  # red herring
        outcome = DatabaseBuilder._build_resource_outcome("x", rr, 1.0)
        assert outcome.status == "success"
        assert outcome.records == 5

    def test_outcome_skipped_via_typed_flag(self):
        rr = ValidationResult(is_valid=True, records=0)
        rr.skipped = True
        rr.skip_kind = "blocked"
        rr.skip_reason = "proxy down"
        outcome = DatabaseBuilder._build_resource_outcome("x", rr, 1.0)
        assert outcome.status == "skipped"
        assert outcome.skip_kind == "blocked"
        assert outcome.skip_reason == "proxy down"


class TestFailOnBlockedFlag:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _make_cli_project(self, resource_code: str) -> None:
        manager = ZeekerProjectManager(Path.cwd())
        assert manager.init_project("cli_project").is_valid
        Path("zeeker.toml").write_text(
            textwrap.dedent(
                """\
                [project]
                name = "cli_project"
                database = "cli_project.db"

                [resource.res]
                description = "x"
                """
            )
        )
        (Path("resources") / "res.py").write_text(resource_code)

    def test_blocked_skip_exits_1_with_flag(self, runner):
        with runner.isolated_filesystem():
            self._make_cli_project(BLOCKED_RESOURCE)
            result = runner.invoke(cli, ["build", "--fail-on-blocked"])
            assert result.exit_code == 1
            assert "blocked" in result.output

    def test_blocked_skip_exits_0_without_flag(self, runner):
        with runner.isolated_filesystem():
            self._make_cli_project(BLOCKED_RESOURCE)
            result = runner.invoke(cli, ["build"])
            assert result.exit_code == 0
            # Streamed skip line carries the reason and kind (may be wrapped
            # by the 80-col non-TTY console, so assert on the tail).
            assert "(blocked)" in result.output

    def test_up_to_date_skip_exits_0_with_flag(self, runner):
        with runner.isolated_filesystem():
            self._make_cli_project("def fetch_data(existing_table):\n    return []\n")
            result = runner.invoke(cli, ["build", "--fail-on-blocked"])
            assert result.exit_code == 0

    def test_skip_reason_in_json_output(self, runner):
        with runner.isolated_filesystem():
            self._make_cli_project(BLOCKED_RESOURCE)
            result = runner.invoke(cli, ["build", "--json"])
            assert result.exit_code == 0
            payload = json.loads(result.output)
            res = payload["resources"][0]
            assert res["status"] == "skipped"
            assert res["skip_kind"] == "blocked"
            assert res["skip_reason"] == "TAILSCALE_PROXY unset — proxy required"
            assert res["warnings"] == []
            assert payload["build_warnings"] == []


class TestWarningsInPayload:
    def test_resource_warning_reaches_outcome_and_payload(self, tmp_path):
        """A schema sample fetch failure produces a per-resource warning that
        must land on the (failed) outcome and in the JSON payload."""
        flag = tmp_path / "explode.flag"
        manager = _make_project(tmp_path, "[resource.docs]\ndescription = 'x'\n")
        (tmp_path / "resources" / "docs.py").write_text(
            f"""
from pathlib import Path

FLAG = {str(flag)!r}

def fetch_data(existing_table):
    if Path(FLAG).exists():
        raise RuntimeError("connection refused")
    return [{{"id": 1, "title": "seed"}}]
"""
        )

        first = manager.build_database()
        assert first.is_valid, first.errors

        flag.write_text("boom")
        second = manager.build_database()
        assert not second.is_valid

        outcome = second.report.resources[0]
        assert outcome.status == "failed"
        assert any("Schema sample fetch failed" in w for w in outcome.warnings)
        # The build-level ValidationResult carries them too (text mode).
        assert any("Schema sample fetch failed" in w for w in second.warnings)

        payload = _build_report_payload(second.report)
        assert any("Schema sample fetch failed" in w for w in payload["resources"][0]["warnings"])

    def test_build_warnings_in_report_and_payload(self, tmp_path, monkeypatch):
        """S3 sync failure surfaces in BuildReport.build_warnings and the payload."""
        for var in ("S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            monkeypatch.delenv(var, raising=False)
        manager = _make_project(tmp_path, "[resource.simple]\ndescription = 'x'\n")
        (tmp_path / "resources" / "simple.py").write_text(
            "def fetch_data(existing_table):\n    return [{'id': 1}]\n"
        )

        result = manager.build_database(sync_from_s3=True)
        report = result.report
        assert any("S3 sync failed" in w for w in report.build_warnings)

        payload = _build_report_payload(report)
        assert any("S3 sync failed" in w for w in payload["build_warnings"])


class TestZeekerReportCounters:
    def test_counters_on_skipped_resource(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.enricher]\ndescription = 'x'\n")
        (tmp_path / "resources" / "enricher.py").write_text(
            """
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {"updated": 50, "enriched": 25, "notes": "phase2 drained 25"}
    return []
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors

        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.extra_counts == {"updated": 50, "enriched": 25}
        assert outcome.notes == "phase2 drained 25"

        payload = _build_report_payload(result.report)
        assert payload["resources"][0]["extra_counts"] == {"updated": 50, "enriched": 25}
        assert payload["resources"][0]["notes"] == "phase2 drained 25"

    def test_counters_on_skip_raised_resource(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.enricher]\ndescription = 'x'\n")
        (tmp_path / "resources" / "enricher.py").write_text(
            """
from zeeker import Skip

def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {"updated": 7}
    raise Skip("up to date")
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors
        outcome = result.report.resources[0]
        assert outcome.status == "skipped"
        assert outcome.extra_counts == {"updated": 7}

    def test_malformed_report_never_fails_build(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.messy]\ndescription = 'x'\n")
        (tmp_path / "resources" / "messy.py").write_text(
            """
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {
        "updated": "fifty",      # non-int → ignored
        "flag": True,            # bool → ignored
        "enriched": 3,           # kept
        42: 99,                  # non-str key → ignored
        "notes": ["not", "str"], # non-str notes → ignored
    }
    return [{"id": 1}]
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors
        outcome = result.report.resources[0]
        assert outcome.status == "success"
        assert outcome.extra_counts == {"enriched": 3}
        assert outcome.notes is None

    def test_non_dict_report_ignored(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.weird]\ndescription = 'x'\n")
        (tmp_path / "resources" / "weird.py").write_text(
            """
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = "not a dict"
    return [{"id": 1}]
"""
        )
        result = manager.build_database()
        assert result.is_valid, result.errors
        assert result.report.resources[0].extra_counts == {}

    def test_report_attribute_reset_after_read(self, tmp_path):
        """The attribute is deleted after reading so stale counts can't leak
        into a later build that doesn't set it."""
        set_flag = tmp_path / "set_report.flag"
        manager = _make_project(tmp_path, "[resource.oneshot]\ndescription = 'x'\n")
        (tmp_path / "resources" / "oneshot.py").write_text(
            f"""
from pathlib import Path

FLAG = {str(set_flag)!r}

def fetch_data(existing_table):
    if Path(FLAG).exists():
        global __zeeker_report__
        __zeeker_report__ = {{"updated": 9}}
    return []
"""
        )

        set_flag.write_text("on")
        first = manager.build_database()
        assert first.report.resources[0].extra_counts == {"updated": 9}

        set_flag.unlink()
        second = manager.build_database()
        assert second.report.resources[0].extra_counts == {}, "stale counts must not leak"


class TestRendering:
    def test_plain_skip_line_with_reason_and_kind(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="pdpc",
            status="skipped",
            duration_s=1.2,
            skip_reason="proxy down",
            skip_kind="blocked",
        )
        render_resource_event("pdpc", outcome, console=_plain_console(buf))
        line = buf.getvalue()
        assert "[SKIP]" in line
        assert "proxy down (blocked)" in line
        assert "(1.2s)" in line

    def test_plain_skip_line_without_reason_keeps_legacy_text(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="quiet", status="skipped", duration_s=0.1, skip_kind="up_to_date"
        )
        render_resource_event("quiet", outcome, console=_plain_console(buf))
        assert "no data returned" in buf.getvalue()

    def test_plain_lines_append_extra_counts(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="judgments",
            status="skipped",
            duration_s=1802.3,
            skip_reason="up to date",
            skip_kind="up_to_date",
            extra_counts={"updated": 50, "enriched": 25},
        )
        render_resource_event("judgments", outcome, console=_plain_console(buf))
        line = buf.getvalue()
        assert "up to date (up_to_date); updated=50 enriched=25" in line

    def test_plain_success_line_appends_extra_counts(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="docs", status="success", records=3, duration_s=2.0, extra_counts={"updated": 4}
        )
        render_resource_event("docs", outcome, console=_plain_console(buf))
        assert "3 records; updated=4" in buf.getvalue()

    def test_plain_warn_lines_per_resource(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="docs",
            status="success",
            records=1,
            duration_s=0.5,
            warnings=["schema check ran blind", "second warning"],
        )
        render_resource_event("docs", outcome, console=_plain_console(buf))
        out = buf.getvalue()
        assert "WARN[docs]: schema check ran blind" in out
        assert "WARN[docs]: second warning" in out

    def test_summary_footer_includes_total_extra_counts(self):
        buf = io.StringIO()
        report = BuildReport(
            resources=[
                ResourceOutcome(
                    name="a",
                    status="skipped",
                    skip_kind="up_to_date",
                    extra_counts={"updated": 50, "enriched": 25},
                ),
                ResourceOutcome(name="b", status="success", records=2, extra_counts={"updated": 5}),
            ],
            total_duration_s=3.0,
        )
        _emit_plain(report, verbose=False, console=_plain_console(buf))
        out = buf.getvalue()
        assert "SUMMARY: 1 succeeded, 0 failed, 1 skipped" in out
        assert "updated=55" in out
        assert "enriched=25" in out

    def test_summary_footer_unchanged_when_no_counts(self):
        buf = io.StringIO()
        report = BuildReport(
            resources=[ResourceOutcome(name="a", status="success", records=1)],
            total_duration_s=1.0,
        )
        _emit_plain(report, verbose=False, console=_plain_console(buf))
        out = buf.getvalue()
        assert "SUMMARY: 1 succeeded, 0 failed, 0 skipped in 1.0s\n" in out

    def test_plain_build_warnings_emitted(self):
        buf = io.StringIO()
        report = BuildReport(
            resources=[ResourceOutcome(name="a", status="success", records=1)],
            total_duration_s=1.0,
            build_warnings=["S3 sync failed but continuing with local build"],
        )
        _emit_plain(report, verbose=False, console=_plain_console(buf))
        assert "WARN[build]: S3 sync failed but continuing with local build" in buf.getvalue()


def _tty_console(buffer: io.StringIO) -> Console:
    return Console(file=buffer, force_terminal=True, width=200)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class TestRichMarkupSafety:
    """User-controlled strings (skip reasons, error messages, __zeeker_report__
    keys) must be markup-escaped in TTY mode — a bracketed token must neither
    raise MarkupError (which would abort the whole build from inside the
    progress callback) nor be silently swallowed as a style tag."""

    def test_skip_reason_with_closing_tag_does_not_raise(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="pdpc",
            status="skipped",
            duration_s=1.0,
            skip_reason="proxy down [/socks5]",
            skip_kind="blocked",
        )
        render_resource_event("pdpc", outcome, console=_tty_console(buf))
        assert "proxy down [/socks5] (blocked)" in _strip_ansi(buf.getvalue())

    def test_skip_reason_with_bracketed_url_is_not_swallowed(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="pdpc",
            status="skipped",
            duration_s=1.0,
            skip_reason="proxy [socks5h://172.17.0.1:1055] unreachable",
            skip_kind="blocked",
        )
        render_resource_event("pdpc", outcome, console=_tty_console(buf))
        assert "[socks5h://172.17.0.1:1055]" in _strip_ansi(buf.getvalue())

    def test_error_message_with_brackets_does_not_raise(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="docs",
            status="failed",
            duration_s=0.4,
            error_message="RetryError[<Future raised [/ProxyError]>]",
        )
        render_resource_event("docs", outcome, console=_tty_console(buf))
        assert "RetryError[<Future raised [/ProxyError]>]" in _strip_ansi(buf.getvalue())

    def test_extra_count_keys_with_brackets_do_not_raise(self):
        buf = io.StringIO()
        outcome = ResourceOutcome(
            name="docs",
            status="success",
            records=1,
            duration_s=0.1,
            extra_counts={"[/x]": 1},
        )
        render_resource_event("docs", outcome, console=_tty_console(buf))
        assert "[/x]=1" in _strip_ansi(buf.getvalue())

    def test_emit_rich_table_and_verbose_warnings_escape_content(self):
        from zeeker.commands.helpers import _emit_rich

        buf = io.StringIO()
        report = BuildReport(
            resources=[
                ResourceOutcome(
                    name="pdpc",
                    status="skipped",
                    skip_reason="proxy down [/socks5]",
                    skip_kind="blocked",
                    extra_counts={"[/y]": 2},
                    warnings=["warn with [/tag] inside"],
                )
            ],
            total_duration_s=1.0,
            build_warnings=["build warn [/oops]"],
        )
        _emit_rich(report, verbose=True, console=_tty_console(buf))
        out = _strip_ansi(buf.getvalue())
        assert "proxy down" in out
        assert "[/tag]" in out
        assert "[/oops]" in out

    def test_emit_rich_fatal_error_with_brackets_does_not_raise(self):
        from zeeker.commands.helpers import _emit_rich

        buf = io.StringIO()
        report = BuildReport(fatal_error="Database build failed: [/boom]")
        _emit_rich(report, verbose=False, console=_tty_console(buf))
        assert "[/boom]" in _strip_ansi(buf.getvalue())

    def test_build_with_bracketed_skip_reason_is_not_fatal(self, tmp_path):
        """End-to-end: a Skip reason containing a closing-tag-like token must
        not convert the build into a fatal error via the TTY progress
        callback (builder catches callback exceptions as fatal)."""
        manager = _make_project(tmp_path, "[resource.spiky]\ndescription = 'x'\n")
        (tmp_path / "resources" / "spiky.py").write_text(
            """
from zeeker import Skip

def fetch_data(existing_table):
    raise Skip("proxy down [/socks5]", kind="blocked")
"""
        )
        buf = io.StringIO()
        console = _tty_console(buf)

        def callback(name, outcome):
            render_resource_event(name, outcome, console=console)

        result = manager.build_database(progress_callback=callback)
        assert result.is_valid, result.errors
        assert result.report.fatal_error is None
        assert result.report.resources[0].status == "skipped"


class TestSkipDoesNotAdvanceFreshnessMarker:
    """A blocked/disabled skip means 'I could not even check the source' —
    it must NOT bump _zeeker_updates.last_updated, or time-based incremental
    resources would permanently miss anything published during the outage."""

    @staticmethod
    def _last_updated(db_path: Path, resource: str) -> str | None:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT last_updated FROM _zeeker_updates WHERE resource_name = ?",
                (resource,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def _project_with_flagged_resource(self, tmp_path: Path, kind: str):
        flag = tmp_path / "skip.flag"
        manager = _make_project(tmp_path, "[resource.docs]\ndescription = 'x'\n")
        (tmp_path / "resources" / "docs.py").write_text(
            f"""
from pathlib import Path
from zeeker import Skip

FLAG = {str(flag)!r}

def fetch_data(existing_table):
    if Path(FLAG).exists():
        raise Skip("source unreachable", kind={kind!r})
    return [{{"id": 1}}]
"""
        )
        return manager, flag

    @pytest.mark.parametrize("kind", ["blocked", "disabled"])
    def test_blocked_and_disabled_skips_leave_timestamp_untouched(self, tmp_path, kind):
        manager, flag = self._project_with_flagged_resource(tmp_path, kind)
        db_path = tmp_path / "test_project.db"

        first = manager.build_database()
        assert first.is_valid, first.errors
        stamp_after_success = self._last_updated(db_path, "docs")
        assert stamp_after_success is not None

        flag.write_text("on")
        second = manager.build_database()
        assert second.is_valid, second.errors
        assert second.report.resources[0].status == "skipped"
        assert second.report.resources[0].skip_kind == kind
        assert self._last_updated(db_path, "docs") == stamp_after_success

    def test_up_to_date_skip_still_advances_timestamp(self, tmp_path):
        """An up_to_date skip means the source WAS checked — the freshness
        marker must advance, same as the legacy returned-[] behavior."""
        manager = _make_project(tmp_path, "[resource.quiet]\ndescription = 'x'\n")
        (tmp_path / "resources" / "quiet.py").write_text(
            "def fetch_data(existing_table):\n    return []\n"
        )
        db_path = tmp_path / "test_project.db"

        first = manager.build_database()
        assert first.is_valid, first.errors
        stamp = self._last_updated(db_path, "quiet")
        assert stamp is not None

        second = manager.build_database()
        assert second.is_valid, second.errors
        assert self._last_updated(db_path, "quiet") >= stamp


class TestSkipInFragmentsPhase:
    def test_skip_from_fetch_fragments_data_is_graceful(self, tmp_path):
        """Skip raised from fetch_fragments_data skips the fragments phase
        without failing the resource or the build."""
        manager = _make_project(
            tmp_path,
            """\
            [resource.enrich]
            description = "x"
            fragments = true
            """,
        )
        (tmp_path / "resources" / "enrich.py").write_text(
            """
from zeeker import Skip

def fetch_data(existing_table):
    return [{"id": 1, "title": "doc"}]

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    raise Skip("enrichment proxy down", kind="blocked")
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors
        outcome = result.report.resources[0]
        assert outcome.status == "success"
        assert outcome.records == 1
        assert not outcome.fragments_records


class TestZeekerReportLateCounters:
    def test_counters_set_in_fetch_fragments_data_are_merged(self, tmp_path):
        """Counters set by resource code that runs AFTER fetch_data (the
        fragments phase) must still reach the outcome."""
        manager = _make_project(
            tmp_path,
            """\
            [resource.backfill]
            description = "x"
            fragments = true
            fragments_on_skip = true
            """,
        )
        (tmp_path / "resources" / "backfill.py").write_text(
            """
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {"discovered": 2}
    return []

def fetch_fragments_data(existing_fragments_table, main_data_context=None):
    global __zeeker_report__
    __zeeker_report__ = {"fragments_backfilled": 4, "notes": "backfill ran"}
    return [{"id": 1, "parent_id": 1, "text": "chunk"}]
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors
        outcome = result.report.resources[0]
        assert outcome.extra_counts == {"discovered": 2, "fragments_backfilled": 4}
        assert outcome.notes == "backfill ran"
        assert outcome.fragments_records == 1

    def test_counters_set_in_transform_data_are_captured(self, tmp_path):
        manager = _make_project(tmp_path, "[resource.shaper]\ndescription = 'x'\n")
        (tmp_path / "resources" / "shaper.py").write_text(
            """
def fetch_data(existing_table):
    return [{"id": 1}]

def transform_data(data):
    global __zeeker_report__
    __zeeker_report__ = {"normalized": 1}
    return data
"""
        )

        result = manager.build_database()
        assert result.is_valid, result.errors
        assert result.report.resources[0].extra_counts == {"normalized": 1}

    def test_counters_survive_fetch_data_crash(self, tmp_path):
        """Enrichment work committed before fetch_data crashes must still be
        visible on the failed outcome (and thus the JSON payload)."""
        manager = _make_project(tmp_path, "[resource.threephase]\ndescription = 'x'\n")
        (tmp_path / "resources" / "threephase.py").write_text(
            """
def fetch_data(existing_table):
    global __zeeker_report__
    __zeeker_report__ = {"enriched": 25}
    raise ConnectionError("discovery endpoint down")
"""
        )

        result = manager.build_database()
        assert not result.is_valid
        outcome = result.report.resources[0]
        assert outcome.status == "failed"
        assert outcome.extra_counts == {"enriched": 25}

        payload = _build_report_payload(result.report)
        assert payload["resources"][0]["extra_counts"] == {"enriched": 25}
