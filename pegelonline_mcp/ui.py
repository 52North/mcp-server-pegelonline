"""The MCP App UIs: the stations map and the measurements chart, rendered
inline by clients that support MCP Apps."""

import logging
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import UI_EXTENSION_ID, UI_MIME_TYPE, AppConfig, ResourceCSP
from fastmcp.server.dependencies import get_context

logger = logging.getLogger(__name__)

MAP_UI_URI = "ui://pegelonline-dict/stations-map"
CHART_UI_URI = "ui://pegelonline-dict/measurements-chart"


def client_renders_apps() -> tuple[bool, str | None]:
    """Whether the client declared MCP Apps, and its name for the log."""
    try:
        ctx = get_context()
        params = ctx.session.client_params
    except RuntimeError:
        return False, None
    name = params.client_info.name if params is not None else None
    return ctx.client_supports_extension(UI_EXTENSION_ID), name


def stations_map_ui() -> str:
    """Leaflet map UI rendered inline for the show_stations_map tool."""
    logger.info("stations_map_ui: serving Leaflet map resource %s", MAP_UI_URI)
    return (Path(__file__).parent / "static" / "stations_map.html").read_text(encoding="utf-8")


def measurements_chart_ui() -> str:
    """Chart UI rendered inline for the show_measurements_chart tool."""
    logger.info("measurements_chart_ui: serving chart resource %s", CHART_UI_URI)
    return (Path(__file__).parent / "static" / "measurements_chart.html").read_text(
        encoding="utf-8"
    )


def register(mcp: FastMCP) -> None:
    """Register the UI resources on the server."""
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
    mcp.resource(
        CHART_UI_URI,
        mime_type=UI_MIME_TYPE,
        app=AppConfig(
            csp=ResourceCSP(resource_domains=["https://unpkg.com"]),
            prefers_border=True,
        ),
    )(measurements_chart_ui)
