"""Unit tests for the TTL cache and the @cached decorator."""

from pegelonline_mcp import cache


def counting(key: str):
    """A cached async function that counts how often its body runs."""
    calls = []

    @cache.cached(key)
    async def load() -> str:
        """Load something expensive."""
        calls.append(1)
        return f"value-{len(calls)}"

    return load, calls


async def test_cached_runs_function_once():
    load, calls = counting("test")

    assert await load() == "value-1"
    assert await load() == "value-1"
    assert len(calls) == 1


async def test_clear_forces_reload():
    load, calls = counting("test")

    await load()
    cache.clear()

    assert await load() == "value-2"
    assert len(calls) == 2


async def test_empty_result_is_not_cached():
    results = ["", "value"]

    @cache.cached("test")
    async def load() -> str:
        return results.pop(0)

    assert await load() == ""
    # The empty result was not cached, so the function runs again
    assert await load() == "value"
    # The non-empty result is cached; another run would fail on the empty list
    assert await load() == "value"


async def test_expired_entry_is_reloaded(monkeypatch):
    load, calls = counting("test")
    monkeypatch.setattr(cache, "CACHE_TTL_SECONDS", 0)

    await load()
    await load()

    assert len(calls) == 2


def test_cached_preserves_metadata():
    load, _ = counting("test")

    assert load.__name__ == "load"
    assert load.__doc__ == "Load something expensive."
