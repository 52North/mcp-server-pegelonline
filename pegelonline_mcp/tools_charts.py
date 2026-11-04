"""Tools that chart the measurements of a station: the API's image and the interactive chart UI."""

import logging

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from pydantic import AwareDatetime

from pegelonline_mcp import client, series, windows
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.constraints import Hours
from pegelonline_mcp.errors import caller_error
from pegelonline_mcp.mapping import (
    normalize_timeseries,
    timeseries_comment,
    water_name,
)
from pegelonline_mcp.models import MeasurementsChart
from pegelonline_mcp.ui import CHART_UI_URI

logger = logging.getLogger(__name__)


def _station_timeseries(station: dict, parameter: str) -> dict:
    """The timeseries of ``parameter`` among a station's timeseries.

    Like the API, the short name matches regardless of case.
    """
    timeseries = normalize_timeseries(station)
    wanted = parameter.casefold()
    for ts in timeseries:
        shortname = ts.get("shortname")
        if isinstance(shortname, str) and shortname.casefold() == wanted:
            return ts
    available = ", ".join(sorted(str(ts.get("shortname")) for ts in timeseries))
    raise caller_error(
        f"Station {station.get('uuid')} has no parameter {parameter!r}; "
        f"it has {available or 'none'}."
    )


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
    such as NNW or MThw; get_characteristic_values returns them exactly.
    Gaps break the line, and an empty grid means no values in the span.
    Some gauges add a dashed, lighter line, e.g. a forecast that can reach
    past now; the measured values are the solid line.

    The user may not see the image: some clients do not show it, others only
    inside the collapsed tool call. So describe what it shows in words. To
    show the user a chart, call show_measurements_chart instead.

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
    since = windows.window_start(hours, start, end)
    # No metadata first: the chart request itself fails with a single 404
    # for an unknown station or parameter
    png = await client.fetch_measurements_chart(uuid, parameter, since, end)
    logger.info(
        "get_measurements_chart: uuid=%s parameter=%s -> %d bytes",
        uuid, parameter, len(png),
    )
    return Image(data=png, format="png")


async def show_measurements_chart(
    uuid: str,
    parameter: str,
    hours: Hours | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
) -> MeasurementsChart:
    """
    Show the user an interactive chart of one parameter of a station over a
    time span: by default the last 24 hours, at most 35 days back. In
    MCP-Apps-capable clients the chart is rendered inline and fetches the
    values itself; the user can zoom and read off values. You receive only
    the summary, so the span costs the same few hundred tokens whatever its
    length. In clients without MCP Apps (e.g., Claude Code) the user sees
    no chart.

    To see the course yourself, call get_measurements_chart; for exact
    values and timestamps, get_measurement_history.

    The response names the station and its water body, the unit and the
    timeseries comment, the interval in minutes, the window as start and end
    in UTC, and the summary of all values in it, as get_measurement_history
    reports it.

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
        "show_measurements_chart: uuid=%s parameter=%s hours=%s start=%s end=%s",
        uuid, parameter, hours, start, end,
    )
    window_start, window_end = windows.absolute_window(hours, start, end)
    station = await client.fetch_station(uuid)
    timeseries = _station_timeseries(station, parameter)
    # The chart UI shows it and passes it on, so "w" becomes "W"
    shortname = timeseries["shortname"]
    measurements = await client.fetch_measurements_since(
        uuid, shortname, window_start, window_end
    )
    points = series.points(measurements)
    interval = timeseries.get("equidistance")
    logger.info(
        "show_measurements_chart: uuid=%s parameter=%s -> %d values",
        uuid, shortname, len(points),
    )

    return {
        "uuid": uuid,
        "parameter": shortname,
        "station": station.get("longname"),
        "water": water_name(station),
        "unit": timeseries.get("unit"),
        "comment": timeseries_comment(timeseries),
        "interval_minutes": interval,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "summary": series.summary(points, series.grid(interval, points)),
    }


async def get_chart_values(
    uuid: str, parameter: str, start: AwareDatetime, end: AwareDatetime
) -> ToolResult:
    """
    Only for the chart UI of show_measurements_chart, not for the model: all
    values of one parameter of a station in a window, oldest first. For
    values to read or quote, call get_measurement_history instead.

    On the grid of the interval, values[i] lies i × interval_minutes after
    start and null marks a gap; off the grid, timestamps holds the time of
    each value.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter.
        start: Start of the window, with UTC offset.
        end: End of the window, with UTC offset.
    """
    logger.info(
        "get_chart_values: uuid=%s parameter=%s start=%s end=%s",
        uuid, parameter, start, end,
    )
    # No check how far back start lies: a chart reopened later shows what
    # the API still keeps
    timeseries = await client.fetch_timeseries(uuid, parameter)
    points = series.points(
        await client.fetch_measurements_since(uuid, parameter, start, end)
    )
    values = series.chart_values(
        points, series.grid(timeseries.get("equidistance"), points)
    )
    logger.info(
        "get_chart_values: uuid=%s parameter=%s -> %d values in %d slots",
        uuid, parameter, len(points), len(values["values"]),
    )
    # The values go only into structuredContent: the text would send them
    # a second time, and the model reads only the text
    return ToolResult(
        content=f"{len(points)} values for the chart UI; they are not meant for the model.",
        structured_content=values,
    )


def register(mcp: FastMCP) -> None:
    """Register the chart tools on the server."""
    mcp.tool(get_measurements_chart, annotations=READ_ONLY)
    mcp.tool(
        show_measurements_chart,
        app=AppConfig(resource_uri=CHART_UI_URI),
        annotations=READ_ONLY,
    )
    # Hidden from the model: its values are meant for the chart UI only
    mcp.tool(
        get_chart_values,
        app=AppConfig(visibility=["app"]),
        annotations=READ_ONLY,
    )
