"""In-memory TTL cache for rarely changing upstream data."""

import functools
import logging
import time
from typing import Any

logger = logging.getLogger("pegelonline-dict")

CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def clear() -> None:
    """Drop all cached entries."""
    _cache.clear()


def cached(key: str):
    """Cache the result of an async function under a fixed key.

    The key does not depend on the arguments, so use it only for functions
    whose result is the same for every call (e.g. parameterless resources).
    Empty results are not cached: for rarely changing data they point to an
    upstream hiccup, so the next call retries.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            value = cache_get(key)
            if value is not None:
                logger.debug("%s: served from cache", func.__name__)
                return value
            value = await func(*args, **kwargs)
            if value:
                cache_set(key, value)
            else:
                logger.warning("%s: empty result, not cached", func.__name__)
            return value
        return wrapper
    return decorator
