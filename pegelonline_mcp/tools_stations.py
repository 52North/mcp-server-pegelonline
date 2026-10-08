"""Tools that locate stations and describe them."""

import logging

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

from pegelonline_mcp import client
from pegelonline_mcp.constraints import Count, Latitude, Longitude, RadiusKm
from pegelonline_mcp.geo import bbox_around, haversine_km
from pegelonline_mcp.mapping import (
    normalize_timeseries,
    parameter_info,
    station_summary,
    timeseries_comment,
    water_name,
)
from pegelonline_mcp.resources import MAP_UI_URI

logger = logging.getLogger("pegelonline-dict")

# Fields the text filters match on that station_summary leaves out; returned
# so the model can tell which substring matches it actually wanted.
FILTER_FIELDS = ("country", "land", "kreis", "einzugsgebiet")


async def search_stations(
    station: str | None = None,
    gewaesser: str | None = None,
    agency: str | None = None,
    land: str | None = None,
    country: str | None = None,
    einzugsgebiet: str | None = None,
    kreis: str | None = None,
    parameter: str | None = None,
    bbox: str | None = None,
    q: str | None = None,
    limit: Count = 50
) -> dict:
    """
    Search for Pegelonline stations using various optional parameters.
    Multiple parameters are combined with AND. Text filters match
    case-insensitive substrings, also of alternative (e.g., English) names:
    land='Sachsen' also returns stations in Niedersachsen and Sachsen-Anhalt,
    so check the returned fields when an exact match matters.

    Each station comes in compact form: uuid, names, agency, water body,
    coordinates, MQTT topic, observation parameters and the country, land,
    kreis and einzugsgebiet it lies in. Use get_station_info for details.

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

    stations = await client.search(params)
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
        "stations": [
            {**station_summary(s), **{k: s.get(k) for k in FILTER_FIELDS}}
            for s in stations
        ],
    }

async def get_station_info(uuid: str) -> dict:
    """
    Fetch static metadata for a specific station (name, agency, coordinates,
    water body, gauge zero and available observation parameters with their
    comments, e.g. disturbances) without any measurement values.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_station_info: uuid=%s", uuid)
    data = await client.fetch_station(uuid)

    parameters = [
        {
            **parameter_info(ts),
            "equidistance_minutes": ts.get("equidistance"),
            "gaugeZero": ts.get("gaugeZero"),
            "comment": timeseries_comment(ts),
        }
        for ts in normalize_timeseries(data)
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
        "water": water_name(data),
        "parameters": parameters,
    }

async def _fetch_nearest_stations(
    latitude: float, longitude: float, radius_km: float, limit: int
) -> dict:
    """Fetch stations around a coordinate, sorted nearest-first."""
    # The dict API has no radius filter but supports a bounding box and
    # enriches each station with its MQTT topic and timeseries. Query the
    # box enclosing the radius, then filter precisely by distance.
    min_lon, min_lat, max_lon, max_lat = bbox_around(latitude, longitude, radius_km)
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    stations = []
    for s in await client.search({"bbox": bbox}):
        if s.get("latitude") is None or s.get("longitude") is None:
            continue
        distance = haversine_km(latitude, longitude, s["latitude"], s["longitude"])
        if distance > radius_km:
            continue
        stations.append({**station_summary(s), "distance_km": round(distance, 2)})
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

async def find_nearest_stations(
    latitude: Latitude,
    longitude: Longitude,
    radius_km: RadiusKm = 25,
    limit: Count = 10
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

async def show_stations_map(
    latitude: Latitude,
    longitude: Longitude,
    radius_km: RadiusKm = 25,
    limit: Count = 50
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


def register(mcp: FastMCP) -> None:
    """Register the station tools on the server."""
    mcp.tool(search_stations)
    mcp.tool(get_station_info)
    mcp.tool(find_nearest_stations)
    mcp.tool(show_stations_map, app=AppConfig(resource_uri=MAP_UI_URI))
