"""Tests for zeeker_common.buildlog (resource_logger)."""

import json

import pytest

from zeeker_common import resource_logger
from zeeker_common.buildlog import ResourceLogger


def test_lazy_export_from_package_init():
    import zeeker_common

    assert zeeker_common.resource_logger is resource_logger
    assert zeeker_common.ResourceLogger is ResourceLogger
    with pytest.raises(AttributeError):
        zeeker_common.does_not_exist


def test_info_goes_to_stdout_with_prefix(capsys):
    log = resource_logger("judgments")
    log.info("discovery starting")
    captured = capsys.readouterr()
    assert captured.out == "judgments: discovery starting\n"
    assert captured.err == ""


def test_warn_and_error_go_to_stderr(capsys):
    log = resource_logger("judgments")
    log.warn("proxy slow")
    log.error("boom")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "judgments: proxy slow\n" in captured.err
    assert "judgments: boom\n" in captured.err


def test_multiline_message_prefixes_every_line_preserving_whitespace(capsys):
    log = resource_logger("res")
    log.info("first\n  indented\nlast")
    captured = capsys.readouterr()
    assert captured.out == "res: first\nres:   indented\nres: last\n"


def test_done_with_counts_uses_noun_first_grammar(capsys):
    """Count grammar must match the data repos' adopted monitoring shape:
    'done — 3 new, 2 skipped, 0 failed' (parsed by regexes like '(\\d+) new')."""
    log = resource_logger("judgments")
    log.done(new=3, updated=50)
    captured = capsys.readouterr()
    assert captured.out == "judgments: done — 3 new, 50 updated\n"
    assert captured.err == ""


def test_done_counts_render_underscores_as_spaces(capsys):
    log = resource_logger("pdpc")
    log.done(ok=4, still_pending=2)
    captured = capsys.readouterr()
    assert captured.out == "pdpc: done — 4 ok, 2 still pending\n"


def test_done_without_counts(capsys):
    log = resource_logger("judgments")
    log.done()
    captured = capsys.readouterr()
    assert captured.out == "judgments: done\n"


def test_aborted_with_counts_goes_to_stderr(capsys):
    log = resource_logger("pdpc")
    log.aborted("circuit breaker", failed=5, ok=2)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pdpc: ABORTED (circuit breaker) — 5 failed, 2 ok\n"


def test_aborted_without_counts(capsys):
    log = resource_logger("pdpc")
    log.aborted("circuit breaker")
    captured = capsys.readouterr()
    assert captured.err == "pdpc: ABORTED (circuit breaker)\n"


def test_skipped_goes_to_stderr(capsys):
    log = resource_logger("pdpc")
    log.skipped("TAILSCALE_PROXY unset")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pdpc: SKIPPED (TAILSCALE_PROXY unset)\n"


def test_jsonl_sink_appends_records(tmp_path, monkeypatch, capsys):
    jsonl = tmp_path / "build.jsonl"
    monkeypatch.setenv("ZEEKER_BUILDLOG_JSONL", str(jsonl))

    log = resource_logger("judgments")
    log.info("starting")
    log.done(updated=50)
    log.skipped("nothing new")
    capsys.readouterr()  # drain stream output

    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]

    assert records[0]["resource"] == "judgments"
    assert records[0]["level"] == "info"
    assert records[0]["event"] == "info"
    assert records[0]["message"] == "starting"
    assert records[0]["counts"] == {}
    assert "ts" in records[0]

    assert records[1]["event"] == "done"
    assert records[1]["counts"] == {"updated": 50}

    assert records[2]["event"] == "skipped"
    assert records[2]["level"] == "warn"


def test_jsonl_disabled_when_env_unset(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ZEEKER_BUILDLOG_JSONL", raising=False)
    log = resource_logger("res")
    log.info("hello")
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []


def test_jsonl_failure_never_raises(tmp_path, monkeypatch, capsys):
    # Point the sink at a directory — open(..., "a") fails, but the logger
    # must swallow it and still emit the stream line.
    monkeypatch.setenv("ZEEKER_BUILDLOG_JSONL", str(tmp_path))
    log = resource_logger("res")
    log.info("still works")
    log.done(x=1)
    captured = capsys.readouterr()
    assert "res: still works\n" in captured.out
    assert "res: done — 1 x\n" in captured.out


def test_jsonl_handles_non_serializable_counts(tmp_path, monkeypatch, capsys):
    jsonl = tmp_path / "log.jsonl"
    monkeypatch.setenv("ZEEKER_BUILDLOG_JSONL", str(jsonl))
    log = resource_logger("res")
    log.done(when=object())  # default=str fallback
    capsys.readouterr()
    record = json.loads(jsonl.read_text().strip())
    assert record["event"] == "done"
    assert "when" in record["counts"]
