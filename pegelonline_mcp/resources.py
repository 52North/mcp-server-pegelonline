"""Resources: water bodies, states, agencies and catchment areas, the stations
per state and the map UI."""

import logging
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP

from pegelonline_mcp import client
from pegelonline_mcp.cache import cached
from pegelonline_mcp.mapping import water_name

logger = logging.getLogger(__name__)

MAP_UI_URI = "ui://pegelonline-dict/stations-map"


def stations_map_ui() -> str:
    """Leaflet map UI rendered inline for the show_stations_map tool."""
    logger.info("stations_map_ui: serving Leaflet map resource %s", MAP_UI_URI)
    return (Path(__file__).parent / "static" / "stations_map.html").read_text(encoding="utf-8")


@cached("water-bodies")
async def list_water_bodies() -> str:
    """List all available water bodies (Gewässer)."""
    waters = await client.fetch_waters()
    result = "\n".join(_water_line(w) for w in waters)
    logger.info("list_water_bodies: fetched and cached %d water bodies", len(waters))
    return result


@cached("stations")
async def all_stations() -> list[dict]:
    """Every station of the dict API, shared by the lists of their field values."""
    stations = await client.search()
    logger.info("all stations: fetched and cached %d stations", len(stations))
    return stations


async def _distinct(field: str) -> list[str]:
    """Sorted distinct values of a station field; stations without it are skipped."""
    return sorted({s[field] for s in await all_stations() if s.get(field)})


async def list_states() -> str:
    """List all federal states (Bundesländer) that have stations."""
    states = await _distinct("land")
    logger.info("list_states: %d states", len(states))
    return "\n".join(states)


async def list_agencies() -> str:
    """List all agencies (WSV locations and other operators) that run stations."""
    agencies = await _distinct("agency")
    logger.info("list_agencies: %d agencies", len(agencies))
    return "\n".join(agencies)


async def list_catchment_areas() -> str:
    """List all catchment areas (Einzugsgebiete) that have stations."""
    areas = await _distinct("einzugsgebiet")
    logger.info("list_catchment_areas: %d catchment areas", len(areas))
    return "\n".join(areas)


async def list_stations_in_state(state: str) -> str:
    """List all stations in a specific federal state."""
    logger.info("list_stations_in_state: state=%s", state)
    # The dict API matches `land` as a substring, also of the alternative
    # names, so "Sachsen" returns Niedersachsen and Sachsen-Anhalt as well.
    matches = await client.search({"land": state})
    stations = [s for s in matches if _in_state(s, state)]
    logger.info(
        "list_stations_in_state: state=%s -> %d stations (%d upstream matches)",
        state, len(stations), len(matches),
    )
    return "\n".join(_station_line(s) for s in stations)


def _in_state(station: dict, state: str) -> bool:
    """Whether ``state`` is the station's state, by name or alternative name."""
    names = [station.get("land")]
    if isinstance(station.get("land_alternatives"), list):
        names += station["land_alternatives"]
    return state.casefold() in {n.casefold() for n in names if isinstance(n, str)}


def _water_line(water: dict) -> str:
    """One line of the water body list; the short name is omitted if unknown."""
    line = f"{water.get('longname')}"
    if water.get("shortname"):
        line += f" ({water['shortname']})"
    return line


def _station_line(station: dict) -> str:
    """One line of the station list; the water body is omitted if unknown."""
    details = f"UUID: {station.get('uuid')}"
    water = water_name(station)
    if water:
        details += f", Gewässer: {water}"
    return f"{station.get('longname')} ({details})"


def register(mcp: FastMCP) -> None:
    """Register the resources on the server."""
    mcp.resource(
        MAP_UI_URI,
        mime_type=UI_MIME_TYPE,
        app=AppConfig(
            csp=ResourceCSP(
                resource_domains=[
                    "https://unpkg.com",
                    "https://tile.openstreetmap.org",
                ],
            ),
            prefers_border=True,
        ),
    )(stations_map_ui)
    mcp.resource("water-bodies://list")(list_water_bodies)
    mcp.resource("states://list")(list_states)
    mcp.resource("states://{state}/stations")(list_stations_in_state)
    mcp.resource("agencies://list")(list_agencies)
    mcp.resource("catchment-areas://list")(list_catchment_areas)
