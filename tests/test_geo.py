import pytest

from pegelonline_mcp.geo import bbox_around, haversine_km

KOELN = (50.936949, 6.9633)
DUESSELDORF = (51.225498, 6.769891)


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


def test_bbox_latitude_half_height():
    _, min_lat, _, max_lat = bbox_around(50.0, 7.0, 111.32)
    assert max_lat - 50.0 == pytest.approx(1.0)
    assert 50.0 - min_lat == pytest.approx(1.0)


def test_bbox_widens_with_latitude():
    min_lon_eq, _, max_lon_eq, _ = bbox_around(0.0, 7.0, 25)
    min_lon_60, _, max_lon_60, _ = bbox_around(60.0, 7.0, 25)
    assert (max_lon_60 - min_lon_60) == pytest.approx(2 * (max_lon_eq - min_lon_eq))


def test_bbox_encloses_radius():
    radius = 25
    lat, lon = KOELN
    min_lon, min_lat, max_lon, max_lat = bbox_around(lat, lon, radius)
    # The box edges lie at least radius_km away from the center
    assert haversine_km(lat, lon, max_lat, lon) >= radius * 0.99
    assert haversine_km(lat, lon, min_lat, lon) >= radius * 0.99
    assert haversine_km(lat, lon, lat, max_lon) >= radius * 0.99
    assert haversine_km(lat, lon, lat, min_lon) >= radius * 0.99
