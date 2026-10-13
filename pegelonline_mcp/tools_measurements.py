"""Tools that fetch measurement values of a station."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from statistics import fmean

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image
from pydantic import AwareDatetime

from pegelonline_mcp import client
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.client import HISTORY_MINUTES
from pegelonline_mcp.constraints import Hours, RecentCount, Resolution
from pegelonline_mcp.mapping import normalize_timeseries, timeseries_comment, water_name
from pegelonline_mcp.models import (
    HistoryRows,
    HistorySummary,
    LatestMeasurement,
    LatestMeasurements,
    Measurement,
    MeasurementHistory,
    RecentMeasurements,
)

logger = logging.getLogger(__name__)

# Time span of the history and the chart without hours or start
DEFAULT_HOURS = 24
# How far back a time window may start and how long it may be, like hours
MAX_WINDOW = timedelta(minutes=HISTORY_MINUTES)
# Most grid slots (rows × columns) of raw values a history returns: 35 days
# of a 15-minute series. Slots, not values, bound the size: rows of a series
# with scattered gaps are full of nulls.
MAX_RAW_SLOTS = 35 * 24 * 4
# Claude Code moves tool results over 50 000 characters into a file and
# shows the model only its path; the largest histories come close to that.
MAX_RESULT_CHARS = 60_000
# Columns of the rows that summarize an hour or a day
SUMMARY_COLUMNS = ["min", "mean", "max"]

# A measured value with its time
Point = tuple[datetime, float]
Rows = dict[str, list[float | None]]


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
    (value older than 25 hours).

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_latest_measurements: uuid=%s", uuid)
    data = await client.fetch_station(uuid, current=True)

    # Clean up the response to only return relevant measurement data
    measurements: list[LatestMeasurement] = []
    for ts in normalize_timeseries(data):
        curr = ts.get("currentMeasurement")
        if curr:
            measurements.append({
                "parameter": ts.get("longname"),
                "shortname": ts.get("shortname"),
                "value": curr.get("value"),
                "unit": ts.get("unit"),
                "timestamp": curr.get("timestamp"),
                # Two independent classifications; the API sends "unknown"
                # rather than omitting one, so neither can stand in for the other.
                "state_mnw_mhw": curr.get("stateMnwMhw"),
                "state_nsw_hsw": curr.get("stateNswHsw"),
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
    # Fetched first, so an unknown parameter fails with a single 404
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


def _window_start(
    hours: float | None, start: datetime | None, end: datetime | None
) -> datetime | timedelta:
    """Start of the time window to fetch: start itself, or hours back from now.

    Rejects a window that mixes hours and start or that the API cannot serve.
    """
    if hours is not None and start is not None:
        raise ToolError("Pass either hours or start, not both.")
    if start is None:
        if end is not None:
            raise ToolError("end needs start; for the last N hours, pass hours alone.")
        return timedelta(hours=hours or DEFAULT_HOURS)
    now = datetime.now(UTC)
    end = end or now
    if start >= end:
        raise ToolError("start must lie before end (default: now).")
    if start < now - MAX_WINDOW:
        raise ToolError(
            f"start lies more than {MAX_WINDOW.days} days back; the official API "
            "keeps measurements for a little over 31 days."
        )
    if end - start > MAX_WINDOW:
        raise ToolError(
            f"start and end may lie at most {HISTORY_MINUTES // 60} hours apart."
        )
    return start


def _points(measurements: list[Measurement]) -> list[Point]:
    """Values with parsed timestamps; measurements without a value are skipped."""
    return [
        (datetime.fromisoformat(m["timestamp"]), m["value"])
        for m in measurements
        if m["timestamp"] is not None and m["value"] is not None
    ]


def _grid(interval: object, points: list[Point]) -> int | None:
    """The interval in minutes if every value lies on its grid, else None.

    Raw rows place a value by its minute, so they need a known interval and
    timestamps on multiples of it, counted from the full hour.
    """
    if not isinstance(interval, int) or interval < 1:
        return None
    on_grid = all(
        t.second == 0 and t.microsecond == 0 and t.minute % interval == 0
        for t, _ in points
    )
    return interval if on_grid else None


def _compact(value: float) -> float:
    """``value`` as int if it is whole, so the JSON leaves off ".0"."""
    return int(value) if value.is_integer() else value


def _mean(values: list[float]) -> float:
    """Mean of ``values``, rounded to two decimals."""
    return _compact(round(fmean(values), 2))


def _row_start(t: datetime, minutes: int) -> str:
    """Start of the row of ``minutes`` holding ``t``, with the UTC offset of ``t``.

    The offset tells apart the two hours of the same name when daylight
    saving time ends.
    """
    return t.replace(minute=t.minute - t.minute % minutes).isoformat(timespec="minutes")


def _raw_rows(points: list[Point], interval: int) -> tuple[list[str], Rows]:
    """Columns and rows of raw values: an hour per row, 10 minutes for 1-minute series."""
    row_minutes = 10 if interval == 1 else 60
    offsets = range(0, row_minutes, interval)
    rows: Rows = {}
    for t, value in points:
        row = rows.setdefault(_row_start(t, row_minutes), [None] * len(offsets))
        row[t.minute % row_minutes // interval] = _compact(value)
    return [f"+{offset}" for offset in offsets], rows


def _summarized_rows(points: list[Point], key: Callable[[datetime], str]) -> Rows:
    """min, mean and max of the values that share a key, e.g. their hour."""
    groups: dict[str, list[float]] = {}
    for t, value in points:
        groups.setdefault(key(t), []).append(value)
    return {
        k: [_compact(min(values)), _mean(values), _compact(max(values))]
        for k, values in groups.items()
    }


def _history_rows(
    points: list[Point], grid: int | None, resolution: Resolution
) -> HistoryRows:
    """Rows in the requested resolution, as get_measurement_history describes."""
    if grid is not None and resolution in ("auto", "raw"):
        columns, rows = _raw_rows(points, grid)
        # Beyond MAX_RAW_SLOTS, raw keeps the newest rows and auto summarizes
        max_rows = MAX_RAW_SLOTS // len(columns)
        if len(rows) <= max_rows or resolution == "raw":
            return {
                "resolution": "raw",
                "truncated": len(rows) > max_rows,
                "columns": columns,
                "rows": dict(list(rows.items())[-max_rows:]),
            }
    if resolution == "day":
        return {
            "resolution": "day",
            "truncated": False,
            "columns": SUMMARY_COLUMNS,
            "rows": _summarized_rows(points, lambda t: t.date().isoformat()),
        }
    # Also raw values that lie off the grid or exceed MAX_RAW_SLOTS
    return {
        "resolution": "hour",
        "truncated": False,
        "columns": SUMMARY_COLUMNS,
        "rows": _summarized_rows(points, lambda t: _row_start(t, 60)),
    }


def _measurement(point: Point) -> Measurement:
    """A value with its timestamp, as the API writes them."""
    t, value = point
    return {"timestamp": t.isoformat(), "value": _compact(value)}


def _summary(points: list[Point], grid: int | None) -> HistorySummary:
    """Statistics of all values; ``grid`` is the interval if they lie on it."""
    if not points:
        return {
            "count": 0, "missing": None, "first": None, "last": None,
            "min": None, "max": None, "mean": None,
        }
    first, last = points[0], points[-1]
    missing = None
    if grid is not None:
        # Grid slots from the first to the last value, both included
        missing = (last[0] - first[0]) // timedelta(minutes=grid) + 1 - len(points)
    return {
        "count": len(points),
        "missing": missing,
        "first": _measurement(first),
        "last": _measurement(last),
        # min and max return the first of equal values, so the earliest
        "min": _measurement(min(points, key=lambda p: p[1])),
        "max": _measurement(max(points, key=lambda p: p[1])),
        "mean": _mean([value for _, value in points]),
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
    - 'hour' or 'day': min, mean and max per hour or calendar day.

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
    since = _window_start(hours, start, end)
    # Fetched first, so an unknown parameter fails with a single 404
    timeseries = await client.fetch_timeseries(uuid, parameter)
    measurements = await client.fetch_measurements_since(uuid, parameter, since, end)
    points = _points(measurements)
    interval = timeseries.get("equidistance")
    grid = _grid(interval, points)
    table = _history_rows(points, grid, resolution)
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
        "summary": _summary(points, grid),
        **table,
    }


async def get_measurements_chart(
    uuid: str,
    parameter: str,
    hours: Hours | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
) -> Image:
    """
    Fetch the official API's line chart (PNG, 900 × 400 pixels) of one
    parameter of a station over a time span: by default the last 24 hours,
    at most 35 days back. Use it to see the course at a glance: trend,
    peaks, magnitude and gaps. It costs the same few hundred tokens for any
    span. Values read off it are approximate; exact values, timestamps and
    the timeseries comment come from get_measurement_history.

    The chart has no title, unit or legend. The y-axis shows the values in
    the timeseries' unit (see get_station_info) with a decimal comma, the
    x-axis German local time. Labeled horizontal lines are reference values
    such as NNW or MThw. Gaps break the line, and an empty grid means no
    values in the span. Some gauges add a dashed, lighter line, e.g. a
    forecast that can reach past now; the measured values are the solid line.

    The user may not see the image: some clients do not show it, others only
    inside the collapsed tool call. So describe what it shows in words.

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
    """
    logger.info(
        "get_measurements_chart: uuid=%s parameter=%s hours=%s start=%s end=%s",
        uuid, parameter, hours, start, end,
    )
    since = _window_start(hours, start, end)
    # No metadata first: the chart request itself fails with a single 404
    # for an unknown station or parameter
    png = await client.fetch_measurements_chart(uuid, parameter, since, end)
    logger.info(
        "get_measurements_chart: uuid=%s parameter=%s -> %d bytes",
        uuid, parameter, len(png),
    )
    return Image(data=png, format="png")


def register(mcp: FastMCP) -> None:
    """Register the measurement tools on the server."""
    mcp.tool(get_latest_measurements, annotations=READ_ONLY)
    mcp.tool(get_recent_measurements, annotations=READ_ONLY)
    # Lets Claude Code keep the largest histories in context
    mcp.tool(
        get_measurement_history,
        annotations=READ_ONLY,
        meta={"anthropic/maxResultSizeChars": MAX_RESULT_CHARS},
    )
    mcp.tool(get_measurements_chart, annotations=READ_ONLY)
