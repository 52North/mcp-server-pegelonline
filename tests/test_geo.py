import math

import pytest

from pegelonline_mcp.geo import EARTH_RADIUS_KM, bbox_around, haversine_km

KOELN = (50.936949, 6.9633)
DUESSELDORF = (51.225498, 6.769891)


def destination(
    lat: float, lon: float, bearing: float, distance_km: float
) -> tuple[float, float]:
    """Point reached from (lat, lon) after ``distance_km`` on the given bearing."""
    d = distance_km / EARTH_RADIUS_KM
    phi1, lambda1, theta = map(math.radians, (lat, lon, bearing))
    phi2 = math.asin(
        math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(d) * math.cos(phi1),
        math.cos(d) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lambda2)


def test_haversine_same_point_is_zero():
    assert haversine_km(*KOELN, *KOELN) == 0.0


def test_haversine_is_symmetric():
    assert haversine_km(*KOELN, *DUESSELDORF) == pytest.approx(
        haversine_km(*DUESSELDORF, *KOELN)
    )


def test_haversine_one_degree_latitude():
    assert haversine_km(50.0, 7.0, 51.0, 7.0) == pytest.approx(111.19, abs=0.01)


def test_haversine_koeln_duesseldorf():
    assert haversine_km(*KOELN, *DUESSELDORF) == pytest.approx(34.8, abs=0.5)


def test_bbox_is_centered_on_point():
    min_lon, min_lat, max_lon, max_lat = bbox_around(*KOELN, 25)
    assert (min_lat + max_lat) / 2 == pytest.approx(KOELN[0])
    assert (min_lon + max_lon) / 2 == pytest.approx(KOELN[1])
    assert min_lat < max_lat
    assert min_lon < max_lon


def test_bbox_latitude_edges_lie_at_radius():
    lat, lon = KOELN
    _, min_lat, _, max_lat = bbox_around(lat, lon, 25)

    assert haversine_km(lat, lon, max_lat, lon) == pytest.approx(25)
    assert haversine_km(lat, lon, min_lat, lon) == pytest.approx(25)


def test_bbox_widens_with_latitude():
    min_lon_eq, _, max_lon_eq, _ = bbox_around(0.0, 7.0, 25)
    min_lon_60, _, max_lon_60, _ = bbox_around(60.0, 7.0, 25)
    # About 1 / cos(latitude), a little more as the circle bulges poleward
    assert (max_lon_60 - min_lon_60) == pytest.approx(
        2 * (max_lon_eq - min_lon_eq), rel=1e-4
    )


@pytest.mark.parametrize("radius", [25, 1000])
def test_bbox_encloses_circle(radius):
    lat, lon = KOELN
    min_lon, min_lat, max_lon, max_lat = bbox_around(lat, lon, radius)
    eps = 1e-9  # degrees, for rounding at the extreme points

    for bearing in range(360):
        p_lat, p_lon = destination(lat, lon, bearing, radius)
        assert min_lat - eps <= p_lat <= max_lat + eps
        assert min_lon - eps <= p_lon <= max_lon + eps


def test_bbox_spans_all_longitudes_around_a_pole():
    min_lon, min_lat, max_lon, max_lat = bbox_around(89.9, 7.0, 25)

    assert (min_lon, max_lon, max_lat) == (-180.0, 180.0, 90.0)
    assert min_lat == pytest.approx(89.9 - math.degrees(25 / EARTH_RADIUS_KM))
