"""Unit tests for the upstream API layer against mocked HTTP."""

import logging
from datetime import datetime, timedelta, timezone

import httpx2
import pytest
from fastmcp.exceptions import ToolError

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
from pegelonline_mcp import client
from pegelonline_mcp.config import OFFICIAL_API_URL

CEST = timezone(timedelta(hours=2))


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

    assert dict(route.calls.last.request.url.params) == {}
    assert timeseries["unit"] == "cm"


async def test_fetch_timeseries_current_and_characteristic_values(respx_mock):
    route = respx_mock.get(TIMESERIES_URL).respond(
        json=load_fixture("timeseries_koeln_w_characteristic")
    )

    await client.fetch_timeseries(
        KOELN_UUID, "W", current=True, characteristic_values=True
    )

    assert dict(route.calls.last.request.url.params) == {
        "includeCurrentMeasurement": "true",
        "includeCharacteristicValues": "true",
    }


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

    await client.fetch_measurements_since(
        "../../waters", "W?start=P31D#", timedelta(minutes=60)
    )

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
        lambda: client.fetch_measurements_since(KOELN_UUID, "", timedelta(hours=1)),
        lambda: client.fetch_measurements_chart("..", "W", timedelta(hours=1)),
        lambda: client.fetch_timeseries(KOELN_UUID, ".."),
    ],
    ids=["station", "measurements", "measurements-since", "chart", "timeseries"],
)
async def test_dot_only_segments_are_rejected(respx_mock, call):
    # Escaping leaves dots alone, so ".." would still climb up the path
    with pytest.raises(ToolError, match="Invalid station or parameter identifier") as exc:
        await call()
    # The caller's mistake, not a failure of the server
    assert exc.value.log_level == logging.WARNING


# The official API's 404 for the timeseries of an unknown station or parameter
TIMESERIES_404 = httpx2.Response(
    404, json={"status": 404, "message": "Timeseries does not exist."}
)
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"
# The requests for a station parameter, which answer both cases alike
PARAMETER_CALLS = [
    pytest.param(
        lambda uuid, parameter: client.fetch_timeseries(uuid, parameter),
        id="timeseries",
    ),
    pytest.param(
        lambda uuid, parameter: client.fetch_measurements_chart(
            uuid, parameter, timedelta(hours=24)
        ),
        id="chart",
    ),
]


def parameter_urls(uuid: str, parameter: str) -> str:
    """Start of the URLs of a station parameter: its metadata and its chart."""
    return f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}"


@pytest.mark.parametrize("call", PARAMETER_CALLS)
async def test_unknown_parameter_names_those_of_the_station(respx_mock, call):
    respx_mock.get(url__startswith=parameter_urls(KOELN_UUID, "LT")).mock(
        return_value=TIMESERIES_404
    )
    station = respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln"))

    with pytest.raises(
        ToolError, match=f"Station {KOELN_UUID} has no parameter 'LT'; it has Q, W"
    ) as exc:
        await call(KOELN_UUID, "LT")
    assert station.called
    assert exc.value.log_level == logging.WARNING


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda uuid, parameter: client.fetch_station(uuid), id="station"),
        *PARAMETER_CALLS,
    ],
)
async def test_unknown_station(respx_mock, call):
    respx_mock.get(url__startswith=parameter_urls(UNKNOWN_UUID, "W")).mock(
        return_value=TIMESERIES_404
    )
    respx_mock.get(f"{OFFICIAL_API_URL}/stations/{UNKNOWN_UUID}.json").respond(
        404, json={"status": 404, "message": "Station does not exist."}
    )

    with pytest.raises(ToolError, match=f"Unknown station '{UNKNOWN_UUID}'") as exc:
        await call(UNKNOWN_UUID, "W")
    assert exc.value.log_level == logging.WARNING


@pytest.mark.parametrize("call", PARAMETER_CALLS)
async def test_404_stays_if_the_station_has_the_parameter(respx_mock, call):
    # E.g. a timeseries that disappears between the two requests
    respx_mock.get(url__startswith=parameter_urls(KOELN_UUID, "W")).mock(
        return_value=TIMESERIES_404
    )
    respx_mock.get(STATION_URL).respond(json=load_fixture("station_koeln"))

    with pytest.raises(ToolError, match="404.*check that the station UUID"):
        await call(KOELN_UUID, "W")


async def test_fetch_measurements_most_recent_first(respx_mock):
    measurements = load_fixture("measurements_w")
    respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    recent = await client.fetch_measurements(KOELN_UUID, "W", 2)

    assert recent == [measurements[-1], measurements[-2]]


@pytest.mark.parametrize(
    ("start", "end", "params"),
    [
        (timedelta(hours=24), None, {"start": "PT1440M"}),
        # Rounded up, since PT0M would cover no time at all
        (timedelta(seconds=1), None, {"start": "PT1M"}),
        (
            datetime(2026, 10, 6, 12, 0, tzinfo=CEST),
            None,
            {"start": "2026-10-06T12:00:00+02:00"},
        ),
        (
            datetime(2026, 10, 6, 12, 0, tzinfo=CEST),
            datetime(2026, 10, 6, 14, 0, tzinfo=CEST),
            {"start": "2026-10-06T12:00:00+02:00", "end": "2026-10-06T14:00:00+02:00"},
        ),
    ],
    ids=["span", "span-rounded-up", "start", "start-end"],
)
async def test_fetch_measurements_since(respx_mock, start, end, params):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=measurements)

    recent = await client.fetch_measurements_since(KOELN_UUID, "W", start, end)

    assert dict(route.calls.last.request.url.params) == params
    # Oldest first, as the API returns them
    assert recent == measurements


async def test_window_timestamps_keep_their_offset(respx_mock):
    route = respx_mock.get(MEASUREMENTS_URL).respond(json=[])

    await client.fetch_measurements_since(
        KOELN_UUID, "W", datetime(2026, 10, 6, 12, 0, tzinfo=CEST)
    )

    # An unescaped "+" would reach the API as a space
    assert b"%2B02%3A00" in route.calls.last.request.url.query


async def test_fetch_measurements_chart(respx_mock):
    route = respx_mock.get(CHART_URL).respond(content=CHART_PNG, content_type="image/png")

    png = await client.fetch_measurements_chart(KOELN_UUID, "W", timedelta(hours=24))

    assert dict(route.calls.last.request.url.params) == {
        "start": "PT1440M",
        "width": "900",
        "height": "400",
    }
    assert png == CHART_PNG


async def test_fetch_measurements_falls_back_to_full_history(respx_mock):
    measurements = load_fixture("measurements_w")
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=[
            httpx2.Response(200, json=[]),
            httpx2.Response(200, json=measurements),
        ]
    )

    recent = await client.fetch_measurements(KOELN_UUID, "W", 3)

    assert route.call_count == 2
    assert route.calls[1].request.url.params["start"] == f"PT{client.HISTORY_MINUTES}M"
    assert recent == measurements[-1:-4:-1]


async def test_fetch_measurements_fallback_reaches_full_history(respx_mock):
    # An hourly series whose interval is unknown, so the window assumes 15
    # minutes: for 1000 values it holds about 500, and the API's 10-day
    # default would hold even fewer.
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


@pytest.mark.parametrize(
    ("series_interval", "interval_minutes", "window", "values"),
    [
        # 1-minute series: 2000 instead of 30 000 minutes
        (1, 1, "PT2000M", 1000),
        (15, 15, "PT30000M", 1000),
        # Hourly series: the full history at once instead of a second request
        (60, 60, f"PT{client.HISTORY_MINUTES}M", 31 * 24),
        # Unknown interval: 15 minutes are assumed
        (15, None, "PT30000M", 1000),
        (15, 0, "PT30000M", 1000),
    ],
)
async def test_fetch_measurements_window_follows_interval(
    respx_mock, series_interval, interval_minutes, window, values
):
    route = respx_mock.get(MEASUREMENTS_URL).mock(
        side_effect=fake_measurements_api(days=31, interval_minutes=series_interval)
    )

    recent = await client.fetch_measurements(KOELN_UUID, "W", 1000, interval_minutes)

    assert route.call_count == 1
    assert route.calls[0].request.url.params["start"] == window
    assert len(recent) == values
    first, last = recent[0]["timestamp"], recent[-1]["timestamp"]
    assert first is not None and last is not None
    assert first > last
