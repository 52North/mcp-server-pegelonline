"""The overview tools: current water levels along water bodies or across
Germany, as data for the model and as a map for the user."""

import difflib
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import get_args

from fastmcp import FastMCP
from fastmcp.apps import UI_EXTENSION_ID, AppConfig
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult

from pegelonline_mcp import client, series
from pegelonline_mcp.annotations import READ_ONLY
from pegelonline_mcp.client import FORECAST_PARAMETER
from pegelonline_mcp.constraints import WaterLevelState
from pegelonline_mcp.errors import caller_error
from pegelonline_mcp.mapping import (
    current_measurement,
    normalize_timeseries,
    water_name,
)
from pegelonline_mcp.models import (
    MapWaterLevel,
    OverviewStation,
    WaterLevelMap,
    WaterLevelMarker,
    WaterLevelOverview,
)
from pegelonline_mcp.ui import MAP_UI_URI, client_renders_apps

logger = logging.getLogger(__name__)

MAP_SHOWN_NOTE = (
    "The user sees this map of every station in scope. Describe the situation "
    "from counts, waters and the notable stations; get_water_level_overview "
    "lists the value of every station."
)
MAP_NOT_SHOWN_NOTE = (
    "This client shows no map, so the user sees nothing. Describe the "
    "situation from counts, waters and the notable stations, or call "
    "get_water_level_overview for the value of every station."
)

# A station in scope: the API's station, its entry and the time of its value
Scoped = tuple[dict, OverviewStation, str | None]

# The characteristic values an overview gives per station: the record low and
# high, the means and the highest navigable water level
REFERENCE_VALUES = ("NNW", "MNW", "MW", "MHW", "HSW", "HHW")
# Tidal gauges have these instead of MNW and MHW, so the API rates them unknown
TIDAL_VALUES = {"MTnw", "MThw"}
# Most stations an overview lists: a flood across Germany, or several large
# rivers, stay below about 25 000 characters
MAX_STATIONS = 100
# The order of the counted states
STATES = get_args(WaterLevelState)


def overview_station(station: dict) -> tuple[OverviewStation, str | None] | None:
    """A station's entry with the time of its current value, or None if it
    has no water level W."""
    timeseries = normalize_timeseries(station)
    w = next((ts for ts in timeseries if ts.get("shortname") == "W"), None)
    if w is None:
        return None
    unit = w.get("unit")
    characteristic = [
        cv for cv in w.get("characteristicValues") or [] if isinstance(cv, dict)
    ]
    # Compared with W below, so only those in W's unit
    found = {
        cv.get("shortname"): series.compact_number(cv.get("value"))
        for cv in characteristic
        if cv.get("unit") == unit
    }
    values = {name: found[name] for name in REFERENCE_VALUES if name in found}
    current = current_measurement(w)
    value = series.compact_number(current["value"]) if current else None
    state_mnw_mhw = current["state_mnw_mhw"] if current else None
    state_nsw_hsw = current["state_nsw_hsw"] if current else None

    notes: list[str] = []
    # A disturbed or stale value says nothing about a record
    if value is not None and state_mnw_mhw not in ("commented", "out-dated"):
        nnw, hhw = values.get("NNW"), values.get("HHW")
        if nnw is not None and value < nnw:
            notes.append("below NNW")
        if hhw is not None and value > hhw:
            notes.append("above HHW")
    if state_nsw_hsw == "high":
        notes.append("above HSW")
    if TIDAL_VALUES & {cv.get("shortname") for cv in characteristic}:
        notes.append("tidal")

    entry: OverviewStation = {
        "uuid": station.get("uuid"),
        "station": station.get("longname"),
        "water": water_name(station),
        "km": station.get("km"),
        "value": value,
        "unit": unit,
        "state_mnw_mhw": state_mnw_mhw,
        "state_nsw_hsw": state_nsw_hsw,
        "characteristic_values": values,
        "notes": notes,
        "forecast": any(ts.get("shortname") == FORECAST_PARAMETER for ts in timeseries),
    }
    return entry, current["timestamp"] if current else None


def _water_names(station: dict) -> list[str]:
    """Short and long name of a station's water body, as the API writes them."""
    water = station.get("water")
    if not isinstance(water, dict):
        return []
    names = (water.get("shortname"), water.get("longname"))
    return [name for name in names if isinstance(name, str)]


def _unknown_water(name: str, stations: list[dict]) -> ToolError:
    """The error for a water body no station lies on, with similar names."""
    names = sorted({n for s in stations for n in _water_names(s)})
    similar = difflib.get_close_matches(name.upper(), names, n=3, cutoff=0.6)
    if similar:
        return caller_error(f"Unknown water {name!r}; did you mean {', '.join(similar)}?")
    return caller_error(
        f"Unknown water {name!r}; water bodies have German names (e.g., RHEIN, "
        "DONAU), which list_search_values lists for the field gewaesser."
    )


def _water_order(names: list[str], stations: list[dict]) -> dict[str, int]:
    """Each requested water body, as a casefolded name, to its position.

    Short and long names both match, regardless of case.
    """
    known = {n.casefold() for s in stations for n in _water_names(s)}
    order: dict[str, int] = {}
    for index, name in enumerate(names):
        if name.casefold() not in known:
            raise _unknown_water(name, stations)
        order.setdefault(name.casefold(), index)
    return order


def _km(entry: OverviewStation) -> float:
    """River kilometer of a station; stations without one sort last."""
    km = entry["km"]
    return km if isinstance(km, (int, float)) else math.inf


def _severity(entry: OverviewStation) -> int | None:
    """How notable a station is in an overview of Germany, 0 the most; None
    if not at all."""
    notes = entry["notes"]
    if "below NNW" in notes or "above HHW" in notes:
        return 0
    if "above HSW" in notes:
        return 1
    if entry["state_mnw_mhw"] == "high":
        return 2
    return None


def _count(entries: list[OverviewStation]) -> dict[str, int]:
    """Stations per state_mnw_mhw, in the order of STATES."""
    counter = Counter(e["state_mnw_mhw"] or "no value" for e in entries)
    return dict(sorted(
        counter.items(),
        key=lambda item: STATES.index(item[0]) if item[0] in STATES else len(STATES),
    ))


def _requested_waters(water: str | None) -> list[str]:
    """The names in water, which separates several by commas."""
    return [name.strip() for name in (water or "").split(",") if name.strip()]


def _in_scope(water: str | None, stations: list[dict]) -> list[Scoped]:
    """The stations with a water level on the requested water bodies, or
    across Germany: by the order of water, or by name, then by km."""
    names = _requested_waters(water)
    order = _water_order(names, stations) if names else None
    # (position of the water body, station, entry, time of the current value)
    scope: list[tuple[int, dict, OverviewStation, str | None]] = []
    for station in stations:
        position = 0
        if order is not None:
            positions = [
                order[name.casefold()]
                for name in _water_names(station)
                if name.casefold() in order
            ]
            if not positions:
                continue
            position = min(positions)
        overview = overview_station(station)
        if overview is not None:
            scope.append((position, station, *overview))
    scope.sort(key=lambda r: (
        r[0], "" if order is not None else r[2]["water"] or "", _km(r[2])
    ))
    return [(station, entry, time) for _, station, entry, time in scope]


def _overview(
    water: str | None,
    state: WaterLevelState | None,
    scope: list[Scoped],
    notable_only: bool,
) -> WaterLevelOverview:
    """Counts of all stations in scope and the listed ones: every station,
    or only the notable ones, most severe first; state filters the list."""
    entries = [entry for _, entry, _ in scope]
    if notable_only:
        ranked = [(rank, e) for e in entries if (rank := _severity(e)) is not None]
        # sorted is stable, so each rank keeps the order by water body and km
        listed = [e for _, e in sorted(ranked, key=lambda r: r[0])]
    else:
        listed = entries
    if state is not None:
        listed = [e for e in listed if e["state_mnw_mhw"] == state]
    shown = listed[:MAX_STATIONS]

    by_water: defaultdict[str, list[OverviewStation]] = defaultdict(list)
    for entry in entries:
        by_water[entry["water"] or "no water"].append(entry)
    times = [datetime.fromisoformat(t) for _, _, t in scope if t]
    return {
        "water": water,
        "state": state,
        "latest": max(times).isoformat(timespec="minutes") if times else None,
        "counts": _count(entries),
        "waters": {name: _count(group) for name, group in by_water.items()},
        "total_matches": len(listed),
        "returned": len(shown),
        "truncated": len(listed) > len(shown),
        "stations": shown,
    }


def water_level_of(entry: OverviewStation) -> MapWaterLevel:
    """The water level of an overview entry, as the maps show it."""
    return {
        "value": entry["value"],
        "unit": entry["unit"],
        "state_mnw_mhw": entry["state_mnw_mhw"],
        "notes": entry["notes"],
    }


async def get_water_level_overview(
    water: str | None = None, state: WaterLevelState | None = None
) -> WaterLevelOverview:
    """
    Overview of the current water levels (W) along whole water bodies or
    across Germany, from one request: e.g., "how is the Rhine?" or "where
    is low water now?". For chosen stations or other parameters, call
    compare_stations instead.

    With water, stations lists every station on those water bodies, by
    water body and river kilometer (km): a longitudinal section. Without
    water, it lists only the notable stations in Germany, most severe
    first: a record low or high (notes "below NNW", "above HHW"), above
    the highest navigable water level ("above HSW"), or state_mnw_mhw
    "high". state keeps only the stations in that state. counts and waters
    count all stations in scope per state_mnw_mhw, before that filter. At
    most 100 stations are listed; truncated says if there were more.

    Each station has its value in unit, both states as in
    get_latest_measurements, and those of NNW, MNW, MW, MHW, HSW and HHW
    it has. Tidal gauges stay "unknown" (note "tidal"), since their level
    swings with every tide. forecast marks the stations that
    get_water_level_forecast has a forecast for. W values of different
    stations are not comparable directly; compare their states and
    characteristic values. The values can be up to 5 minutes older than
    those of get_latest_measurements; latest is the newest measurement.

    Args:
        water: German short or long names of water bodies, several
            separated by commas (e.g., 'RHEIN' or 'Elbe, Saale'); default:
            all of Germany.
        state: Only the stations in this state_mnw_mhw, e.g. 'low'.
    """
    logger.info("get_water_level_overview: water=%s state=%s", water, state)
    scope = _in_scope(water, await client.all_water_levels())
    # A longitudinal section lists every station, Germany the notable ones
    result = _overview(water, state, scope, notable_only=not _requested_waters(water))
    logger.info(
        "get_water_level_overview: water=%s state=%s -> %d stations in scope, "
        "%d of %d listed",
        water, state, len(scope), result["returned"], result["total_matches"],
    )
    return result


async def show_water_level_map(
    water: str | None = None, state: WaterLevelState | None = None
) -> WaterLevelMap:
    """
    Show the user an interactive map of the current water levels (W) along
    whole water bodies or across Germany: every station in scope as a
    marker colored by its state, as in show_stations_map. In
    MCP-Apps-capable clients the map is rendered inline and loads its
    stations itself; you receive only the summary: counts and waters per
    state_mnw_mhw and the notable stations (record lows and highs, above
    HSW, high), as get_water_level_overview reports them for Germany. Its
    note says whether this client shows the map.

    For the value of every station, call get_water_level_overview; for the
    stations around a place, show_stations_map.

    Args:
        water: German short or long names of water bodies, several
            separated by commas (e.g., 'RHEIN' or 'Elbe, Saale'); default:
            all of Germany.
        state: Only the stations in this state_mnw_mhw, e.g. 'low'; the
            map shows no others.
    """
    logger.info("show_water_level_map: water=%s state=%s", water, state)
    scope = _in_scope(water, await client.all_water_levels())
    result = _overview(water, state, scope, notable_only=True)
    shown, client_name = client_renders_apps()
    logger.info(
        "show_water_level_map: water=%s state=%s -> %d stations in scope, "
        "%d notable; client %s declares %s: %s",
        water, state, len(scope), result["total_matches"], client_name,
        UI_EXTENSION_ID, shown,
    )
    return {**result, "note": MAP_SHOWN_NOTE if shown else MAP_NOT_SHOWN_NOTE}


async def get_water_level_map_stations(
    water: str | None = None, state: WaterLevelState | None = None
) -> ToolResult:
    """
    Only for the map UI of show_water_level_map, not for the model: every
    station in scope with its coordinates and current water level. For
    values to read or quote, call get_water_level_overview instead.

    Args:
        water: Names of water bodies, separated by commas; default: all of
            Germany.
        state: Only the stations in this state_mnw_mhw.
    """
    logger.info("get_water_level_map_stations: water=%s state=%s", water, state)
    scope = _in_scope(water, await client.all_water_levels())
    markers: list[WaterLevelMarker] = [
        {
            "uuid": entry["uuid"],
            "longname": entry["station"],
            "water": entry["water"],
            "km": entry["km"],
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "water_level": water_level_of(entry),
            "forecast": entry["forecast"],
        }
        for station, entry, _ in scope
        if state is None or entry["state_mnw_mhw"] == state
    ]
    logger.info(
        "get_water_level_map_stations: water=%s state=%s -> %d stations",
        water, state, len(markers),
    )
    # The stations go only into structuredContent: the text would send them
    # a second time, and the model reads only the text
    return ToolResult(
        content=f"{len(markers)} stations for the map UI; they are not meant for the model.",
        structured_content={"stations": markers},
    )


def register(mcp: FastMCP) -> None:
    """Register the overview tools on the server."""
    mcp.tool(get_water_level_overview, annotations=READ_ONLY)
    mcp.tool(
        show_water_level_map,
        app=AppConfig(resource_uri=MAP_UI_URI),
        annotations=READ_ONLY,
    )
    # Hidden from the model: its stations are meant for the map UI only
    mcp.tool(
        get_water_level_map_stations,
        app=AppConfig(visibility=["app"]),
        annotations=READ_ONLY,
    )
