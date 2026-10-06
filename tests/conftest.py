"""Shared fixtures: in-memory MCP client, mocked upstream APIs and JSON snapshots."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from syrupy.extensions.json import JSONSnapshotExtension

import helpers
from server import BASE_URL, OFFICIAL_API_URL, mcp

FIXTURES_DIR = Path(__file__).parent / "fixtures"

KOELN_UUID = "a6ee8177-107b-47dd-bcfd-30960ccc6e9c"
SEARCH_URL = f"{BASE_URL}/search"
STATION_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}.json"
MEASUREMENTS_URL = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}/W/measurements.json"
WATERS_URL = f"{OFFICIAL_API_URL}/waters.json"


def load_fixture(name: str) -> Any:
    """Load a recorded upstream API response from tests/fixtures/<name>.json."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clear_cache():
    """Resources cache module-wide; isolate every test from the others."""
    helpers._cache.clear()
    yield
    helpers._cache.clear()


@pytest.fixture
async def client():
    """MCP client talking to the server over the in-memory transport."""
    async with Client(mcp) as c:
        yield c


@pytest.fixture
def snapshot_json(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)
