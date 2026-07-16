"""Structured, prefix-consistent logging for Zeeker resource modules.

``resource_logger(name)`` returns a tiny logger whose every output line is
prefixed with ``"{name}: "`` so multi-resource build logs stay attributable.
Informational output goes to stdout; warnings, errors, aborts, and skips go
to stderr.

If the environment variable ``ZEEKER_BUILDLOG_JSONL`` is set to a file path,
every call also appends a JSON line ``{ts, resource, level, event, message,
counts}`` to that file (best-effort — JSONL failures never raise).

Pure stdlib; no click/rich dependency.

Usage::

    from zeeker_common import resource_logger

    log = resource_logger("judgments")
    log.info("discovery starting")
    log.warn("proxy slow, retrying")
    log.done(new=3, updated=50)          # judgments: done — 3 new, 50 updated
    log.aborted("circuit breaker", failed=5)
    log.skipped("TAILSCALE_PROXY unset")

Count grammar is noun-first (``3 new, 2 skipped, 0 failed``) to match the
``done — N new, M skipped, K failed`` lines the data repos' Build Monitoring
Guides already standardized on — swapping an existing ``_echo`` helper for
``resource_logger`` must not break monitoring regexes like ``(\\d+) new``.
Underscores in count names render as spaces (``still_pending=4`` →
``4 still pending``); the JSONL sink keeps raw keys.
"""

import datetime
import json
import os
import sys

__all__ = ["ResourceLogger", "resource_logger"]

_JSONL_ENV_VAR = "ZEEKER_BUILDLOG_JSONL"


def _format_counts(counts: dict) -> str:
    """Noun-first count grammar: ``3 new, 2 skipped, 0 failed``.

    This matches the shape the downstream data repos' monitoring guides
    already parse (``done — (\\d+) new``). Underscores become spaces so
    ``still_pending=4`` renders as ``4 still pending``.
    """
    return ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items())


class ResourceLogger:
    """Small logger that prefixes every line with the resource name."""

    def __init__(self, name: str):
        self.name = name

    # -- public API ---------------------------------------------------------

    def info(self, msg: str) -> None:
        """Informational message (stdout)."""
        self._emit(msg, stream=sys.stdout, level="info", event="info")

    def warn(self, msg: str) -> None:
        """Warning message (stderr)."""
        self._emit(msg, stream=sys.stderr, level="warn", event="warn")

    def error(self, msg: str) -> None:
        """Error message (stderr)."""
        self._emit(msg, stream=sys.stderr, level="error", event="error")

    def done(self, **counts) -> None:
        """Completion marker (stdout): ``{name}: done — 3 new, 2 skipped``."""
        msg = "done"
        if counts:
            msg += f" — {_format_counts(counts)}"
        self._emit(msg, stream=sys.stdout, level="info", event="done", counts=counts)

    def aborted(self, reason: str, **counts) -> None:
        """Abort marker (stderr): ``{name}: ABORTED (reason) — 5 failed``."""
        msg = f"ABORTED ({reason})"
        if counts:
            msg += f" — {_format_counts(counts)}"
        self._emit(msg, stream=sys.stderr, level="error", event="aborted", counts=counts)

    def skipped(self, reason: str) -> None:
        """Skip marker (stderr): ``{name}: SKIPPED (reason)``."""
        msg = f"SKIPPED ({reason})"
        self._emit(msg, stream=sys.stderr, level="warn", event="skipped")

    # -- internals ----------------------------------------------------------

    def _prefix_lines(self, msg: str) -> str:
        """Prefix EVERY line of ``msg`` with ``{name}: ``, preserving any
        leading whitespace of each line (after the prefix)."""
        lines = str(msg).splitlines() or [""]
        return "\n".join(f"{self.name}: {line}" for line in lines)

    def _emit(self, msg, *, stream, level: str, event: str, counts: dict | None = None) -> None:
        try:
            stream.write(self._prefix_lines(msg) + "\n")
            stream.flush()
        except Exception:
            # Logging must never break the build.
            pass
        self._jsonl(level=level, event=event, message=str(msg), counts=counts)

    def _jsonl(self, *, level: str, event: str, message: str, counts: dict | None) -> None:
        """Best-effort JSONL sink — never raises."""
        try:
            path = os.environ.get(_JSONL_ENV_VAR)
            if not path:
                return
            record = {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "resource": self.name,
                "level": level,
                "event": event,
                "message": message,
                "counts": counts or {},
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception:
            pass


def resource_logger(name: str) -> ResourceLogger:
    """Return a :class:`ResourceLogger` for ``name``."""
    return ResourceLogger(name)
