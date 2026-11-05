"""Tools that fetch measurement values of a station."""

import logging

from fastmcp import FastMCP
from pydantic import AwareDatetime

from pegelonline_mcp import client, series, windows
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.constraints import Hours, RecentCount, Resolution, StationIds
from pegelonline_mcp.mapping import (
    characteristic_value,
    current_measurement,
    normalize_timeseries,
    timeseries_comment,
    water_name,
)
from pegelonline_mcp.models import (
    CharacteristicValues,
    ComparedStation,
    LatestMeasurement,
    LatestMeasurements,
    MeasurementHistory,
    RecentMeasurements,
    StationComparison,
)

logger = logging.getLogger(__name__)

# Claude Code moves tool results over 50 000 characters into a file and
# shows the model only its path; the largest histories come close to that.
MAX_RESULT_CHARS = 60_000


async def get_latest_measurements(uuid: str) -> LatestMeasurements:
    """
    Fetch the latest measurements (e.g., water level, flow, temperature) for a specific station.
    Each measurement carries the comment on its timeseries, e.g. a disturbance or why
    discharge is currently not determined.

    Water levels (W) also carry two states:
    - state_mnw_mhw relates W to mean low water (MNW) and mean high water (MHW):
      "low" (at or below MNW), "normal" (in between) or "high" (at or above MHW).
    - state_nsw_hsw relates W to the highest navigable water level (HSW):
      "normal" (below HSW) or "high" (at or above HSW).
    Both can also be "unknown" (no reference values for this timeseries),
    "commented" (malfunction or disturbance, see comment) or "out-dated"
    (value older than 25 hours). get_characteristic_values returns the
    reference values themselves, to say more precisely how high W is.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_latest_measurements: uuid=%s", uuid)
    data = await client.fetch_station(uuid, current=True)

    # Clean up the response to only return relevant measurement data
    measurements: list[LatestMeasurement] = []
    for ts in normalize_timeseries(data):
        current = current_measurement(ts)
        if current is None:
            continue
        measurements.append({
            "parameter": ts.get("longname"),
            "shortname": ts.get("shortname"),
            "value": current["value"],
            "unit": ts.get("unit"),
            "timestamp": current["timestamp"],
            # Two independent classifications; the API sends "unknown"
            # rather than omitting one, so neither can stand in for the other.
            "state_mnw_mhw": current["state_mnw_mhw"],
            "state_nsw_hsw": current["state_nsw_hsw"],
            "comment": timeseries_comment(ts),
        })
    logger.info(
        "get_latest_measurements: uuid=%s -> %d current measurements",
        uuid, len(measurements),
    )

    return {
        "station": data.get("longname"),
        "water": water_name(data),
        "measurements": measurements
    }


async def get_characteristic_values(
    uuid: str, parameter: str = "W"
) -> CharacteristicValues:
    """
    Fetch the characteristic values (Kennwerte) of a station's water level
    together with its current value, to tell how high or low the water is:
    e.g., between mean water (MW) and mean high water (MHW), or below the
    lowest level ever measured (NNW). Only water levels (W) have
    characteristic values; other parameters return an empty list, as do
    water levels without any.

    Each value carries its unit, mostly that of the measurements: cm
    relative to the gauge zero, on some canals heights in m. The values come
    in the API's order, each with its long name. The most common are:
    - MNW, MW, MHW: mean low, mean daily and mean high water over the years
      from timespan_start to timespan_end.
    - NNW, HHW: lowest and highest level ever measured, with the dates (or
      only years) in occurrences; NW and HW are the extremes of a timespan.
    - HSW: highest navigable water level; M_I, M_II, M_III: flood marks at
      which shipping restrictions take effect. Both apply from valid_from on.
    - MTnw, MThw: mean tidal low and high water; NTnw, HThw their extremes.
    TuGLW is a fairway depth below GlW, not a water level.

    current holds the latest measurement and, for W, the two states that
    get_latest_measurements reports; without MNW and MHW, or without HSW,
    the corresponding state is "unknown". comment explains disturbances or
    stale values, if there are any.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (default: 'W', the only one
            with characteristic values).
    """
    logger.info("get_characteristic_values: uuid=%s parameter=%s", uuid, parameter)
    timeseries = await client.fetch_timeseries(
        uuid, parameter, current=True, characteristic_values=True
    )

    values = [
        characteristic_value(cv) for cv in timeseries.get("characteristicValues") or []
    ]
    logger.info(
        "get_characteristic_values: uuid=%s parameter=%s -> %d values",
        uuid, parameter, len(values),
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "unit": timeseries.get("unit"),
        "comment": timeseries_comment(timeseries),
        "current": current_measurement(timeseries),
        "characteristic_values": values,
    }


def _compared_station(station: dict) -> ComparedStation:
    """A compared station with its current measurement and characteristic values."""
    # The API includes only the requested timeseries
    timeseries = normalize_timeseries(station)
    ts = timeseries[0] if timeseries else {}
    return {
        "uuid": station.get("uuid"),
        "station": station.get("longname"),
        "water": water_name(station),
        "km": station.get("km"),
        "unit": ts.get("unit"),
        "gaugeZero": ts.get("gaugeZero"),
        "comment": timeseries_comment(ts),
        "current": current_measurement(ts),
        "characteristic_values": {
            cv["shortname"]: cv.get("value")
            for cv in ts.get("characteristicValues") or []
            if isinstance(cv, dict) and isinstance(cv.get("shortname"), str)
        },
    }


async def compare_stations(uuids: StationIds, parameter: str = "W") -> StationComparison:
    """
    Fetch the current measurement of one parameter at several stations in a
    single call, e.g. to compare the water levels along a river. Each station
    comes with its water body, river kilometer (km), gauge zero, the comment on
    its timeseries and its characteristic values as short name and value
    (e.g., MNW, MW, MHW, HSW, NNW, HHW); get_characteristic_values explains
    them with their periods and dates. TuGLW is a fairway depth, not a water
    level.

    Water levels (W) are relative to each station's own gauge zero, so the W
    values of different stations cannot be compared directly. Compare their
    states (state_mnw_mhw, state_nsw_hsw, as in get_latest_measurements),
    where they lie between their characteristic values, or their absolute
    heights: gaugeZero (m above NHN) + W / 100 for W in cm.

    The stations come in the order of uuids. not_found lists the uuids the
    API did not return: unknown stations and stations without the parameter.

    Args:
        uuids: The UUIDs of the stations, one per item (1 to 30, e.g., from
            search_stations).
        parameter: The shortname of the parameter (default: 'W').
    """
    logger.info("compare_stations: %d uuids parameter=%s", len(uuids), parameter)
    requested = list(dict.fromkeys(uuid.strip() for uuid in uuids))
    # The API returns the uuids in lower case and in its own order
    found = {
        s["uuid"].casefold(): s
        for s in await client.fetch_stations_current(requested, parameter)
        if isinstance(s.get("uuid"), str)
    }

    stations: list[ComparedStation] = []
    not_found: list[str] = []
    for uuid in requested:
        station = found.get(uuid.casefold())
        if station is None:
            not_found.append(uuid)
        else:
            stations.append(_compared_station(station))
    logger.info(
        "compare_stations: parameter=%s -> %d stations, %d not found",
        parameter, len(stations), len(not_found),
    )

    return {"parameter": parameter, "stations": stations, "not_found": not_found}


async def get_recent_measurements(
    uuid: str, parameter: str, count: RecentCount = 2
) -> RecentMeasurements:
    """
    Fetch the most recent measurements for a specific parameter of a station,
    newest first. For a time span such as the last 24 hours, use
    get_measurement_history instead: the measurement interval differs per
    timeseries, so a count covers no fixed span.
    Values are given in unit, which differs between timeseries: water levels
    (W) are mostly in cm, but some stations, mostly on canals, report m+NN.
    comment explains disturbances or stale values, if there are any.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2, at most 100).
    """
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s count=%d",
        uuid, parameter, count,
    )
    # Fetched first: an unknown station or parameter fails here, with an
    # error that says which
    timeseries = await client.fetch_timeseries(uuid, parameter)
    recent = await client.fetch_measurements(
        uuid, parameter, count, timeseries.get("equidistance")
    )
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s -> %d measurements",
        uuid, parameter, len(recent),
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "unit": timeseries.get("unit"),
        "comment": timeseries_comment(timeseries),
        "measurements": recent
    }


async def get_measurement_history(
    uuid: str,
    parameter: str,
    hours: Hours | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    resolution: Resolution = "auto",
) -> MeasurementHistory:
    """
    Fetch the measurements of one parameter of a station over a time span,
    oldest first: by default the last 24 hours, at most 35 days back. The
    official API keeps a little over 31 days, so older values do not exist.
    Values are given in unit (water levels W mostly in cm, on some canals
    in m+NN); comment explains disturbances or stale values, if any.

    Values come in rows. A row key is the start of an hour in German time
    (CET/CEST, e.g., '2026-09-20T12:00+02:00'), and columns gives each
    slot's offset from it in minutes: '+15' holds the value of 12:15.
    1-minute series have rows of 10 minutes, so the slot is the last digit
    of the minute. null marks a missing value; rows without any value are
    left out.

    resolution selects the rows; the response reports which ones it holds:
    - 'auto': raw values while the rows hold at most 3360 slots (the whole
      history of 15- and 60-minute series), otherwise as 'hour'. For raw
      values of a single day of a 1-minute series, pass start and end.
    - 'raw': raw values; beyond 3360 slots only the newest rows, and
      truncated is true.
    - 'hour' or 'day': min, mean and max per hour or calendar day, and n,
      the number of values behind them. Fewer than the interval allows
      (e.g., 4 per hour at 15 minutes) mean gaps; the first and last row
      may also be cut off by the window.

    summary covers all values of the span in any case: count, missing (grid
    slots without a value between the first and last one), first, last,
    min and max with their timestamps, and mean.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        hours: The last N hours (e.g., 168 for a week); default 24 unless
            start is given.
        start: Start of a time window instead of hours, with UTC offset:
            e.g., '2026-09-20T00:00+02:00' in summer, '2026-12-01T00:00+01:00'
            in winter.
        end: End of the window, with UTC offset (default: now); only with
            start. Both ends are included, at most 840 hours apart.
        resolution: 'auto' (default), 'raw', 'hour' or 'day'; see above.
    """
    logger.info(
        "get_measurement_history: uuid=%s parameter=%s hours=%s start=%s end=%s "
        "resolution=%s",
        uuid, parameter, hours, start, end, resolution,
    )
    since = windows.window_start(hours, start, end)
    # Fetched first: an unknown station or parameter fails here, with an
    # error that says which
    timeseries = await client.fetch_timeseries(uuid, parameter)
    measurements = await client.fetch_measurements_since(uuid, parameter, since, end)
    points = series.points(measurements)
    interval = timeseries.get("equidistance")
    grid = series.grid(interval, points)
    table = series.history_rows(points, grid, resolution)
    logger.info(
        "get_measurement_history: uuid=%s parameter=%s -> %d values in %d %s rows",
        uuid, parameter, len(points), len(table["rows"]), table["resolution"],
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "unit": timeseries.get("unit"),
        "comment": timeseries_comment(timeseries),
        "interval_minutes": interval,
        "summary": series.summary(points, grid),
        **table,
    }


def register(mcp: FastMCP) -> None:
    """Register the measurement tools on the server."""
    mcp.tool(get_latest_measurements, annotations=READ_ONLY)
    mcp.tool(get_characteristic_values, annotations=READ_ONLY)
    mcp.tool(compare_stations, annotations=READ_ONLY)
    mcp.tool(get_recent_measurements, annotations=READ_ONLY)
    # Lets Claude Code keep the largest histories in context
    mcp.tool(
        get_measurement_history,
        annotations=READ_ONLY,
        meta={"anthropic/maxResultSizeChars": MAX_RESULT_CHARS},
    )
