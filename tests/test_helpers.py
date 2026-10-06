import pytest

from helpers import haversine_km

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
