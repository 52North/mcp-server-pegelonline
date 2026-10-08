"""Tools that fetch measurement values of a station."""

import logging

from fastmcp import FastMCP

from pegelonline_mcp import client
from pegelonline_mcp.constraints import Count
from pegelonline_mcp.mapping import normalize_timeseries, water_name

logger = logging.getLogger("pegelonline-dict")


async def get_latest_measurements(uuid: str) -> dict:
    """
    Fetch the latest measurements (e.g., water level, flow, temperature) for a specific station.

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
                "state": curr.get("stateMnwMhw") or curr.get("stateNswHsw")
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

async def get_recent_measurements(uuid: str, parameter: str, count: Count = 2) -> dict:
    """
    Fetch the most recent measurements for a specific parameter of a station.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2).
    """
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s count=%d",
        uuid, parameter, count,
    )
    recent = await client.fetch_measurements(uuid, parameter, count)
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
