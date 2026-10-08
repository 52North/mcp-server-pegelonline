"""Geographic helpers for WGS84 coordinates."""

import math

EARTH_RADIUS_KM = 6371.0


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

    Returns ``(min_lon, min_lat, max_lon, max_lat)``. The circle lies on the
    same sphere as ``haversine_km``, so every point within ``radius_km``
    falls inside the box.
    """
    delta = radius_km / EARTH_RADIUS_KM
    dlat = math.degrees(delta)
    if abs(lat) + dlat >= 90:
        # The circle reaches a pole, so it spans every longitude
        return -180.0, max(lat - dlat, -90.0), 180.0, min(lat + dlat, 90.0)
    # The circle is widest north or south of its center, which makes its
    # longitude extent slightly larger than delta / cos(lat)
    dlon = math.degrees(math.asin(math.sin(delta) / math.cos(math.radians(lat))))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat
