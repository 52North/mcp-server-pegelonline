"""Tools that fetch measurement values of a station."""

import logging
import math

from fastmcp import FastMCP

from pegelonline_mcp import client
from pegelonline_mcp.constraints import Count, Hours
from pegelonline_mcp.mapping import normalize_timeseries, timeseries_comment, water_name

logger = logging.getLogger("pegelonline-dict")


async def get_latest_measurements(uuid: str) -> dict:
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
    measurements = []
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
) -> dict:
    """
    Fetch the most recent measurements for a specific parameter of a station.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2). Ignored if
            hours is given.
        hours: Fetch all measurements of the last N hours instead (e.g., 24).
            Prefer this for time spans: the measurement interval differs per
            timeseries (1, 15 or 60 minutes).
    """
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s count=%d hours=%s",
        uuid, parameter, count, hours,
    )
    if hours is None:
        recent = await client.fetch_measurements(uuid, parameter, count)
    else:
        recent = await client.fetch_measurements_within(
            uuid, parameter, math.ceil(hours * 60)
        )
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s -> %d measurements",
        uuid, parameter, len(recent),
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "measurements": recent
    }


def register(mcp: FastMCP) -> None:
    """Register the measurement tools on the server."""
    mcp.tool(get_latest_measurements)
    mcp.tool(get_recent_measurements)
