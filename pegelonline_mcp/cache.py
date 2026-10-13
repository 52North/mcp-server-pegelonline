"""In-memory TTL cache for rarely changing upstream data."""

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("pegelonline-dict")

CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, Any]] = {}


def clear() -> None:
    """Drop all cached entries."""
    _cache.clear()


def cached[**P, T](
    key: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Cache the result of an async function under a fixed key.

    The key does not depend on the arguments, so use it only for functions
    whose result is the same for every call (e.g. parameterless resources).
    Empty results are not cached: for rarely changing data they point to an
    upstream hiccup, so the next call retries.
    """
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            entry: tuple[float, T] | None = _cache.get(key)
            if entry and time.monotonic() - entry[0] < CACHE_TTL_SECONDS:
                logger.debug("%s: served from cache", func.__name__)
                return entry[1]
            value = await func(*args, **kwargs)
            if value:
                _cache[key] = (time.monotonic(), value)
            else:
                logger.warning("%s: empty result, not cached", func.__name__)
            return value
        return wrapper
    return decorator
