"""The water level forecast tool, and the guard that keeps the forecast out of
the tools for measured values."""

import logging
import math
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from pegelonline_mcp import client, series
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.client import FORECAST_PARAMETER
from pegelonline_mcp.errors import caller_error
from pegelonline_mcp.mapping import (
    characteristic_value_map,
    current_measurement,
    normalize_timeseries,
    timeseries_comment,
    water_name,
)
from pegelonline_mcp.models import CompactNumber, ForecastValue, WaterLevelForecast

logger = logging.getLogger(__name__)

# How many stations with a forecast the error for a station without one names
NEAREST_FORECAST_STATIONS = 3


def reject_forecast(parameter: str) -> None:
    """Keep the forecast WV out of a tool for measured values.

    Such a tool would take the forecast for measurements: its most recent
    values would be the furthest estimates, and the official chart draws
    none of them.
    """
    if parameter.casefold() == FORECAST_PARAMETER.casefold():
        raise caller_error(
            f"{parameter} is a water level forecast, not measured values; "
            "call get_water_level_forecast."
        )


def _timeseries(station: dict, shortname: str) -> dict | None:
    """The timeseries ``shortname`` of a station, or None."""
    return next(
        (ts for ts in normalize_timeseries(station) if ts.get("shortname") == shortname),
        None,
    )


def _km(station: dict) -> float:
    """River kilometer of a station; stations without one sort last."""
    km = station.get("km")
    return km if isinstance(km, (int, float)) else math.inf


async def _no_forecast_error(station: dict) -> ToolError:
    """The error for a station without a forecast, naming the stations
    nearest to it by river kilometer on its water body that have one.

    search_stations cannot find them: the dict API does not know WV.
    """
    message = (
        f"Station {station.get('longname')} has no water level forecast "
        f"({FORECAST_PARAMETER})."
    )
    water = station.get("water")
    shortname = water.get("shortname") if isinstance(water, dict) else None
    if not isinstance(shortname, str):
        return caller_error(message)
    others = [
        s for s in await client.fetch_forecast_stations(shortname)
        if s.get("uuid") != station.get("uuid")
    ]
    name = water_name(station) or shortname
    if not others:
        return caller_error(f"{message} No station on {name} has one.")
    km = _km(station)
    # Without the station's km, every distance is inf and the API's order stays
    nearest = sorted(others, key=lambda s: abs(_km(s) - km))[:NEAREST_FORECAST_STATIONS]
    listed = ", ".join(
        f"{s.get('longname')} (km {s.get('km')}, uuid {s.get('uuid')})"
        for s in sorted(nearest, key=_km)
    )
    return caller_error(f"{message} Nearest stations on {name} with one: {listed}.")


def _minutes(timestamp: str | None) -> str | None:
    """``timestamp`` without seconds, like the row keys of the history."""
    if not timestamp:
        return None
    return datetime.fromisoformat(timestamp).isoformat(timespec="minutes")


def _value(m: ForecastValue) -> CompactNumber | list[CompactNumber | None] | None:
    """A forecast value, with its range where the source gives one."""
    value = series.compact_number(m["value"])
    if "percentile10" in m or "percentile90" in m:
        return [
            series.compact_number(m.get("percentile10")),
            value,
            series.compact_number(m.get("percentile90")),
        ]
    return value


async def get_water_level_forecast(uuid: str) -> WaterLevelForecast:
    """
    Fetch the latest water level forecast (Wasserstandsvorhersage, WV) of a
    station: the expected water level W for the next one to eight days.
    Only about 40 stations have one, mostly on the Elbe, Oder, Rhein and
    Donau; get_station_info lists it as parameter WV. For a station without
    one, the error names the nearest stations on its water body that have one.

    values maps each time (German time, CET/CEST) to the expected W in unit,
    relative to the same gauge zero as the measured W. Up to forecast_until
    the values are forecasts (Vorhersage); later ones are estimates
    (Abschätzung), a rough trend with greater uncertainty. Where the source
    gives a range (e.g., on the Oder), a value is [percentile10, value,
    percentile90], an 80 % range.

    initialized and source tell when and by whom the run was computed; only
    the latest run exists. It can be a day old, so its first values may lie
    in the past: compare them with current, the latest measured W with its
    states, to tell how well the run matches. characteristic_values of W
    (e.g., MNW, MW, the record low NNW, or GlW) tell how low or high the
    expected levels are. summary covers all values, as in
    get_measurement_history.

    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    logger.info("get_water_level_forecast: uuid=%s", uuid)
    station = await client.fetch_station(uuid, current=True, characteristic_values=True)
    forecast = _timeseries(station, FORECAST_PARAMETER)
    if forecast is None:
        raise await _no_forecast_error(station)
    measured = _timeseries(station, "W") or {}
    values = await client.fetch_forecast(uuid)
    points = series.points(values)
    interval = forecast.get("equidistance")
    forecasts = [m for m in values if m.get("type") == "forecast"]
    initialized = values[0].get("initialized") if values else forecast.get("start")
    logger.info(
        "get_water_level_forecast: uuid=%s -> %d values, initialized %s",
        uuid, len(values), initialized,
    )

    return {
        "uuid": station.get("uuid"),
        "station": station.get("longname"),
        "water": water_name(station),
        "unit": forecast.get("unit"),
        "initialized": _minutes(initialized),
        "source": timeseries_comment(forecast),
        "interval_minutes": interval,
        "current": current_measurement(measured),
        "characteristic_values": characteristic_value_map(measured),
        "forecast_until": _minutes(forecasts[-1]["timestamp"]) if forecasts else None,
        "summary": series.summary(points, series.grid(interval, points)),
        "values": {
            key: _value(m)
            for m in values
            if (key := _minutes(m["timestamp"])) is not None
        },
    }


def register(mcp: FastMCP) -> None:
    """Register the forecast tool on the server."""
    mcp.tool(get_water_level_forecast, annotations=READ_ONLY)
