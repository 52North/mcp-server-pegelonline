"""Unit tests for the upstream API layer against mocked HTTP."""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError

from conftest import (
    KOELN_UUID,
    MEASUREMENTS_URL,
    SEARCH_URL,
    STATION_URL,
    TIMESERIES_URL,
    load_fixture,
)
from pegelonline_mcp import client


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


async def test_search_drops_none_params(respx_mock):
    route = respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_rhein"))

    stations = await client.search({"gewaesser": "Rhein", "land": None})

    assert dict(route.calls.last.request.url.params) == {"gewaesser": "Rhein"}
    assert len(stations) == len(load_fixture("search_rhein")["stations"])


async def test_search_without_stations_key(respx_mock):
    respx_mock.get(SEARCH_URL).respond(json={})

    assert await client.search() == []


async def test_fetch_station(respx_mock):
    route = respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln"))

    await client.fetch_station(KOELN_UUID)

    assert dict(route.calls.last.request.url.params) == {"includeTimeseries": "true"}


async def test_fetch_station_current(respx_mock):
    route = respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln_current"))

    await client.fetch_station(KOELN_UUID, current=True)

    assert dict(route.calls.last.request.url.params) == {
        "includeTimeseries": "true",
        "includeCurrentMeasurement": "true",
    }


async def test_fetch_timeseries(respx_mock):
    route = respx_mock.get(TIMESERIES_URL).respond(json=load_fixture("timeseries_koeln_w"))

    timeseries = await client.fetch_timeseries(KOELN_UUID, "W")

    assert route.called
    assert timeseries["unit"] == "cm"


@pytest.mark.parametrize(
    ("identifier", "segment"),
    [("2730010", b"2730010"), ("KÖLN", b"K%C3%96LN"), ("HAMM UW", b"HAMM%20UW")],
)
async def test_fetch_station_accepts_numbers_and_names(respx_mock, identifier, segment):
    route = respx_mock.get().respond(json={})

    await client.fetch_station(identifier)

    assert route.calls.last.request.url.raw_path.endswith(
        b"/stations/" + segment + b".json?includeTimeseries=true"
    )


async def test_path_segments_are_escaped(respx_mock):
    route = respx_mock.get().respond(json=[])

    await client.fetch_measurements_within("../../waters", "W?start=P31D#", 60)

    # The request stays below /stations/ and keeps its own query string
    assert route.calls.last.request.url.raw_path.endswith(
        b"/stations/..%2F..%2Fwaters/W%3Fstart%3DP31D%23"
        b"/measurements.json?start=PT60M"
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: client.fetch_station(".."),
        lambda: client.fetch_measurements("..", "W", 2),
        lambda: client.fetch_measurements_within(KOELN_UUID, "", 60),
        lambda: client.fetch_timeseries(KOELN_UUID, ".."),
    ],
    ids=["station", "measurements", "measurements-within", "timeseries"],
)
async def test_dot_only_segments_are_rejected(respx_mock, call):
    # Escaping leaves dots alone, so ".." would still climb up the path
    with pytest.raises(ToolError, match="Invalid station or parameter identifier"):
        await call()


async def test_fetch_measurements_most_recent_first(respx_mock):
    measurements = load_fixture("measurements_w")
    respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    recent = await client.fetch_measurements(KOELN_UUID, "W", 2)

    assert recent == [measurements[-1], measurements[-2]]


async def test_fetch_measurements_within(respx_mock):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    recent = await client.fetch_measurements_within(KOELN_UUID, "W", 1440)

    assert route.calls.last.request.url.params["start"] == "PT1440M"
    assert recent == measurements[::-1]


async def test_fetch_measurements_falls_back_to_full_history(respx_mock):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(200, json=measurements),
        ]
    )

    recent = await client.fetch_measurements(KOELN_UUID, "W", 3)

    assert route.call_count == 2
    assert route.calls[1].request.url.params["start"] == f"PT{client.HISTORY_MINUTES}M"
    assert recent == measurements[-1:-4:-1]


async def test_fetch_measurements_fallback_reaches_full_history(respx_mock):
    # An hourly series over 31 days: the window for 1000 values holds about
    # 500, and the API's 10-day default would hold even fewer.
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=fake_measurements_api(days=31, interval_minutes=60)
    )

    recent = await client.fetch_measurements(KOELN_UUID, "W", 1000)

    assert route.call_count == 2
    assert len(recent) == 31 * 24


async def test_fetch_measurements_window_capped_at_full_history(respx_mock):
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=fake_measurements_api(days=31, interval_minutes=60)
    )

    recent = await client.fetch_measurements(KOELN_UUID, "W", 5000)

    # The window already spans the full history, so no fallback follows
    assert route.call_count == 1
    assert route.calls[0].request.url.params["start"] == f"PT{client.HISTORY_MINUTES}M"
    assert len(recent) == 31 * 24
