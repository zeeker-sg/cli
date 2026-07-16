"""Tests for the 'zeeker runbook' command."""

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from zeeker.cli import cli

SAMPLE_TOML = textwrap.dedent(
    """\
    [project]
    name = "test_project"
    database = "test_project.db"

    [resource.users]
    description = "User account data"
    facets = ["role", "department"]
    size = 50
    fts_fields = ["bio"]

    [resource.judgments]
    description = "Court judgments"
    fragments = true
    fragments_on_skip = true
    fts_fields = ["content_text", "summary"]
    """
)


@pytest.fixture
def runner():
    return CliRunner()


def _make_project(toml_content: str = SAMPLE_TOML) -> None:
    """Write a minimal zeeker project into the current (isolated) directory."""
    Path("zeeker.toml").write_text(toml_content)
    Path("resources").mkdir()


class TestRunbookGeneration:
    """Test basic RUNBOOK.md generation."""

    def test_generates_runbook_with_resource_facts(self, runner):
        with runner.isolated_filesystem():
            _make_project()

            result = runner.invoke(cli, ["runbook"])

            assert result.exit_code == 0
            assert "✅ Generated runbook" in result.output

            content = Path("RUNBOOK.md").read_text()
            # Project facts
            assert "RUNBOOK — test_project" in content
            assert "`test_project.db`" in content
            # Resource table rows
            assert "`users`" in content
            assert "`judgments`" in content
            assert "User account data" in content
            assert "Court judgments" in content
            # Per-resource config surfaced
            assert "`content_text`" in content
            assert "`judgments_fragments`" in content

    def test_fragments_flags_rendered(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            result = runner.invoke(cli, ["runbook"])
            assert result.exit_code == 0

            content = Path("RUNBOOK.md").read_text()
            users_row = next(line for line in content.splitlines() if "| `users` " in line)
            judgments_row = next(line for line in content.splitlines() if "| `judgments` " in line)
            assert "| no | no |" in users_row
            assert "| yes | yes |" in judgments_row

    def test_custom_output_path(self, runner):
        with runner.isolated_filesystem():
            _make_project()

            result = runner.invoke(cli, ["runbook", "--output", "docs/RUNBOOK.md"])

            assert result.exit_code == 0
            assert Path("docs/RUNBOOK.md").exists()
            assert not Path("RUNBOOK.md").exists()

    def test_todo_placeholder_sections_present(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            runner.invoke(cli, ["runbook"])

            content = Path("RUNBOOK.md").read_text()
            assert content.count("<!-- TODO: fill in -->") == 6
            for section in [
                "## What happens during a run",
                "## Environment variables",
                "## Cadence & expected yield",
                "## Failure modes & recovery",
                "## Backlog / progress queries",
                "## Escalation",
            ]:
                assert section in content

    def test_regeneration_policy_documented(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            runner.invoke(cli, ["runbook"])

            content = Path("RUNBOOK.md").read_text()
            assert "Regeneration policy" in content
            assert "Nothing is preserved on" in content


class TestRunbookOverwrite:
    """Test overwrite protection."""

    def test_refuses_overwrite_without_force(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            Path("RUNBOOK.md").write_text("hand-written content")

            result = runner.invoke(cli, ["runbook"])

            assert result.exit_code != 0
            assert "already exists" in result.output
            assert "--force" in result.output
            assert Path("RUNBOOK.md").read_text() == "hand-written content"

    def test_force_overwrites(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            Path("RUNBOOK.md").write_text("hand-written content")

            result = runner.invoke(cli, ["runbook", "--force"])

            assert result.exit_code == 0
            content = Path("RUNBOOK.md").read_text()
            assert "hand-written content" not in content
            assert "RUNBOOK — test_project" in content


class TestRunbookOutsideProject:
    """Test error handling outside a zeeker project."""

    def test_errors_outside_project(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["runbook"])

            assert result.exit_code != 0
            assert "Not in a Zeeker project directory" in result.output
            assert not Path("RUNBOOK.md").exists()


class TestRunbookStatusContract:
    """The status contract must be baked into the generated file verbatim."""

    @pytest.fixture
    def content(self, runner):
        with runner.isolated_filesystem():
            _make_project()
            result = runner.invoke(cli, ["runbook"])
            assert result.exit_code == 0
            yield Path("RUNBOOK.md").read_text()

    def test_line_grammar_documented(self, content):
        assert "[OK  ] <resource>  <N> records  (<T>s)" in content
        assert "[FAIL] <resource>  <error message>  (<T>s)" in content
        assert "[SKIP] <resource>  <reason> (<kind>)  (<T>s)" in content
        assert "[SKIP] <resource>  no data returned  (<T>s)" in content
        assert "WARN[<resource>]:" in content
        assert "WARN[build]:" in content
        assert "SUMMARY: <S> succeeded, <F> failed, <K> skipped in <T>s" in content
        assert "FTS_ERROR:" in content
        assert "FATAL:" in content

    def test_exit_codes_documented(self, content):
        assert "Exit codes" in content
        for code in ("`0`", "`1`", "`2`"):
            assert code in content
        assert "Fatal error" in content

    def test_skip_kinds_documented(self, content):
        assert "`up_to_date`" in content
        assert "`blocked`" in content
        assert "`disabled`" in content
        assert "_zeeker_updates.last_updated" in content
        assert "--fail-on-blocked" in content

    def test_enrichment_counters_documented(self, content):
        assert "__zeeker_report__" in content
        assert "extra_counts" in content
        assert "updated=50 enriched=25" in content

    def test_json_payload_fields_documented(self, content):
        for field in (
            "`status`",
            "`total_duration_s`",
            "`resources`",
            "`build_warnings`",
            "`fts_error`",
            "`fatal_error`",
            "`post_hook`",
            "`skip_reason`",
            "`skip_kind`",
            "`fragments_records`",
            "`traceback`",
            "`warnings`",
            "`notes`",
        ):
            assert field in content

    def test_command_reference_documented(self, content):
        for flag in (
            "--sync-from-s3",
            "--setup-fts",
            "--json",
            "--progress-file",
            "--fail-on-blocked",
        ):
            assert flag in content
        assert "zeeker deploy" in content
