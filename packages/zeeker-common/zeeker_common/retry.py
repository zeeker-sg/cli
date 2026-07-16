"""Retry decorators for Zeeker data fetching."""

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable(exc: BaseException) -> bool:
    """Everything is retryable except ``zeeker.Skip`` (and Skip-named shims).

    ``Skip`` is a control-flow signal ("skip this resource"), not a transient
    failure — retrying it would burn 2-10s of backoff per attempt and then
    surface a tenacity ``RetryError``, turning a declared graceful skip into a
    resource FAILURE. zeeker-common cannot import zeeker (that would invert
    the dependency), so the exclusion matches by class name across the MRO,
    which also covers locally-defined ``class Skip(Exception)`` compatibility
    shims.
    """
    return not any(cls.__name__ == "Skip" for cls in type(exc).__mro__)


# Async retry decorator with exponential backoff
async_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_retryable),
)


# Sync retry decorator with exponential backoff
sync_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_retryable),
)
