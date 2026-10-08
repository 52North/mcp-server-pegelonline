from conftest import load_fixture
from pegelonline_mcp.mapping import normalize_timeseries, parameter_info, station_summary, water_name

W = {"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": "cm", "equidistance": 15}
Q = {"shortname": "Q", "longname": "ABFLUSS_ROHDATEN", "unit": "m³/s"}


def rhein_station(longname: str) -> dict:
    stations = load_fixture("search_rhein")["stations"]
    return next(s for s in stations if s["longname"] == longname)


def test_normalize_timeseries_keeps_list():
    assert normalize_timeseries({"timeseries": [W, Q]}) == [W, Q]


def test_normalize_timeseries_wraps_single_dict():
    assert normalize_timeseries({"timeseries": W}) == [W]


def test_normalize_timeseries_missing_or_none():
    assert normalize_timeseries({}) == []
    assert normalize_timeseries({"timeseries": None}) == []


def test_normalize_timeseries_drops_non_dict_entries():
    assert normalize_timeseries({"timeseries": [W, "W", None]}) == [W]


def test_water_name():
    assert water_name({"water": {"shortname": "RHEIN", "longname": "RHEIN"}}) == "RHEIN"


def test_water_name_missing():
    assert water_name({}) is None
    assert water_name({"water": None}) is None
    assert water_name({"water": {}}) is None


def test_parameter_info():
    assert parameter_info(W) == {
        "shortname": "W",
        "longname": "WASSERSTAND ROHDATEN",
        "unit": "cm",
    }


def test_station_summary():
    summary = station_summary(rhein_station("KÖLN"))

    assert summary["uuid"] == "a6ee8177-107b-47dd-bcfd-30960ccc6e9c"
    assert summary["water"] == "RHEIN"
    assert [p["shortname"] for p in summary["parameters"]] == ["Q", "W"]


def test_station_summary_single_dict_timeseries():
    summary = station_summary(rhein_station("BONN"))

    assert summary["parameters"] == [
        {"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": "cm"}
    ]


def test_station_summary_without_water_and_timeseries():
    summary = station_summary({"uuid": "x", "longname": "X"})

    assert summary["water"] is None
    assert summary["parameters"] == []
