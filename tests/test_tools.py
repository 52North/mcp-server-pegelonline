"""Smoke tests for every MCP tool against mocked upstream APIs.

The structured tool results are frozen as JSON snapshots so later refactoring
steps can prove the responses stay identical.
"""

import httpx
import pytest
from fastmcp.exceptions import ToolError

from conftest import (
    KOELN_UUID,
    MEASUREMENTS_URL,
    SEARCH_URL,
    STATION_URL,
    load_fixture,
)

KOELN_LAT, KOELN_LON = 50.94, 6.96


async def test_search_stations(client, respx_mock, snapshot_json):
    route = respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_rhein"))

    result = await client.call_tool(
        "search_stations", {"gewaesser": "Rhein", "land": "Nordrhein-Westfalen"}
    )

    assert dict(route.calls.last.request.url.params) == {
        "gewaesser": "Rhein",
        "land": "Nordrhein-Westfalen",
    }
    assert result.structured_content == snapshot_json


async def test_search_stations_truncated(client, respx_mock, snapshot_json):
    respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_rhein"))

    result = await client.call_tool("search_stations", {"gewaesser": "Rhein", "limit": 2})

    data = result.structured_content
    assert data["total_matches"] == 4
    assert data["returned"] == 2
    assert data["truncated"] is True
    assert len(data["mqtttopics"]) == 2
    assert data == snapshot_json


async def test_get_station_info(client, respx_mock, snapshot_json):
    route = respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln"))

    result = await client.call_tool("get_station_info", {"uuid": KOELN_UUID})

    assert route.calls.last.request.url.params["includeTimeseries"] == "true"
    assert result.structured_content == snapshot_json


async def test_find_nearest_stations(client, respx_mock, snapshot_json):
    route = respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_rhein"))

    result = await client.call_tool(
        "find_nearest_stations",
        {"latitude": KOELN_LAT, "longitude": KOELN_LON, "radius_km": 30},
    )

    assert "bbox" in route.calls.last.request.url.params
    data = result.structured_content
    # Köln and Bonn lie within 30 km; Düsseldorf is too far, and the station
    # without coordinates is skipped.
    assert [s["longname"] for s in data["stations"]] == ["KÖLN", "BONN"]
    # Bonn's single-dict timeseries is normalized to a list
    assert len(data["stations"][1]["parameters"]) == 1
    assert data == snapshot_json


async def test_show_stations_map(client, respx_mock, snapshot_json):
    respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_rhein"))

    result = await client.call_tool(
        "show_stations_map",
        {"latitude": KOELN_LAT, "longitude": KOELN_LON, "radius_km": 50},
    )

    data = result.structured_content
    assert data["center"] == {"latitude": KOELN_LAT, "longitude": KOELN_LON}
    assert data["radius_km"] == 50
    assert data == snapshot_json


async def test_get_latest_measurements(client, respx_mock, snapshot_json):
    route = respx_mock.get(STATION_URL).respond(
        json=load_fixture("station_koeln_current")
    )

    result = await client.call_tool("get_latest_measurements", {"uuid": KOELN_UUID})

    assert route.calls.last.request.url.params["includeCurrentMeasurement"] == "true"
    assert result.structured_content == snapshot_json


async def test_get_recent_measurements(client, respx_mock, snapshot_json):
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=load_fixture("measurements_w"))

    result = await client.call_tool(
        "get_recent_measurements", {"uuid": KOELN_UUID, "parameter": "W", "count": 2}
    )

    # The time window holds enough values, so no full-history request follows
    assert route.call_count == 1
    assert route.calls.last.request.url.params["start"] == "PT60M"
    assert result.structured_content == snapshot_json


async def test_get_recent_measurements_falls_back_to_full_history(
    client, respx_mock, snapshot_json
):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=[
            httpx.Response(200, json=measurements[-3:]),
            httpx.Response(200, json=measurements),
        ]
    )

    result = await client.call_tool(
        "get_recent_measurements", {"uuid": KOELN_UUID, "parameter": "W", "count": 5}
    )

    assert route.call_count == 2
    assert route.calls[0].request.url.params["start"] == "PT150M"
    assert "start" not in route.calls[1].request.url.params
    assert len(result.structured_content["measurements"]) == 5
    assert result.structured_content == snapshot_json


async def test_upstream_404_raises_tool_error(client, respx_mock):
    respx_mock.get(STATION_URL).respond(404)

    with pytest.raises(ToolError, match="404"):
        await client.call_tool("get_station_info", {"uuid": KOELN_UUID})


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_stations", {"limit": 0}),
        ("find_nearest_stations", {"latitude": KOELN_LAT, "longitude": KOELN_LON, "limit": 0}),
        ("find_nearest_stations", {"latitude": KOELN_LAT, "longitude": KOELN_LON, "radius_km": 0}),
        ("show_stations_map", {"latitude": KOELN_LAT, "longitude": KOELN_LON, "radius_km": 0}),
        ("get_recent_measurements", {"uuid": KOELN_UUID, "parameter": "W", "count": 0}),
    ],
)
async def test_invalid_arguments_are_rejected(client, respx_mock, tool, arguments):
    # Only assert that the call fails: the message changes once validation
    # becomes declarative (refactoring step 2).
    with pytest.raises(ToolError):
        await client.call_tool(tool, arguments)
