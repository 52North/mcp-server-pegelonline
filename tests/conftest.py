"""Shared fixtures: in-memory MCP client, mocked upstream APIs and JSON snapshots."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from syrupy.extensions.json import JSONSnapshotExtension

from pegelonline_mcp import cache, http_client
from pegelonline_mcp.config import BASE_URL, OFFICIAL_API_URL
from pegelonline_mcp.server import mcp

FIXTURES_DIR = Path(__file__).parent / "fixtures"

KOELN_UUID = "a6ee8177-107b-47dd-bcfd-30960ccc6e9c"
SEARCH_URL = f"{BASE_URL}/search"
STATIONS_URL = f"{OFFICIAL_API_URL}/stations.json"
STATION_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}.json"
TIMESERIES_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}/W.json"
MEASUREMENTS_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}/W/measurements.json"
CHART_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}/W/measurements.png"
WATERS_URL = f"{OFFICIAL_API_URL}/waters.json"

# Nothing decodes a chart, so the PNG signature stands in for a whole image
CHART_PNG = b"\x89PNG\r\n\x1a\nchart"


def load_fixture(name: str) -> Any:
    """Load a recorded upstream API response from tests/fixtures/<name>.json."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def all_stations() -> dict:
    """Unfiltered /search response spanning several federal states."""
    rhein = load_fixture("search_rhein")
    hamburg = load_fixture("search_hamburg")
    return {
        key: rhein[key] + hamburg[key]
        for key in ("mqtttopics", "pegelonlinelinks", "stations")
    }


def fake_measurements_api(days: int, interval_minutes: int):
    """Handler mimicking the official API for a series over the last ``days``.

    Like the live API, it honours ``start=PT<n>M`` and returns only the last
    10 days without ``start``.
    """
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    series: list[dict[str, Any]] = [
        {"timestamp": (now - timedelta(minutes=age)).isoformat(), "value": 48.0}
        for age in range(days * 24 * 60 - interval_minutes, -1, -interval_minutes)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params.get("start", f"PT{10 * 24 * 60}M")
        minutes = int(start.removeprefix("PT").removesuffix("M"))
        since = now - timedelta(minutes=minutes)
        kept = [m for m in series if datetime.fromisoformat(m["timestamp"]) >= since]
        return httpx.Response(200, json=kept)

    return handler


@pytest.fixture(autouse=True)
def clear_cache():
    """Resources cache module-wide; isolate every test from the others."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Retry failed connections at once instead of waiting between attempts."""
    monkeypatch.setattr(http_client, "RETRY_DELAY_SECONDS", 0)


@pytest.fixture
async def client():
    """MCP client talking to the server over the in-memory transport."""
    async with Client(mcp) as c:
        yield c


@pytest.fixture
def snapshot_json(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)
