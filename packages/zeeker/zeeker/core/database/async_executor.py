"""
Async execution handler for Zeeker database operations.

This module handles the execution of both synchronous and asynchronous
fetch_data and fetch_fragments_data functions with automatic detection.
"""

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional

from sqlite_utils.db import Table


class AsyncExecutor:
    """Handles execution of both sync and async resource functions."""

    def __init__(self, cache_enabled: bool = True):
        """Initialize AsyncExecutor with optional fetch_data cache.

        Args:
            cache_enabled: When False, skip the shared fetch cache. Disable
                this in parallel-fetch contexts where concurrent access to
                the cache dict would race.
        """
        self._fetch_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_enabled = cache_enabled
        # One-shot overrides keyed only on resource_name, populated by the
        # builder's parallel pre-warm step. Stable across table-state changes
        # during the build so a single fetch serves schema check + insert +
        # fragments-context without re-running the user's fetch_data().
        self._prewarmed: Dict[str, List[Dict[str, Any]]] = {}

    def set_prewarmed(self, resource_name: str, data: List[Dict[str, Any]]) -> None:
        """Register a fetch result to be returned by subsequent ``call_fetch_data``
        calls for ``resource_name`` within this build."""
        self._prewarmed[resource_name] = data

    def clear_prewarmed(self) -> None:
        """Drop all pre-warmed overrides. Call between builds."""
        self._prewarmed.clear()

    def clear_fetch_cache(self) -> None:
        """Drop all cached fetch_data results. Call between builds."""
        self._fetch_cache.clear()

    def call_fetch_data(
        self, fetch_data_func: Callable, existing_table: Optional[Table], resource_name: str = None
    ) -> List[Dict[str, Any]]:
        """Call fetch_data function, handling both sync and async variants.

        Args:
            fetch_data_func: The fetch_data function from the resource module
            existing_table: sqlite-utils Table object or None
            resource_name: Name of the resource for caching (optional for backward compatibility)

        Returns:
            List[Dict[str, Any]]: The data returned by fetch_data
        """
        # Serve from the parallel pre-warm override if present.
        if resource_name and resource_name in self._prewarmed:
            return self._prewarmed[resource_name]

        # Check cache if resource_name is provided and caching is enabled.
        cache_key = (
            self._generate_cache_key(resource_name, existing_table)
            if resource_name and self._cache_enabled
            else None
        )
        if cache_key and cache_key in self._fetch_cache:
            return self._fetch_cache[cache_key]

        # Execute the function
        if inspect.iscoroutinefunction(fetch_data_func):
            result = self._run_async_function(fetch_data_func, existing_table)
        else:
            result = fetch_data_func(existing_table)

        # Cache the result if caching is active.
        if cache_key:
            self._fetch_cache[cache_key] = result

        return result

    async def acall_fetch_data(
        self,
        fetch_data_func: Callable,
        existing_table: Optional[Table],
        resource_name: str = None,
    ) -> List[Dict[str, Any]]:
        """Async variant of :meth:`call_fetch_data` for use under
        ``asyncio.gather``. Returns the data produced by ``fetch_data_func``.

        Async fetchers are awaited directly. Sync fetchers are run in the
        default ThreadPoolExecutor so they don't block the event loop and
        can run concurrently with other fetches.
        """
        cache_key = (
            self._generate_cache_key(resource_name, existing_table)
            if resource_name and self._cache_enabled
            else None
        )
        if cache_key and cache_key in self._fetch_cache:
            return self._fetch_cache[cache_key]

        if inspect.iscoroutinefunction(fetch_data_func):
            result = await fetch_data_func(existing_table)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, fetch_data_func, existing_table)

        if cache_key:
            self._fetch_cache[cache_key] = result

        return result

    def _generate_cache_key(self, resource_name: str, existing_table: Optional[Table]) -> str:
        """Generate cache key for fetch_data results.

        The key is the resource name alone — stable for the duration of a
        build. Keying on live table state (e.g. row count) would let an
        intermediate step that changes the table — such as a user-supplied
        migrate_schema() deleting rows between the schema-check fetch and
        the insert fetch — miss the cache and run fetch_data a second time
        in the same build, double-spending side effects (API budgets,
        checkpoints). The cache is cleared between builds by
        :meth:`clear_fetch_cache`.

        Args:
            resource_name: Name of the resource
            existing_table: sqlite-utils Table object or None (unused; kept
                for signature stability)

        Returns:
            Cache key string
        """
        return resource_name

    def call_fetch_fragments_data(
        self,
        fetch_fragments_func: Callable,
        existing_fragments_table: Optional[Table],
        main_data_context: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Call fetch_fragments_data function, handling both sync and async variants.

        Args:
            fetch_fragments_func: The fetch_fragments_data function from the resource module
            existing_fragments_table: sqlite-utils Table object or None
            main_data_context: Raw data from fetch_data for context passing

        Returns:
            List[Dict[str, Any]]: The fragment data returned by fetch_fragments_data
        """
        if inspect.iscoroutinefunction(fetch_fragments_func):
            # Async function - run in event loop
            return self._run_async_fragments_function(
                fetch_fragments_func, existing_fragments_table, main_data_context
            )
        else:
            # Sync function - handle signature compatibility
            sig = inspect.signature(fetch_fragments_func)
            if len(sig.parameters) >= 2:
                try:
                    # Try new signature with context
                    return fetch_fragments_func(existing_fragments_table, main_data_context)
                except TypeError:
                    # Fall back to old signature
                    return fetch_fragments_func(existing_fragments_table)
            else:
                # Old signature - single parameter
                return fetch_fragments_func(existing_fragments_table)

    def _run_async_function(
        self, async_func: Callable, existing_table: Optional[Table]
    ) -> List[Dict[str, Any]]:
        """Execute an async fetch_data function."""
        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If loop is already running, we need to run in a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, async_func(existing_table))
                return future.result()
        except RuntimeError:
            # No event loop running, create one
            return asyncio.run(async_func(existing_table))

    def _run_async_fragments_function(
        self,
        async_func: Callable,
        existing_fragments_table: Optional[Table],
        main_data_context: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute an async fetch_fragments_data function."""
        # Handle signature compatibility
        sig = inspect.signature(async_func)

        if len(sig.parameters) >= 2:
            # New signature with context
            coro = async_func(existing_fragments_table, main_data_context)
        else:
            # Old signature - single parameter
            coro = async_func(existing_fragments_table)

        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If loop is already running, we need to run in a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No event loop running, create one
            return asyncio.run(coro)
