"""Common utilities for Zeeker data projects."""

from .hashing import get_hash_id
from .jina import get_jina_reader_content
from .retry import async_retry, sync_retry

__version__ = "0.2.0"
__all__ = [
    "get_hash_id",
    "get_jina_reader_content",
    "async_retry",
    "sync_retry",
    "resource_logger",
    "ResourceLogger",
]


def __getattr__(name):
    # Lazy exports — buildlog is pure stdlib, but keep import-time work minimal.
    if name in ("resource_logger", "ResourceLogger"):
        from . import buildlog

        return getattr(buildlog, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
