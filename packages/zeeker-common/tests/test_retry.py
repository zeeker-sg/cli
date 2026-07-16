"""Tests for retry decorators."""

import pytest
from zeeker_common.retry import async_retry, sync_retry
from tenacity import RetryError


def _make_counter_func(decorator, fail_until=0):
    """Create a decorated function that tracks call count and fails until a threshold.

    Args:
        decorator: async_retry or sync_retry
        fail_until: number of calls that should fail before succeeding
    """
    call_count = 0

    if decorator is async_retry:

        @decorator
        async def func():
            nonlocal call_count
            call_count += 1
            if call_count <= fail_until:
                raise ValueError("Failure")
            return {"key": "value", "list": [1, 2, 3]}

    else:

        @decorator
        def func():
            nonlocal call_count
            call_count += 1
            if call_count <= fail_until:
                raise ValueError("Failure")
            return {"key": "value", "list": [1, 2, 3]}

    return func, lambda: call_count


class TestAsyncRetry:
    """Test suite for async_retry decorator."""

    @pytest.mark.anyio
    async def test_successful_first_attempt(self):
        """Test that successful function executes without retry."""
        func, get_count = _make_counter_func(async_retry, fail_until=0)
        result = await func()
        assert result == {"key": "value", "list": [1, 2, 3]}
        assert get_count() == 1

    @pytest.mark.anyio
    async def test_retry_on_failure_then_success(self):
        """Test retry behavior when function fails then succeeds."""
        func, get_count = _make_counter_func(async_retry, fail_until=2)
        result = await func()
        assert result == {"key": "value", "list": [1, 2, 3]}
        assert get_count() == 3

    @pytest.mark.anyio
    async def test_gives_up_after_max_attempts(self):
        """Test that retry gives up after maximum attempts."""
        func, get_count = _make_counter_func(async_retry, fail_until=999)
        with pytest.raises(RetryError):
            await func()
        assert get_count() == 3

    @pytest.mark.anyio
    async def test_preserves_exception_info(self):
        """Test that original exception information is preserved."""

        @async_retry
        async def raises_custom_error():
            raise ValueError("Custom error message")

        with pytest.raises(RetryError) as exc_info:
            await raises_custom_error()

        assert exc_info.value.last_attempt.failed
        original_exc = exc_info.value.last_attempt.exception()
        assert isinstance(original_exc, ValueError)
        assert "Custom error message" in str(original_exc)

    @pytest.mark.anyio
    async def test_async_with_delay(self):
        """Test that retries include wait time (basic timing test)."""
        import time

        start_time = time.time()
        func, get_count = _make_counter_func(async_retry, fail_until=2)
        await func()
        elapsed = time.time() - start_time

        assert elapsed >= 2.0
        assert get_count() == 3


class TestSyncRetry:
    """Test suite for sync_retry decorator."""

    def test_successful_first_attempt(self):
        """Test that successful function executes without retry."""
        func, get_count = _make_counter_func(sync_retry, fail_until=0)
        result = func()
        assert result == {"key": "value", "list": [1, 2, 3]}
        assert get_count() == 1

    def test_retry_on_failure_then_success(self):
        """Test retry behavior when function fails then succeeds."""
        func, get_count = _make_counter_func(sync_retry, fail_until=2)
        result = func()
        assert result == {"key": "value", "list": [1, 2, 3]}
        assert get_count() == 3

    def test_gives_up_after_max_attempts(self):
        """Test that retry gives up after maximum attempts."""
        func, get_count = _make_counter_func(sync_retry, fail_until=999)
        with pytest.raises(RetryError):
            func()
        assert get_count() == 3

    def test_different_exception_types(self):
        """Test retry behavior with different exception types."""
        call_count = 0

        @sync_retry
        def raises_different_errors():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First error")
            elif call_count == 2:
                raise RuntimeError("Second error")
            return "success"

        result = raises_different_errors()
        assert result == "success"
        assert call_count == 3

    def test_sync_with_delay(self):
        """Test that retries include wait time."""
        import time

        start_time = time.time()
        func, get_count = _make_counter_func(sync_retry, fail_until=2)
        func()
        elapsed = time.time() - start_time

        assert elapsed >= 2.0
        assert get_count() == 3


class _Skip(Exception):
    """Stand-in for zeeker.Skip (zeeker-common can't depend on zeeker).

    The retry decorators exclude by class name, so any exception class named
    ``Skip`` anywhere in the MRO must pass through without retries.
    """


_Skip.__name__ = "Skip"


class TestSkipPassesThrough:
    """zeeker.Skip is control flow, not a transient failure — the decorators
    must re-raise it immediately (no backoff, no RetryError wrapping)."""

    def test_sync_retry_does_not_retry_skip(self):
        call_count = 0

        @sync_retry
        def declares_skip():
            nonlocal call_count
            call_count += 1
            raise _Skip("proxy required")

        with pytest.raises(_Skip):
            declares_skip()
        assert call_count == 1

    @pytest.mark.anyio
    async def test_async_retry_does_not_retry_skip(self):
        call_count = 0

        @async_retry
        async def declares_skip():
            nonlocal call_count
            call_count += 1
            raise _Skip("proxy required")

        with pytest.raises(_Skip):
            await declares_skip()
        assert call_count == 1

    def test_skip_subclass_also_passes_through(self):
        class SubSkip(_Skip):
            pass

        @sync_retry
        def declares_skip():
            raise SubSkip("blocked")

        with pytest.raises(SubSkip):
            declares_skip()
