"""Smoke tests for every MCP tool against mocked upstream APIs.

The structured tool results are frozen as JSON snapshots so later refactoring
steps can prove the responses stay identical.
"""

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastmcp.exceptions import ToolError
from mcp.types import ImageContent

from conftest import (
    CHART_PNG,
    CHART_URL,
    KOELN_UUID,
    MEASUREMENTS_URL,
    SEARCH_URL,
    STATION_URL,
    TIMESERIES_URL,
    fake_measurements_api,
    load_fixture,
)
from pegelonline_mcp.client import HISTORY_MINUTES
from pegelonline_mcp.config import OFFICIAL_API_URL
from pegelonline_mcp.tools_measurements import MAX_RAW_SLOTS, MAX_RESULT_CHARS

KOELN_LAT, KOELN_LON = 50.94, 6.96
KOELN = {"latitude": KOELN_LAT, "longitude": KOELN_LON}
KOELN_W = {"uuid": KOELN_UUID, "parameter": "W"}

BERLIN = ZoneInfo("Europe/Berlin")
# A time window may start at most 35 days back, so windows follow the clock
NOW = datetime.now(UTC).replace(microsecond=0)
START = (NOW - timedelta(days=2)).astimezone(BERLIN)
END = START + timedelta(hours=6)

# Tools that take a time window, by hours or by start and end
WINDOW_TOOLS = ["get_measurement_history", "get_measurements_chart"]
# Window arguments and the query parameters the API receives for them:
# hours counts back from the API's now, a window is sent as given
WINDOW_PARAMS = [
    pytest.param({"hours": 1.5}, {"start": "PT90M"}, id="hours"),
    pytest.param({"start": START.isoformat()}, {"start": START.isoformat()}, id="start"),
    pytest.param(
        {"start": START.isoformat(), "end": END.isoformat()},
        {"start": START.isoformat(), "end": END.isoformat()},
        id="start-end",
    ),
]
CHART_SIZE = {"width": "900", "height": "400"}


@pytest.fixture
def timeseries_w(respx_mock):
    """Köln W metadata, which get_recent_measurements fetches before the values."""
    return respx_mock.get(TIMESERIES_URL).respond(json=load_fixture("timeseries_koeln_w"))


@pytest.fixture
def three_days_of_minutes(respx_mock):
    """Köln W as a 1-minute series over three days: 433 rows of 10 minutes."""
    respx_mock.get(TIMESERIES_URL).respond(
        json=load_fixture("timeseries_koeln_w") | {"equidistance": 1}
    )
    respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=fake_measurements_api(days=3, interval_minutes=1)
    )


def series(
    first: datetime, values: list[float | None], interval_minutes: int = 15
) -> list[dict[str, Any]]:
    """Measurements every ``interval_minutes`` from ``first`` on, in German time.

    ``first`` is in UTC, so the steps also cross a change of daylight saving
    time evenly. A None value leaves a gap.
    """
    return [
        {
            "timestamp": (first + timedelta(minutes=i * interval_minutes))
            .astimezone(BERLIN)
            .isoformat(),
            "value": value,
        }
        for i, value in enumerate(values)
        if value is not None
    ]


def mock_history(respx_mock, measurements: list[dict[str, Any]], **timeseries: Any):
    """Mock Köln W with ``measurements``; ``timeseries`` overrides its metadata."""
    respx_mock.get(TIMESERIES_URL).respond(
        json=load_fixture("timeseries_koeln_w") | timeseries
    )
    respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)


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


async def test_search_stations_tolerates_missing_fields(client, respx_mock):
    # Live, some stations lack a district, catchment area or state. The server
    # validates every response against the output schema, so the schema has to
    # allow that or the whole call fails.
    data = load_fixture("search_rhein")
    for key in ("kreis", "einzugsgebiet", "land", "water", "mqtttopic"):
        del data["stations"][0][key]
    respx_mock.get(SEARCH_URL).respond(json=data)

    result = await client.call_tool("search_stations", {"gewaesser": "Rhein"})

    station = result.structured_content["stations"][0]
    for key in ("kreis", "einzugsgebiet", "land", "water", "mqtttopic"):
        assert station[key] is None, key


async def test_get_station_info(client, respx_mock, snapshot_json):
    route = respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln"))

    result = await client.call_tool("get_station_info", {"uuid": KOELN_UUID})

    assert route.calls.last.request.url.params["includeTimeseries"] == "true"
    assert result.structured_content == snapshot_json


async def test_get_station_info_tolerates_missing_fields(client, respx_mock):
    # Live, some stations lack coordinates or a river kilometer
    station = load_fixture("station_koeln")
    for key in ("km", "latitude", "longitude", "water"):
        del station[key]
    for ts in station["timeseries"]:
        for key in ("equidistance", "gaugeZero", "comment"):
            ts.pop(key, None)
    respx_mock.get(STATION_URL).respond(json=station)

    result = await client.call_tool("get_station_info", {"uuid": KOELN_UUID})

    data = result.structured_content
    for key in ("km", "latitude", "longitude", "water"):
        assert data[key] is None, key
    for parameter in data["parameters"]:
        for key in ("equidistance_minutes", "gaugeZero", "comment"):
            assert parameter[key] is None, key


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


async def test_get_characteristic_values(client, respx_mock, snapshot_json):
    route = respx_mock.get(TIMESERIES_URL).respond(
        json=load_fixture("timeseries_koeln_w_characteristic")
    )

    # W by default: only water levels have characteristic values
    result = await client.call_tool("get_characteristic_values", {"uuid": KOELN_UUID})

    # Current value and characteristic values come in a single request
    assert dict(route.calls.last.request.url.params) == {
        "includeCurrentMeasurement": "true",
        "includeCharacteristicValues": "true",
    }
    assert result.structured_content == snapshot_json


async def test_get_characteristic_values_without_values(client, respx_mock):
    # Recorded Köln Q: no characteristic values, here also no current value
    station = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}"
    respx_mock.get(f"{station}/Q.json").respond(json=load_fixture("timeseries_koeln_q"))

    result = await client.call_tool(
        "get_characteristic_values", {"uuid": KOELN_UUID, "parameter": "Q"}
    )

    data = result.structured_content
    assert data["characteristic_values"] == []
    assert data["current"] is None
    assert data["unit"] == "m³/s"
    assert data["comment"] == "Abflussermittlung unter W = 50cm aktuell nicht möglich"


async def test_get_characteristic_values_tolerates_missing_fields(client, respx_mock):
    timeseries = load_fixture("timeseries_koeln_w_characteristic")
    del timeseries["unit"]
    for key in ("stateMnwMhw", "stateNswHsw"):
        del timeseries["currentMeasurement"][key]
    for cv in timeseries["characteristicValues"]:
        for key in ("longname", "unit", "value"):
            del cv[key]
    respx_mock.get(TIMESERIES_URL).respond(json=timeseries)

    result = await client.call_tool("get_characteristic_values", KOELN_W)

    data = result.structured_content
    assert data["unit"] is None
    assert data["current"]["state_mnw_mhw"] is None
    for cv in data["characteristic_values"]:
        for key in ("longname", "unit", "value"):
            assert cv[key] is None, key


async def test_get_recent_measurements(client, respx_mock, timeseries_w, snapshot_json):
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=load_fixture("measurements_w"))

    result = await client.call_tool(
        "get_recent_measurements", {"uuid": KOELN_UUID, "parameter": "W", "count": 2}
    )

    # The time window holds enough values, so no full-history request follows
    assert route.call_count == 1
    assert route.calls.last.request.url.params["start"] == "PT60M"
    assert result.structured_content == snapshot_json


async def test_get_recent_measurements_falls_back_to_full_history(
    client, respx_mock, timeseries_w, snapshot_json
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


async def test_get_recent_measurements_window_follows_interval(client, respx_mock):
    # A 1-minute series: the window covers 200 minutes, not 100 × 30
    timeseries = load_fixture("timeseries_koeln_w") | {"equidistance": 1}
    respx_mock.get(TIMESERIES_URL).respond(json=timeseries)
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=fake_measurements_api(days=3, interval_minutes=1)
    )

    result = await client.call_tool("get_recent_measurements", {**KOELN_W, "count": 100})

    assert route.call_count == 1
    assert route.calls.last.request.url.params["start"] == "PT200M"
    measurements = result.structured_content["measurements"]
    assert len(measurements) == 100
    assert measurements[0]["timestamp"] > measurements[-1]["timestamp"]


async def test_get_recent_measurements_reports_unit_and_comment(client, respx_mock):
    # Recorded Köln Q: its unit is not cm, and the timeseries carries a comment
    station = f"{OFFICIAL_API_URL}/stations/{KOELN_UUID}"
    respx_mock.get(f"{station}/Q.json").respond(json=load_fixture("timeseries_koeln_q"))
    respx_mock.get(f"{station}/Q/measurements.json").respond(
        json=[{"timestamp": "2026-10-06T09:45:00+02:00", "value": 577.0}]
    )

    result = await client.call_tool(
        "get_recent_measurements", {"uuid": KOELN_UUID, "parameter": "Q", "count": 1}
    )

    data = result.structured_content
    assert data["unit"] == "m³/s"
    assert data["comment"] == "Abflussermittlung unter W = 50cm aktuell nicht möglich"
    assert [m["value"] for m in data["measurements"]] == [577.0]


async def test_get_measurement_history(client, respx_mock, timeseries_w, snapshot_json):
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=load_fixture("measurements_w"))

    result = await client.call_tool("get_measurement_history", KOELN_W)

    # The last 24 hours by default
    assert dict(route.calls.last.request.url.params) == {"start": "PT1440M"}
    assert result.structured_content == snapshot_json


@pytest.mark.parametrize(("window", "params"), WINDOW_PARAMS)
async def test_get_measurement_history_requests_window(
    client, respx_mock, timeseries_w, window, params
):
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=[])

    await client.call_tool("get_measurement_history", {**KOELN_W, **window})

    assert dict(route.calls.last.request.url.params) == params


@pytest.mark.parametrize(
    ("window", "message"),
    [
        ({"hours": 24, "start": START.isoformat()}, "either hours or start"),
        ({"end": END.isoformat()}, "end needs start"),
        ({"start": END.isoformat(), "end": START.isoformat()}, "before end"),
        ({"start": (NOW + timedelta(hours=1)).isoformat()}, "before end"),
        ({"start": (NOW - timedelta(days=36)).isoformat()}, "a little over 31 days"),
        (
            {"start": START.isoformat(), "end": (NOW + timedelta(days=34)).isoformat()},
            "at most 840 hours apart",
        ),
    ],
    ids=[
        "hours-and-start", "end-without-start", "end-before-start",
        "start-in-future", "start-too-old", "window-too-long",
    ],
)
@pytest.mark.parametrize("tool", WINDOW_TOOLS)
async def test_invalid_time_windows_are_rejected(client, respx_mock, tool, window, message):
    # Rejected before any upstream request, which respx would refuse unmocked
    with pytest.raises(ToolError, match=message):
        await client.call_tool(tool, {**KOELN_W, **window})


async def test_get_measurement_history_marks_gaps(client, respx_mock):
    # 12:30 and the whole hour from 13:00 are missing
    mock_history(respx_mock, series(
        datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
        [50.0, 50.5, None, 51.0, None, None, None, None, 52.0, 52.0, 52.0, 52.0],
    ))

    result = await client.call_tool("get_measurement_history", KOELN_W)

    data = result.structured_content
    assert (data["resolution"], data["columns"]) == ("raw", ["+0", "+15", "+30", "+45"])
    assert data["rows"] == {
        "2026-10-06T12:00+02:00": [50, 50.5, None, 51],
        "2026-10-06T14:00+02:00": [52, 52, 52, 52],
    }
    assert (data["summary"]["count"], data["summary"]["missing"]) == (7, 5)


async def test_get_measurement_history_names_repeated_hour_by_offset(client, respx_mock):
    # On 25 October 2026 the clocks go back from 03:00 CEST to 02:00 CET
    mock_history(respx_mock, series(datetime(2026, 10, 24, 23, 0, tzinfo=UTC), [48.0] * 16))

    result = await client.call_tool("get_measurement_history", KOELN_W)

    data = result.structured_content
    assert list(data["rows"]) == [
        "2026-10-25T01:00+02:00",
        "2026-10-25T02:00+02:00",
        "2026-10-25T02:00+01:00",
        "2026-10-25T03:00+01:00",
    ]
    assert data["summary"]["missing"] == 0


async def test_get_measurement_history_minute_series_in_rows_of_ten(client, respx_mock):
    # 12:03 to 12:27, each value the minute it was measured
    mock_history(
        respx_mock,
        series(
            datetime(2026, 10, 6, 10, 3, tzinfo=UTC),
            [float(minute) for minute in range(3, 28)],
            interval_minutes=1,
        ),
        equidistance=1,
    )

    result = await client.call_tool("get_measurement_history", KOELN_W)

    data = result.structured_content
    assert data["columns"] == [f"+{minute}" for minute in range(10)]
    # The slot is the last digit of the minute
    assert data["rows"] == {
        "2026-10-06T12:00+02:00": [None, None, None, 3, 4, 5, 6, 7, 8, 9],
        "2026-10-06T12:10+02:00": list(range(10, 20)),
        "2026-10-06T12:20+02:00": [20, 21, 22, 23, 24, 25, 26, 27, None, None],
    }


async def test_get_measurement_history_auto_summarizes_per_hour(
    client, three_days_of_minutes
):
    result = await client.call_tool("get_measurement_history", {**KOELN_W, "hours": 72})

    data = result.structured_content
    assert (data["resolution"], data["truncated"]) == ("hour", False)
    assert data["columns"] == ["min", "mean", "max"]
    assert len(data["rows"]) == 73
    assert data["rows"]["2026-10-08T12:00+02:00"] == [48, 48, 48]
    assert data["summary"]["count"] == 3 * 24 * 60


async def test_get_measurement_history_raw_keeps_newest_rows(client, three_days_of_minutes):
    result = await client.call_tool(
        "get_measurement_history", {**KOELN_W, "hours": 72, "resolution": "raw"}
    )

    data = result.structured_content
    assert (data["resolution"], data["truncated"]) == ("raw", True)
    rows = list(data["rows"])
    assert len(rows) == MAX_RAW_SLOTS // 10
    assert (rows[0], rows[-1]) == ("2026-10-06T04:10+02:00", "2026-10-08T12:00+02:00")
    # The summary still covers every value
    assert data["summary"]["count"] == 3 * 24 * 60


async def test_get_measurement_history_by_day(client, respx_mock):
    # Hourly from 22:00 to 02:00 the next day
    mock_history(
        respx_mock,
        series(
            datetime(2026, 10, 6, 20, 0, tzinfo=UTC),
            [1.0, 2.0, 1.0, 1.0, 2.0],
            interval_minutes=60,
        ),
        equidistance=60,
    )

    result = await client.call_tool(
        "get_measurement_history", {**KOELN_W, "resolution": "day"}
    )

    data = result.structured_content
    assert (data["resolution"], data["columns"]) == ("day", ["min", "mean", "max"])
    assert data["rows"] == {"2026-10-06": [1, 1.5, 2], "2026-10-07": [1, 1.33, 2]}


async def test_get_measurement_history_summary(client, respx_mock):
    mock_history(respx_mock, series(
        datetime(2026, 10, 6, 10, 0, tzinfo=UTC), [3.0, 1.0, 5.0, 1.0, 5.0, 2.0]
    ))

    result = await client.call_tool("get_measurement_history", KOELN_W)

    # The earliest of equal extremes counts; mean is rounded to two decimals
    assert result.structured_content["summary"] == {
        "count": 6,
        "missing": 0,
        "first": {"timestamp": "2026-10-06T12:00:00+02:00", "value": 3},
        "last": {"timestamp": "2026-10-06T13:15:00+02:00", "value": 2},
        "min": {"timestamp": "2026-10-06T12:15:00+02:00", "value": 1},
        "max": {"timestamp": "2026-10-06T12:30:00+02:00", "value": 5},
        "mean": 2.83,
    }


async def test_get_measurement_history_without_values(client, respx_mock):
    # E.g. a window before the kept history
    mock_history(respx_mock, [])

    result = await client.call_tool("get_measurement_history", KOELN_W)

    data = result.structured_content
    assert data["summary"] == {
        "count": 0, "missing": None, "first": None, "last": None,
        "min": None, "max": None, "mean": None,
    }
    assert data["rows"] == {}


@pytest.mark.parametrize(
    ("first", "timeseries"),
    [
        (datetime(2026, 10, 6, 10, 0, tzinfo=UTC), {"equidistance": None}),
        (datetime(2026, 10, 6, 10, 7, tzinfo=UTC), {}),
    ],
    ids=["unknown-interval", "off-grid"],
)
async def test_get_measurement_history_without_grid_summarizes_per_hour(
    client, respx_mock, first, timeseries
):
    mock_history(respx_mock, series(first, [48.0] * 3), **timeseries)

    result = await client.call_tool(
        "get_measurement_history", {**KOELN_W, "resolution": "raw"}
    )

    data = result.structured_content
    assert (data["resolution"], data["truncated"]) == ("hour", False)
    assert data["rows"] == {"2026-10-06T12:00+02:00": [48, 48, 48]}
    assert data["summary"]["missing"] is None


async def test_get_measurements_chart(client, respx_mock):
    # Only the chart is mocked, and respx refuses any other request: the tool
    # fetches no timeseries metadata first
    route = respx_mock.get(CHART_URL).respond(content=CHART_PNG, content_type="image/png")

    result = await client.call_tool("get_measurements_chart", KOELN_W)

    # The last 24 hours by default
    assert dict(route.calls.last.request.url.params) == {"start": "PT1440M", **CHART_SIZE}
    assert result.content == [
        ImageContent(
            type="image", data=base64.b64encode(CHART_PNG).decode(), mimeType="image/png"
        )
    ]
    assert result.structured_content is None


@pytest.mark.parametrize(("window", "params"), WINDOW_PARAMS)
async def test_get_measurements_chart_requests_window(client, respx_mock, window, params):
    route = respx_mock.get(CHART_URL).respond(content=CHART_PNG, content_type="image/png")

    await client.call_tool("get_measurements_chart", {**KOELN_W, **window})

    assert dict(route.calls.last.request.url.params) == params | CHART_SIZE


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(404, json={"status": 404, "message": "Timeseries does not exist."}),
            "check that the station UUID",
        ),
        # E.g. a maintenance page delivered with status 200
        (httpx.Response(200, html="<html>Wartungsarbeiten</html>"), "no PNG image.*text/html"),
    ],
    ids=["unknown-parameter", "no-png"],
)
async def test_get_measurements_chart_upstream_errors(client, respx_mock, response, message):
    respx_mock.get(CHART_URL).mock(return_value=response)

    with pytest.raises(ToolError, match=message):
        await client.call_tool("get_measurements_chart", KOELN_W)


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
    ("mock", "message"),
    [
        ({"return_value": httpx.Response(503)}, "HTTP 503"),
        ({"side_effect": httpx.ReadTimeout("read timed out")}, "timed out"),
        ({"side_effect": httpx.ConnectError("connection refused")},
         "Could not reach upstream API"),
    ],
    ids=["server-error", "timeout", "connection-error"],
)
async def test_upstream_failures_raise_tool_error(client, respx_mock, mock, message):
    respx_mock.get(STATION_URL).mock(**mock)

    with pytest.raises(ToolError, match=message):
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
        ("get_recent_measurements", {**KOELN_W, "count": 101}, "count"),
        # Time spans moved to get_measurement_history; hours is not ignored
        ("get_recent_measurements", {**KOELN_W, "hours": 24}, "hours"),
        ("get_measurement_history", {**KOELN_W, "hours": 0}, "hours"),
        ("get_measurement_history", {**KOELN_W, "hours": 841}, "hours"),
        # Without an offset, the time is ambiguous
        ("get_measurement_history", {**KOELN_W, "start": "2026-09-20T00:00"}, "start"),
        ("get_measurement_history", {**KOELN_W, "resolution": "minute"}, "resolution"),
        ("get_measurements_chart", {**KOELN_W, "hours": 841}, "hours"),
        ("get_measurements_chart", {**KOELN_W, "start": "2026-09-20T00:00"}, "start"),
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
        ("get_recent_measurements", "count", {"minimum": 1, "maximum": 100}),
    ],
)
async def test_constraints_in_tool_schema(client, tool, argument, constraint):
    tools = {t.name: t for t in await client.list_tools()}
    schema = tools[tool].inputSchema["properties"][argument]

    assert constraint.items() <= schema.items()


@pytest.mark.parametrize("tool", WINDOW_TOOLS)
async def test_hours_constraints_in_tool_schema(client, tool):
    tools = {t.name: t for t in await client.list_tools()}
    schema = tools[tool].inputSchema["properties"]["hours"]

    # hours is optional, so its constraints sit in the non-null branch
    number = next(s for s in schema["anyOf"] if s.get("type") == "number")
    assert {"exclusiveMinimum": 0, "maximum": 840}.items() <= number.items()


@pytest.mark.parametrize("tool", WINDOW_TOOLS)
async def test_window_in_tool_schema(client, tool):
    tools = {t.name: t for t in await client.list_tools()}
    properties = tools[tool].inputSchema["properties"]

    for argument in ("start", "end"):
        assert {"type": "string", "format": "date-time"} in properties[argument]["anyOf"]


async def test_resolution_in_tool_schema(client):
    tools = {t.name: t for t in await client.list_tools()}
    schema = tools["get_measurement_history"].inputSchema["properties"]["resolution"]

    assert schema["enum"] == ["auto", "raw", "hour", "day"]


async def test_history_allows_large_results(client):
    tools = {t.name: t for t in await client.list_tools()}

    # Claude Code reads the allowance from the tool's _meta in tools/list
    meta = tools["get_measurement_history"].meta
    assert meta["anthropic/maxResultSizeChars"] == MAX_RESULT_CHARS


@pytest.mark.parametrize(
    ("tool", "properties"),
    [
        ("search_stations", {"total_matches", "returned", "truncated", "stations"}),
        (
            "get_station_info",
            {
                "uuid", "number", "shortname", "longname", "agency",
                "longitude", "latitude", "km", "water", "parameters",
            },
        ),
        ("find_nearest_stations", {"total_matches", "returned", "truncated", "stations"}),
        (
            "show_stations_map",
            {"center", "radius_km", "total_matches", "returned", "truncated", "stations"},
        ),
        ("get_latest_measurements", {"station", "water", "measurements"}),
        (
            "get_characteristic_values",
            {"uuid", "parameter", "unit", "comment", "current", "characteristic_values"},
        ),
        (
            "get_recent_measurements",
            {"uuid", "parameter", "unit", "comment", "measurements"},
        ),
        (
            "get_measurement_history",
            {
                "uuid", "parameter", "unit", "comment", "interval_minutes",
                "summary", "resolution", "truncated", "columns", "rows",
            },
        ),
    ],
)
async def test_output_schema_describes_response(client, tool, properties):
    # A plain dict return type would publish only an open object schema
    tools = {t.name: t for t in await client.list_tools()}

    assert set(tools[tool].outputSchema["properties"]) == properties


async def test_chart_has_no_output_schema(client):
    tools = {t.name: t for t in await client.list_tools()}

    # It returns image content, not structured data
    assert tools["get_measurements_chart"].outputSchema is None


async def test_tools_are_annotated_read_only(client):
    tools = await client.list_tools()

    assert {t.name for t in tools} == {
        "search_stations",
        "get_station_info",
        "find_nearest_stations",
        "show_stations_map",
        "get_latest_measurements",
        "get_characteristic_values",
        "get_recent_measurements",
        "get_measurement_history",
        "get_measurements_chart",
    }
    for tool in tools:
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.openWorldHint is True, tool.name
