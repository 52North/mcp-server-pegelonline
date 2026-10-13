"""The FastMCP server: client instructions, tools, resources and /healthz."""

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from pegelonline_mcp import resources, tools_measurements, tools_stations

logger = logging.getLogger(__name__)

# Server-wide guidance sent to clients on initialize; complements the
# per-tool docstrings with workflow hints and domain pitfalls.
INSTRUCTIONS = """\
Gauge stations (Pegel) on German federal waterways from Pegelonline (WSV).
Only federal waterways are covered; smaller rivers and streams have no stations here.

Workflow:
- Locate stations with search_stations (by name, water body, state, ...) or,
  for a place or coordinate, with find_nearest_stations. Use show_stations_map
  instead when the user asks for a map.
- The location tools expect WGS84 coordinates, not place names: resolve the
  place to latitude/longitude yourself before calling them.
- Use the station uuid from those results for get_station_info,
  get_latest_measurements and get_recent_measurements.
- Measurement intervals differ per timeseries (equidistance_minutes in
  get_station_info: mostly 15 minutes, often 1 or 60). For a time span, call
  get_recent_measurements with hours (e.g., hours=24) instead of estimating a
  count. A span returns at most the 1440 most recent values (24 hours of a
  1-minute series, 15 days of a 15-minute one); truncated=true marks a cut.

Interpreting values:
- Water level W in cm is relative to the station's gauge zero (Pegelnullpunkt),
  not water depth. Absolute height = gaugeZero (m above NHN) + W / 100.
  Some stations, mostly on canals, report W directly in m+NN; the unit
  returned with every measurement tool's values tells which.
- Discharge Q may be missing, stale or unreliable at low water; compare
  timestamps. get_latest_measurements, get_recent_measurements and
  get_station_info return a comment per timeseries that explains such cases
  and reports disturbances or stations out of service.
- Measurements are raw data (Rohdaten) and unverified; small jumps of about
  1 cm are usually measurement noise.
"""

mcp = FastMCP("Pegelonline Dict API", instructions=INSTRUCTIONS)

tools_stations.register(mcp)
tools_measurements.register(mcp)
resources.register(mcp)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> PlainTextResponse:
    """Liveness probe for a load balancer.

    The MCP endpoint (/mcp) requires a JSON-RPC handshake, so it is unsuitable
    as an LB health check. This lightweight route returns 200 OK instead.
    """
    # DEBUG only: the LB polls this frequently and uvicorn's access log already
    # records each hit, so INFO here would be pure noise.
    logger.debug("healthz: liveness probe")
    return PlainTextResponse("ok")
