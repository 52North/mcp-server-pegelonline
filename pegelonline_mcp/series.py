"""Pure functions that turn measurements into rows, a summary and chart values."""

from collections.abc import Callable
from datetime import datetime, timedelta
from statistics import fmean

from pegelonline_mcp.constraints import Resolution
from pegelonline_mcp.models import (
    ChartValues,
    HistoryRows,
    HistorySummary,
    Measurement,
)

# Most grid slots (rows × columns) of raw values a history returns: 35 days
# of a 15-minute series. Slots, not values, bound the size: rows of a series
# with scattered gaps are full of nulls.
MAX_RAW_SLOTS = 35 * 24 * 4
# Columns of the rows that summarize an hour or a day; n counts their values
SUMMARY_COLUMNS = ["min", "mean", "max", "n"]

# A measured value with its time
Point = tuple[datetime, float]
Rows = dict[str, list[float | None]]


def points(measurements: list[Measurement]) -> list[Point]:
    """Values with parsed timestamps; measurements without a value are skipped."""
    return [
        (datetime.fromisoformat(m["timestamp"]), m["value"])
        for m in measurements
        if m["timestamp"] is not None and m["value"] is not None
    ]


def grid(interval: object, points: list[Point]) -> int | None:
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


def compact(value: float) -> float:
    """``value`` as int if it is whole, so the JSON leaves off ".0"."""
    return int(value) if value.is_integer() else value


def mean(values: list[float]) -> float:
    """Mean of ``values``, rounded to two decimals."""
    return compact(round(fmean(values), 2))


def row_start(t: datetime, minutes: int) -> str:
    """Start of the row of ``minutes`` holding ``t``, with the UTC offset of ``t``.

    The offset tells apart the two hours of the same name when daylight
    saving time ends.
    """
    return t.replace(minute=t.minute - t.minute % minutes).isoformat(timespec="minutes")


def raw_rows(points: list[Point], interval: int) -> tuple[list[str], Rows]:
    """Columns and rows of raw values: an hour per row, 10 minutes for 1-minute series."""
    row_minutes = 10 if interval == 1 else 60
    offsets = range(0, row_minutes, interval)
    rows: Rows = {}
    for t, value in points:
        row = rows.setdefault(row_start(t, row_minutes), [None] * len(offsets))
        row[t.minute % row_minutes // interval] = compact(value)
    return [f"+{offset}" for offset in offsets], rows


def summarized_rows(points: list[Point], key: Callable[[datetime], str]) -> Rows:
    """min, mean, max and number of the values that share a key, e.g. their hour."""
    groups: dict[str, list[float]] = {}
    for t, value in points:
        groups.setdefault(key(t), []).append(value)
    return {
        k: [compact(min(values)), mean(values), compact(max(values)), len(values)]
        for k, values in groups.items()
    }


def history_rows(
    points: list[Point], grid: int | None, resolution: Resolution
) -> HistoryRows:
    """Rows in the requested resolution, as get_measurement_history describes."""
    if grid is not None and resolution in ("auto", "raw"):
        columns, rows = raw_rows(points, grid)
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
            "rows": summarized_rows(points, lambda t: t.date().isoformat()),
        }
    # Also raw values that lie off the grid or exceed MAX_RAW_SLOTS
    return {
        "resolution": "hour",
        "truncated": False,
        "columns": SUMMARY_COLUMNS,
        "rows": summarized_rows(points, lambda t: row_start(t, 60)),
    }


def measurement(point: Point) -> Measurement:
    """A value with its timestamp, as the API writes them."""
    t, value = point
    return {"timestamp": t.isoformat(), "value": compact(value)}


def summary(points: list[Point], grid: int | None) -> HistorySummary:
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
        "first": measurement(first),
        "last": measurement(last),
        # min and max return the first of equal values, so the earliest
        "min": measurement(min(points, key=lambda p: p[1])),
        "max": measurement(max(points, key=lambda p: p[1])),
        "mean": mean([value for _, value in points]),
    }


def chart_values(points: list[Point], grid: int | None) -> ChartValues:
    """Values for the chart UI: a flat list on the grid, else with timestamps."""
    if grid is None:
        return {
            "start": None,
            "interval_minutes": None,
            "timestamps": [t.isoformat() for t, _ in points],
            "values": [compact(value) for _, value in points],
        }
    values: list[float | None] = []
    if points:
        # Aware datetimes subtract in absolute time, so the slots stay even
        # across a change of daylight saving time
        first, step = points[0][0], timedelta(minutes=grid)
        values = [None] * ((points[-1][0] - first) // step + 1)
        for t, value in points:
            values[(t - first) // step] = compact(value)
    return {
        "start": points[0][0].isoformat() if points else None,
        "interval_minutes": grid,
        "timestamps": None,
        "values": values,
    }
