"""Tools that fetch measurement values of a station."""

import logging
import math

from fastmcp import FastMCP

from pegelonline_mcp import client
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.constraints import Count, Hours
from pegelonline_mcp.mapping import normalize_timeseries, timeseries_comment, water_name
from pegelonline_mcp.models import (
    LatestMeasurement,
    LatestMeasurements,
    RecentMeasurements,
    SpanCounts,
)

logger = logging.getLogger("pegelonline-dict")

# Most values a time span returns: a full day of a 1-minute series, so
# hours=24 always fits, while 35 days of such a series (about 45 000 values)
# no longer flood the LLM context.
MAX_SPAN_VALUES = 24 * 60


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
    uuid: str, parameter: str, count: Count = 2, hours: Hours | None = None
) -> RecentMeasurements:
    """
    Fetch the most recent measurements for a specific parameter of a station.
    Values are given in unit, which differs between timeseries: water levels
    (W) are mostly in cm, but some stations, mostly on canals, report m+NN.
    comment explains disturbances or stale values, if there are any.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2). Ignored if
            hours is given.
        hours: Fetch all measurements of the last N hours instead (e.g., 24).
            Prefer this for time spans: the measurement interval differs per
            timeseries (1, 15 or 60 minutes). At most the 1440 most recent
            values are returned; total_matches and truncated report a cut.
    """
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s count=%d hours=%s",
        uuid, parameter, count, hours,
    )
    # Fetched first, so an unknown parameter fails with a single 404
    timeseries = await client.fetch_timeseries(uuid, parameter)
    span: SpanCounts = {}
    if hours is None:
        recent = await client.fetch_measurements(
            uuid, parameter, count, timeseries.get("equidistance")
        )
    else:
        in_span = await client.fetch_measurements_within(
            uuid, parameter, math.ceil(hours * 60)
        )
        recent = in_span[:MAX_SPAN_VALUES]
        span = {
            "total_matches": len(in_span),
            "returned": len(recent),
            "truncated": len(in_span) > len(recent),
        }
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s -> %d measurements",
        uuid, parameter, len(recent),
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "unit": timeseries.get("unit"),
        "comment": timeseries_comment(timeseries),
        **span,
        "measurements": recent
    }


def register(mcp: FastMCP) -> None:
    """Register the measurement tools on the server."""
    mcp.tool(get_latest_measurements, annotations=READ_ONLY)
    mcp.tool(get_recent_measurements, annotations=READ_ONLY)
