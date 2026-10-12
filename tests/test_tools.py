"""Smoke tests for every MCP tool against mocked upstream APIs.

The structured tool results are frozen as JSON snapshots so later refactoring
steps can prove the responses stay identical.
"""

from datetime import datetime, timedelta, timezone

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
from pegelonline_mcp.client import HISTORY_MINUTES
from pegelonline_mcp.tools_measurements import MAX_SPAN_VALUES

KOELN_LAT, KOELN_LON = 50.94, 6.96
KOELN = {"latitude": KOELN_LAT, "longitude": KOELN_LON}
KOELN_W = {"uuid": KOELN_UUID, "parameter": "W"}


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
    assert len(data["stations"]) == 2
    assert data == snapshot_json


async def test_search_stations_is_compact(client, respx_mock):
    # Recorded land=Sachsen response, raw with alternative names and phone
    # numbers; the substring search also matched Niedersachsen and Sachsen-Anhalt.
    respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_sachsen"))

    result = await client.call_tool("search_stations", {"land": "Sachsen"})

    data = result.structured_content
    stations = data["stations"]
    # land stays, so the model can still tell the states apart
    assert [s["land"] for s in stations] == [
        "Niedersachsen", "Sachsen", "Sachsen", "Sachsen-Anhalt"
    ]
    assert not [k for s in stations for k in s if k.endswith("_alternatives")]
    assert not [s for s in stations if "voiceServiceNumber" in s]
    assert "mqtttopics" not in data
    assert "pegelonlinelinks" not in data


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


async def test_get_latest_measurements_reports_both_states(client, respx_mock):
    # The API sends "unknown" instead of omitting a state, so the known
    # NSW/HSW state must not be hidden behind it.
    data = load_fixture("station_koeln_current")
    w_series = next(ts for ts in data["timeseries"] if ts["shortname"] == "W")
    w_series["currentMeasurement"]["stateMnwMhw"] = "unknown"
    respx_mock.get(STATION_URL).respond(json=data)

    result = await client.call_tool("get_latest_measurements", {"uuid": KOELN_UUID})

    measurements = result.structured_content["measurements"]
    w = next(m for m in measurements if m["shortname"] == "W")
    assert (w["state_mnw_mhw"], w["state_nsw_hsw"]) == ("unknown", "normal")


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
    assert route.calls[1].request.url.params["start"] == f"PT{HISTORY_MINUTES}M"
    assert len(result.structured_content["measurements"]) == 5
    assert result.structured_content == snapshot_json


async def test_get_recent_measurements_by_hours(client, respx_mock):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    result = await client.call_tool(
        "get_recent_measurements",
        {"uuid": KOELN_UUID, "parameter": "W", "count": 2, "hours": 24},
    )

    # One request for the time span; count does not apply
    assert route.call_count == 1
    assert route.calls.last.request.url.params["start"] == "PT1440M"
    assert result.structured_content["measurements"] == measurements[::-1]
    assert result.structured_content["truncated"] is False


async def test_get_recent_measurements_by_hours_keeps_newest_values(client, respx_mock):
    # Two days of a 1-minute series hold more values than one response carries
    start = datetime(2026, 10, 6, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    measurements = [
        {"timestamp": (start + timedelta(minutes=i)).isoformat(), "value": 48.0}
        for i in range(2 * 24 * 60)
    ]
    respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    result = await client.call_tool("get_recent_measurements", {**KOELN_W, "hours": 48})

    data = result.structured_content
    assert (data["total_matches"], data["returned"], data["truncated"]) == (
        2 * 24 * 60, MAX_SPAN_VALUES, True
    )
    # Most recent first, so the cut drops the oldest values
    assert data["measurements"][0] == measurements[-1]
    assert data["measurements"][-1] == measurements[-MAX_SPAN_VALUES]


async def test_upstream_404_raises_tool_error(client, respx_mock):
    respx_mock.get(STATION_URL).respond(404)

    with pytest.raises(ToolError, match="404"):
        await client.call_tool("get_station_info", {"uuid": KOELN_UUID})


async def test_upstream_non_json_raises_tool_error(client, respx_mock):
    # E.g. a maintenance page delivered with status 200
    respx_mock.get(STATION_URL).respond(200, html="<html>Wartungsarbeiten</html>")

    with pytest.raises(ToolError, match="no valid JSON.*text/html"):
        await client.call_tool("get_station_info", {"uuid": KOELN_UUID})


@pytest.mark.parametrize(
    ("tool", "arguments", "argument"),
    [
        ("search_stations", {"limit": 0}, "limit"),
        ("search_stations", {"limit": 1001}, "limit"),
        ("find_nearest_stations", {**KOELN, "limit": 0}, "limit"),
        ("find_nearest_stations", {**KOELN, "radius_km": 0}, "radius_km"),
        ("find_nearest_stations", {**KOELN, "radius_km": 1001}, "radius_km"),
        ("find_nearest_stations", {**KOELN, "latitude": 95}, "latitude"),
        ("find_nearest_stations", {**KOELN, "longitude": -181}, "longitude"),
        ("show_stations_map", {**KOELN, "radius_km": 0}, "radius_km"),
        ("show_stations_map", {**KOELN, "latitude": -91}, "latitude"),
        ("get_recent_measurements", {**KOELN_W, "count": 0}, "count"),
        ("get_recent_measurements", {**KOELN_W, "count": 1001}, "count"),
        ("get_recent_measurements", {**KOELN_W, "hours": 0}, "hours"),
        ("get_recent_measurements", {**KOELN_W, "hours": 841}, "hours"),
    ],
)
async def test_invalid_arguments_are_rejected(client, respx_mock, tool, arguments, argument):
    with pytest.raises(ToolError, match=rf"validation error for call\[{tool}\]\n{argument}\n"):
        await client.call_tool(tool, arguments)


@pytest.mark.parametrize(
    ("tool", "argument", "constraint"),
    [
        ("search_stations", "limit", {"minimum": 1, "maximum": 1000}),
        ("find_nearest_stations", "limit", {"minimum": 1, "maximum": 1000}),
        ("find_nearest_stations", "radius_km", {"exclusiveMinimum": 0, "maximum": 1000}),
        ("find_nearest_stations", "latitude", {"minimum": -90, "maximum": 90}),
        ("find_nearest_stations", "longitude", {"minimum": -180, "maximum": 180}),
        ("show_stations_map", "limit", {"minimum": 1, "maximum": 1000}),
        ("show_stations_map", "radius_km", {"exclusiveMinimum": 0, "maximum": 1000}),
        ("show_stations_map", "latitude", {"minimum": -90, "maximum": 90}),
        ("show_stations_map", "longitude", {"minimum": -180, "maximum": 180}),
        ("get_recent_measurements", "count", {"minimum": 1, "maximum": 1000}),
    ],
)
async def test_constraints_in_tool_schema(client, tool, argument, constraint):
    tools = {t.name: t for t in await client.list_tools()}
    schema = tools[tool].inputSchema["properties"][argument]

    assert constraint.items() <= schema.items()


async def test_hours_constraints_in_tool_schema(client):
    tools = {t.name: t for t in await client.list_tools()}
    schema = tools["get_recent_measurements"].inputSchema["properties"]["hours"]

    # hours is optional, so its constraints sit in the non-null branch
    number = next(s for s in schema["anyOf"] if s.get("type") == "number")
    assert {"exclusiveMinimum": 0, "maximum": 840}.items() <= number.items()


async def test_tools_are_annotated_read_only(client):
    tools = await client.list_tools()

    assert {t.name for t in tools} == {
        "search_stations",
        "get_station_info",
        "find_nearest_stations",
        "show_stations_map",
        "get_latest_measurements",
        "get_recent_measurements",
    }
    for tool in tools:
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.openWorldHint is True, tool.name
