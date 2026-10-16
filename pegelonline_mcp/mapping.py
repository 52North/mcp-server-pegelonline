"""Mapping helpers that turn upstream station JSON into tool responses."""

from pegelonline_mcp.models import (
    CharacteristicValue,
    CurrentMeasurement,
    ParameterInfo,
    StationSummary,
)


def normalize_timeseries(station: dict) -> list[dict]:
    """Timeseries of a station as a list of dicts.

    The dict API's OpenAPI spec declares ``timeseries`` as a single object,
    while the live API always returns a list; both shapes are accepted.
    Missing timeseries and non-dict entries are dropped.
    """
    timeseries = station.get("timeseries")
    if isinstance(timeseries, dict):
        return [timeseries]
    if not isinstance(timeseries, list):
        return []
    return [ts for ts in timeseries if isinstance(ts, dict)]


def water_name(station: dict) -> str | None:
    """Long name of the station's water body, or None if it is missing."""
    water = station.get("water")
    if not isinstance(water, dict):
        return None
    return water.get("longname")


def search_values(station: dict, field: str) -> list[tuple[str, str | None]]:
    """Values of a search_stations filter that a station has, each with a long name.

    For gewaesser and parameter the value is a short name, which comes with
    the long name of the water body or timeseries; the other filters take
    the station field itself, without a long name. Missing values are dropped.
    """
    if field == "gewaesser":
        water = station.get("water")
        pairs = (
            [(water.get("shortname"), water.get("longname"))]
            if isinstance(water, dict) else []
        )
    elif field == "parameter":
        pairs = [
            (ts.get("shortname"), ts.get("longname"))
            for ts in normalize_timeseries(station)
        ]
    else:
        pairs = [(station.get(field), None)]
    return [
        (value, longname if isinstance(longname, str) and longname else None)
        for value, longname in pairs
        if isinstance(value, str) and value
    ]


def parameter_info(ts: dict) -> ParameterInfo:
    """Short description of an observation parameter (timeseries)."""
    return {
        "shortname": ts.get("shortname"),
        "longname": ts.get("longname"),
        "unit": ts.get("unit"),
    }


def timeseries_comment(ts: dict) -> str | None:
    """Comment on a timeseries (e.g., a disturbance), or None if there is none.

    The API sends a short and a long description; the long one can carry
    more detail, so it is preferred.
    """
    comment = ts.get("comment")
    if not isinstance(comment, dict):
        return None
    return comment.get("longDescription") or comment.get("shortDescription")


def current_measurement(ts: dict) -> CurrentMeasurement | None:
    """Current measurement of a timeseries with its two states, or None."""
    curr = ts.get("currentMeasurement")
    if not isinstance(curr, dict) or not curr:
        return None
    return {
        "timestamp": curr.get("timestamp"),
        "value": curr.get("value"),
        "state_mnw_mhw": curr.get("stateMnwMhw"),
        "state_nsw_hsw": curr.get("stateNswHsw"),
    }


def characteristic_value(cv: dict) -> CharacteristicValue:
    """Characteristic value of a timeseries (e.g., MNW or HSW).

    Some long names end in a space, which is dropped.
    """
    longname = cv.get("longname")
    return {
        "shortname": cv.get("shortname"),
        "longname": longname.strip() if isinstance(longname, str) else None,
        "value": cv.get("value"),
        "unit": cv.get("unit"),
        "valid_from": cv.get("validFrom"),
        "timespan_start": cv.get("timespanStart"),
        "timespan_end": cv.get("timespanEnd"),
        "occurrences": cv.get("occurrences"),
    }


def station_summary(station: dict) -> StationSummary:
    """Compact station description with its observation parameters."""
    return {
        "uuid": station.get("uuid"),
        "shortname": station.get("shortname"),
        "longname": station.get("longname"),
        "agency": station.get("agency"),
        "water": water_name(station),
        "latitude": station.get("latitude"),
        "longitude": station.get("longitude"),
        "mqtttopic": station.get("mqtttopic"),
        "parameters": [parameter_info(ts) for ts in normalize_timeseries(station)],
    }
