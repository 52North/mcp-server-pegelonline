"""Unit tests of the measurement series helpers, without upstream or MCP client."""

from datetime import datetime, timedelta, timezone

import pytest

from pegelonline_mcp import series

CEST = timezone(timedelta(hours=2))
NOON = datetime(2026, 10, 6, 12, 0, tzinfo=CEST)


@pytest.mark.parametrize("interval", [None, 0, "15"])
def test_grid_needs_a_whole_positive_interval(interval):
    assert series.grid(interval, [(NOON, 1.0)]) is None


@pytest.mark.parametrize(
    "t",
    [NOON.replace(minute=7), NOON.replace(second=30)],
    ids=["off-grid-minute", "seconds"],
)
def test_grid_rejects_values_off_the_grid(t):
    assert series.grid(15, [(NOON, 1.0), (t, 2.0)]) is None


def test_grid_returns_the_interval_of_values_on_it():
    assert series.grid(15, [(NOON, 1.0), (NOON.replace(minute=45), 2.0)]) == 15


def test_points_skip_measurements_without_value_or_timestamp():
    measurements: list = [
        {"timestamp": "2026-10-06T12:00:00+02:00", "value": 350},
        {"timestamp": "2026-10-06T12:15:00+02:00", "value": None},
        {"timestamp": None, "value": 351},
    ]

    assert series.points(measurements) == [(NOON, 350)]


def test_compact_drops_the_fraction_of_whole_values():
    assert type(series.compact(3.0)) is int
    assert series.compact(3.5) == 3.5


def test_row_start_of_ten_minute_rows():
    assert series.row_start(NOON.replace(minute=37), 10) == "2026-10-06T12:30+02:00"


def test_chart_values_on_the_grid_without_points():
    assert series.chart_values([], 15) == {
        "start": None,
        "interval_minutes": 15,
        "timestamps": None,
        "values": [],
    }
