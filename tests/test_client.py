"""Unit tests for the upstream API layer against mocked HTTP."""

import httpx

import client
from conftest import KOELN_UUID, MEASUREMENTS_URL, SEARCH_URL, STATION_URL, load_fixture


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
    assert "start" not in route.calls[1].request.url.params
    assert recent == measurements[-1:-4:-1]
