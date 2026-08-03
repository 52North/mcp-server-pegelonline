import logging
import math
import os
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from helpers import cache_get, cache_set, configure_logging, get_json, haversine_km

# Share the application logger namespace with helpers.py so a single log-config
# entry ("pegelonline-dict") governs both the HTTP layer and these handlers.
logger = logging.getLogger("pegelonline-dict")

# Initialize FastMCP server
mcp = FastMCP("Pegelonline Dict API")

BASE_URL = os.environ.get(
    "PEGELONLINE_DICT_API_URL", "https://dict-api.pegelonline.wsv.de"
).rstrip("/")
OFFICIAL_API_URL = os.environ.get(
    "PEGELONLINE_API_URL", "https://pegelonline.wsv.de/webservices/rest-api/v2"
).rstrip("/")

MAP_UI_URI = "ui://pegelonline-dict/stations-map"


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
    logger.info("search_stations: filters=%s limit=%d", params, limit)

    if limit < 1:
        logger.warning("search_stations: rejected limit=%d (must be >= 1)", limit)
        raise ToolError("limit must be at least 1.")

    data = await get_json(f"{BASE_URL}/search", params=params)
    stations = data.get("stations", [])
    total = len(stations)
    truncated = total > limit
    if truncated:
        stations = stations[:limit]
    logger.info(
        "search_stations: %d matches, returning %d (truncated=%s)",
        total, len(stations), truncated,
    )

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
async def get_station_info(uuid: str) -> dict:
    """
    Fetch static metadata for a specific station (name, agency, coordinates,
    water body, gauge zero and available observation parameters) without
    any measurement values.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_station_info: uuid=%s", uuid)
    url = f"{OFFICIAL_API_URL}/stations/{uuid}.json"
    data = await get_json(url, params={"includeTimeseries": "true"})

    parameters = [
        {
            "shortname": ts.get("shortname"),
            "longname": ts.get("longname"),
            "unit": ts.get("unit"),
            "equidistance_minutes": ts.get("equidistance"),
            "gaugeZero": ts.get("gaugeZero"),
        }
        for ts in data.get("timeseries", [])
    ]
    logger.info(
        "get_station_info: uuid=%s -> %s (%d parameters)",
        uuid, data.get("longname"), len(parameters),
    )

    return {
        "uuid": data.get("uuid"),
        "number": data.get("number"),
        "shortname": data.get("shortname"),
        "longname": data.get("longname"),
        "agency": data.get("agency"),
        "longitude": data.get("longitude"),
        "latitude": data.get("latitude"),
        "km": data.get("km"),
        "water": data.get("water", {}).get("longname"),
        "parameters": parameters,
    }

async def _fetch_nearest_stations(
    latitude: float, longitude: float, radius_km: float, limit: int
) -> dict:
    """Fetch stations around a coordinate, sorted nearest-first."""
    if radius_km <= 0:
        logger.warning(
            "nearest stations: rejected radius_km=%s (must be > 0)", radius_km
        )
        raise ToolError("radius_km must be greater than 0.")
    if limit < 1:
        logger.warning("nearest stations: rejected limit=%d (must be >= 1)", limit)
        raise ToolError("limit must be at least 1.")

    # The dict API has no radius filter but supports a bounding box and
    # enriches each station with its MQTT topic and timeseries. Query the
    # box enclosing the radius, then filter precisely by distance.
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * math.cos(math.radians(latitude)))
    bbox = (
        f"{longitude - dlon},{latitude - dlat},"
        f"{longitude + dlon},{latitude + dlat}"
    )
    data = await get_json(f"{BASE_URL}/search", params={"bbox": bbox})

    stations = []
    for s in data.get("stations", []):
        if s.get("latitude") is None or s.get("longitude") is None:
            continue
        distance = haversine_km(latitude, longitude, s["latitude"], s["longitude"])
        if distance > radius_km:
            continue
        timeseries = s.get("timeseries") or []
        if isinstance(timeseries, dict):
            timeseries = [timeseries]
        stations.append({
            "uuid": s.get("uuid"),
            "shortname": s.get("shortname"),
            "longname": s.get("longname"),
            "agency": s.get("agency"),
            "water": (s.get("water") or {}).get("longname"),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "distance_km": round(distance, 2),
            "mqtttopic": s.get("mqtttopic"),
            "parameters": [
                {
                    "shortname": ts.get("shortname"),
                    "longname": ts.get("longname"),
                    "unit": ts.get("unit"),
                }
                for ts in timeseries
            ],
        })
    stations.sort(key=lambda s: s["distance_km"])

    total = len(stations)
    logger.info(
        "nearest stations: %d within %.1f km of (%.4f, %.4f), returning %d",
        total, radius_km, latitude, longitude, min(total, limit),
    )
    return {
        "total_matches": total,
        "returned": min(total, limit),
        "truncated": total > limit,
        "stations": stations[:limit],
    }

@mcp.tool()
async def find_nearest_stations(
    latitude: float,
    longitude: float,
    radius_km: float = 25,
    limit: int = 10
) -> dict:
    """
    Find gauge stations near a geographic coordinate, sorted by distance
    (nearest first).

    Args:
        latitude: Latitude of the search center (WGS84, e.g., 50.94).
        longitude: Longitude of the search center (WGS84, e.g., 6.96).
        radius_km: Search radius in kilometers (default: 25).
        limit: Maximum number of stations to return (default: 10).
    """
    logger.info(
        "find_nearest_stations: lat=%s lon=%s radius_km=%s limit=%d",
        latitude, longitude, radius_km, limit,
    )
    return await _fetch_nearest_stations(latitude, longitude, radius_km, limit)

@mcp.tool(app=AppConfig(resource_uri=MAP_UI_URI))
async def show_stations_map(
    latitude: float,
    longitude: float,
    radius_km: float = 25,
    limit: int = 50
) -> dict:
    """
    Show an interactive map of all gauge stations within a search radius
    around a geographic coordinate. In MCP-Apps-capable clients the map is
    rendered inline (OpenStreetMap with radius circle and station markers);
    other clients receive the station list as structured data.

    Args:
        latitude: Latitude of the search center (WGS84, e.g., 50.94).
        longitude: Longitude of the search center (WGS84, e.g., 6.96).
        radius_km: Search radius in kilometers (default: 25).
        limit: Maximum number of stations to show (default: 50).
    """
    logger.info(
        "show_stations_map: lat=%s lon=%s radius_km=%s limit=%d",
        latitude, longitude, radius_km, limit,
    )
    result = await _fetch_nearest_stations(latitude, longitude, radius_km, limit)
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_km": radius_km,
        **result,
    }

@mcp.resource(
    MAP_UI_URI,
    mime_type=UI_MIME_TYPE,
    app=AppConfig(
        csp=ResourceCSP(
            resource_domains=[
                "https://unpkg.com",
                "https://tile.openstreetmap.org",
            ],
        ),
        prefers_border=True,
    ),
)
def stations_map_ui() -> str:
    """Leaflet map UI rendered inline for the show_stations_map tool."""
    logger.info("stations_map_ui: serving Leaflet map resource %s", MAP_UI_URI)
    return (Path(__file__).parent / "stations_map.html").read_text(encoding="utf-8")

@mcp.tool()
async def get_latest_measurements(uuid: str) -> dict:
    """
    Fetch the latest measurements (e.g., water level, flow, temperature) for a specific station.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_latest_measurements: uuid=%s", uuid)
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
    logger.info(
        "get_latest_measurements: uuid=%s -> %d current measurements",
        uuid, len(measurements),
    )

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
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s count=%d",
        uuid, parameter, count,
    )
    if count < 1:
        logger.warning("get_recent_measurements: rejected count=%d (must be >= 1)", count)
        raise ToolError("count must be at least 1.")

    url = f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}/measurements.json"

    # Measurements are typically spaced 15 minutes apart. Request a window
    # twice that size server-side instead of downloading the full history,
    # and fall back to the full history if the window has gaps.
    window_minutes = max(count * 30, 60)
    data = await get_json(url, params={"start": f"PT{window_minutes}M"})
    if len(data) < count:
        logger.debug(
            "get_recent_measurements: %dM window yielded %d < %d, fetching full history",
            window_minutes, len(data), count,
        )
        data = await get_json(url)

    # The API returns measurements in chronological order, so we take the last 'count' items
    recent = data[-count:] if data else []
    recent.reverse() # Most recent first
    logger.info(
        "get_recent_measurements: uuid=%s parameter=%s -> %d measurements",
        uuid, parameter, len(recent),
    )

    return {
        "uuid": uuid,
        "parameter": parameter,
        "measurements": recent
    }

@mcp.resource("water-bodies://list")
async def list_water_bodies() -> str:
    """List all available water bodies (Gewässer)."""
    logger.info("list_water_bodies: resource requested")
    cached = cache_get("water-bodies")
    if cached is not None:
        logger.debug("list_water_bodies: served from cache")
        return cached
    waters = await get_json(f"{OFFICIAL_API_URL}/waters.json")
    result = "\n".join([f"{w['longname']} ({w['shortname']})" for w in waters])
    cache_set("water-bodies", result)
    logger.info("list_water_bodies: fetched and cached %d water bodies", len(waters))
    return result

@mcp.resource("states://list")
async def list_states() -> str:
    """List all federal states (Bundesländer) that have stations."""
    logger.info("list_states: resource requested")
    cached = cache_get("states")
    if cached is not None:
        logger.debug("list_states: served from cache")
        return cached
    # We fetch all stations from the dict-api to get unique states
    data = await get_json(f"{BASE_URL}/search")
    states = sorted(list(set(s.get("land") for s in data.get("stations", []) if s.get("land"))))
    result = "\n".join(states)
    cache_set("states", result)
    logger.info("list_states: fetched and cached %d states", len(states))
    return result

@mcp.resource("states://{state}/stations")
async def list_stations_in_state(state: str) -> str:
    """List all stations in a specific federal state."""
    logger.info("list_stations_in_state: state=%s", state)
    data = await get_json(f"{BASE_URL}/search", params={"land": state})
    stations = data.get("stations", [])
    logger.info("list_stations_in_state: state=%s -> %d stations", state, len(stations))
    return "\n".join([f"{s['longname']} (UUID: {s['uuid']}, Gewässer: {s['water']['longname']})" for s in stations])

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> PlainTextResponse:
    """Liveness probe for a load balancer.

    The MCP endpoint (/mcp) requires a JSON-RPC handshake, so it is unsuitable
    as an LB health check. This lightweight route returns 200 OK instead.
    """
    # DEBUG only: the LB polls this frequently and uvicorn's access log already
    # records each hit, so INFO here would be pure noise.
    logger.debug("healthz: liveness probe")
    return PlainTextResponse("ok")


if __name__ == "__main__":
    # Configure logging for dev setup.
    # uvicorn logging is configured via --log-file config.
    configure_logging()
    mcp.run()
