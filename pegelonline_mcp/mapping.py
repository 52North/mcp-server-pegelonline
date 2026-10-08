"""Mapping helpers that turn upstream station JSON into tool responses."""

from typing import Any


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


def parameter_info(ts: dict) -> dict[str, Any]:
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


def station_summary(station: dict) -> dict[str, Any]:
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
