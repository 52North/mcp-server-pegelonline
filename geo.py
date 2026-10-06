"""Geographic helpers for WGS84 coordinates."""

import math

EARTH_RADIUS_KM = 6371.0
# Approximate length of one degree of latitude
KM_PER_DEG_LAT = 111.32


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 coordinates in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bbox_around(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Bounding box enclosing a circle around a point.

    Returns ``(min_lon, min_lat, max_lon, max_lat)``.
    """
    dlat = radius_km / KM_PER_DEG_LAT
    dlon = radius_km / (KM_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat
