import pytest

from conftest import load_fixture
from pegelonline_mcp.mapping import (
    characteristic_value,
    normalize_timeseries,
    parameter_info,
    station_summary,
    timeseries_comment,
    water_name,
)

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


def test_timeseries_comment_prefers_long_description():
    ts = {
        "comment": {
            "shortDescription": "Behelfspegel - Messwerte können Fehler aufweisen",
            "longDescription": "Nach einer Schiffskollision ist aktuell ein Behelfspegel"
            " in Betrieb. Die Messwerte können Fehler aufweisen.",
        }
    }

    assert timeseries_comment(ts).startswith("Nach einer Schiffskollision")


def test_timeseries_comment_falls_back_to_short_description():
    ts = {"comment": {"shortDescription": "Techn. Störung"}}

    assert timeseries_comment(ts) == "Techn. Störung"


def test_timeseries_comment_missing():
    assert timeseries_comment(W) is None
    assert timeseries_comment({"comment": None}) is None


@pytest.mark.parametrize(
    ("shortname", "fields"),
    [
        ("HSW", {"valid_from": "1950-01-01"}),
        ("MNW", {"timespan_start": "2010-11-01", "timespan_end": "2020-10-31"}),
        ("NNW", {"occurrences": ["2018-10-23"]}),
    ],
    ids=["fixed", "statistic", "extreme"],
)
def test_characteristic_value(shortname, fields):
    # Recorded Köln W: each kind of value carries other optional fields
    values = load_fixture("timeseries_koeln_w_characteristic")["characteristicValues"]
    cv = next(v for v in values if v["shortname"] == shortname)

    optional = {
        "valid_from": None, "timespan_start": None, "timespan_end": None,
        "occurrences": None,
    }
    assert characteristic_value(cv) == {
        "shortname": shortname,
        "longname": cv["longname"].strip(),
        "value": cv["value"],
        "unit": "cm",
        **optional,
        **fields,
    }


def test_characteristic_value_strips_longname():
    cv = {"shortname": "MW", "longname": "Mittel der Tageswasserstände "}

    assert characteristic_value(cv)["longname"] == "Mittel der Tageswasserstände"


def test_characteristic_value_missing_fields():
    assert characteristic_value({}) == dict.fromkeys(
        [
            "shortname", "longname", "value", "unit", "valid_from",
            "timespan_start", "timespan_end", "occurrences",
        ]
    )


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
