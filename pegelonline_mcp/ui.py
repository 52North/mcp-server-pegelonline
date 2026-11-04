"""The MCP App UIs: the stations map and the measurements chart, rendered
inline by clients that support MCP Apps."""

import logging
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP

logger = logging.getLogger(__name__)

MAP_UI_URI = "ui://pegelonline-dict/stations-map"
CHART_UI_URI = "ui://pegelonline-dict/measurements-chart"


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
