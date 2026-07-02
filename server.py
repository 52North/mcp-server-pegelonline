import logging
import os
from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from helpers import cache_get, cache_set, get_json

# Logging goes to stderr, so it does not interfere with the stdio MCP transport
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Initialize FastMCP server
mcp = FastMCP("Pegelonline Dict API")

BASE_URL = os.environ.get(
    "PEGELONLINE_DICT_API_URL", "https://dict-api.pegelonline.wsv.de"
).rstrip("/")
OFFICIAL_API_URL = os.environ.get(
    "PEGELONLINE_API_URL", "https://pegelonline.wsv.de/webservices/rest-api/v2"
).rstrip("/")


@mcp.tool()
async def search_stations(
    station: Optional[str] = None,
    gewaesser: Optional[str] = None,
    agency: Optional[str] = None,
    land: Optional[str] = None,
    country: Optional[str] = None,
    einzugsgebiet: Optional[str] = None,
    kreis: Optional[str] = None,
    parameter: Optional[str] = None,
    bbox: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50
) -> dict:
    """
    Search for Pegelonline stations using various optional parameters.
    Multiple parameters are combined with AND.

    Args:
        station: Search by station name (e.g., 'Köln').
        gewaesser: Search by water body (e.g., 'Rhein').
        agency: Search by agency (e.g., 'Dresden').
        land: Search by state/land (e.g., 'Hamburg').
        country: Search by country (e.g., 'Deutschland').
        einzugsgebiet: Search by catchment area (e.g., 'Ems').
        kreis: Search by district/county (e.g., 'Emsland').
        parameter: Search by observation parameter (e.g., 'Wassertemperatur').
        bbox: Search by bounding box (minLon, minLat, maxLon, maxLat, e.g., '7,52,8,53').
        q: General search across all parameters.
        limit: Maximum number of stations to return (default: 50). The response
            reports the total number of matches, so a truncated result is visible.
    """
    params = {
        "station": station,
        "gewaesser": gewaesser,
        "agency": agency,
        "land": land,
        "country": country,
        "einzugsgebiet": einzugsgebiet,
        "kreis": kreis,
        "parameter": parameter,
        "bbox": bbox,
        "q": q
    }
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}

    if limit < 1:
        raise ToolError("limit must be at least 1.")

    data = await get_json(f"{BASE_URL}/search", params=params)
    stations = data.get("stations", [])
    total = len(stations)
    truncated = total > limit
    if truncated:
        stations = stations[:limit]

    return {
        "total_matches": total,
        "returned": len(stations),
        "truncated": truncated,
        "stations": stations,
        # Rebuild the aggregated lists from the (possibly truncated) stations
        # so they stay consistent with the station list.
        "mqtttopics": [s["mqtttopic"] for s in stations if s.get("mqtttopic")],
        "pegelonlinelinks": [
            ts["pegelonlinelink"]
            for s in stations
            for ts in (s.get("timeseries") or [])
            if isinstance(ts, dict) and ts.get("pegelonlinelink")
        ],
    }

@mcp.tool()
async def get_latest_measurements(uuid: str) -> dict:
    """
    Fetch the latest measurements (e.g., water level, flow, temperature) for a specific station.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    url = f"{OFFICIAL_API_URL}/stations/{uuid}.json"
    params = {
        "includeTimeseries": "true",
        "includeCurrentMeasurement": "true"
    }

    data = await get_json(url, params=params)

    # Clean up the response to only return relevant measurement data
    measurements = []
    for ts in data.get("timeseries", []):
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

    return {
        "station": data.get("longname"),
        "water": data.get("water", {}).get("longname"),
        "measurements": measurements
    }

@mcp.tool()
async def get_recent_measurements(uuid: str, parameter: str, count: int = 2) -> dict:
    """
    Fetch the most recent measurements for a specific parameter of a station.

    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2).
    """
    if count < 1:
        raise ToolError("count must be at least 1.")

    url = f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}/measurements.json"

    # Measurements are typically spaced 15 minutes apart. Request a window
    # twice that size server-side instead of downloading the full history,
    # and fall back to the full history if the window has gaps.
    window_minutes = max(count * 30, 60)
    data = await get_json(url, params={"start": f"PT{window_minutes}M"})
    if len(data) < count:
        data = await get_json(url)

    # The API returns measurements in chronological order, so we take the last 'count' items
    recent = data[-count:] if data else []
    recent.reverse() # Most recent first

    return {
        "uuid": uuid,
        "parameter": parameter,
        "measurements": recent
    }

@mcp.resource("water-bodies://list")
async def list_water_bodies() -> str:
    """List all available water bodies (Gewässer)."""
    cached = cache_get("water-bodies")
    if cached is not None:
        return cached
    waters = await get_json(f"{OFFICIAL_API_URL}/waters.json")
    result = "\n".join([f"{w['longname']} ({w['shortname']})" for w in waters])
    cache_set("water-bodies", result)
    return result

@mcp.resource("states://list")
async def list_states() -> str:
    """List all federal states (Bundesländer) that have stations."""
    cached = cache_get("states")
    if cached is not None:
        return cached
    # We fetch all stations from the dict-api to get unique states
    data = await get_json(f"{BASE_URL}/search")
    states = sorted(list(set(s.get("land") for s in data.get("stations", []) if s.get("land"))))
    result = "\n".join(states)
    cache_set("states", result)
    return result

@mcp.resource("states://{state}/stations")
async def list_stations_in_state(state: str) -> str:
    """List all stations in a specific federal state."""
    data = await get_json(f"{BASE_URL}/search", params={"land": state})
    stations = data.get("stations", [])
    return "\n".join([f"{s['longname']} (UUID: {s['uuid']}, Gewässer: {s['water']['longname']})" for s in stations])

if __name__ == "__main__":
    mcp.run()
