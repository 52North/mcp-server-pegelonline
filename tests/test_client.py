"""Unit tests for the upstream API layer against mocked HTTP."""

from datetime import datetime, timedelta, timezone

import httpx

from pegelonline_mcp import client
from conftest import KOELN_UUID, MEASUREMENTS_URL, SEARCH_URL, STATION_URL, load_fixture


def fake_measurements_api(days: int, interval_minutes: int):
    """Handler mimicking the official API for a series over the last ``days``.

    Like the live API, it honours ``start=PT<n>M`` and returns only the last
    10 days without ``start``.
    """
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    series = [
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


async def test_fetch_measurements_most_recent_first(respx_mock):
    measurements = load_fixture("measurements_w")
    respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    recent = await client.fetch_measurements(KOELN_UUID, "W", 2)

    assert recent == [measurements[-1], measurements[-2]]


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
