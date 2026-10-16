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
- When a search_stations filter finds nothing or too much, look up its values
  with list_search_values (e.g., the short names gewaesser and parameter take).
- The location tools expect WGS84 coordinates, not place names: resolve the
  place to latitude/longitude yourself before calling them.
- Use the station uuid from those results for get_station_info and the
  measurement tools: get_latest_measurements, get_characteristic_values,
  get_recent_measurements, get_measurement_history and get_measurements_chart.
  For the current value of one parameter at several stations, call
  compare_stations once instead of get_latest_measurements per station.
- For a time span (e.g., the last 24 hours, a week or a past day), call
  get_measurement_history instead of estimating a count for
  get_recent_measurements: measurement intervals differ per timeseries (1, 5,
  10, 15 or 60 minutes; equidistance_minutes in get_station_info). The
  official API keeps a little over 31 days. Long spans of short-interval
  series come as hourly min/mean/max; resolution in the response says so.
- To see how a parameter developed (trend, peaks, reference lines such as
  NNW), call get_measurements_chart: a chart image that costs the same few
  hundred tokens for any span. Take exact values from get_measurement_history,
  and describe the chart in words, since the user may not see it.

Interpreting values:
- Water level W in cm is relative to the station's gauge zero (Pegelnullpunkt),
  not water depth. Absolute height = gaugeZero (m above NHN) + W / 100.
  Some stations, mostly on canals, report W directly in m+NN; the unit
  returned with the measured values tells which. W values of different
  stations are therefore not comparable directly; compare states,
  characteristic values or absolute heights instead.
- To tell how high or low a water level is, compare it with the
  characteristic values from get_characteristic_values (e.g., MNW, MW, MHW,
  HSW, the record low NNW and high HHW); state_mnw_mhw and state_nsw_hsw
  give only a rough class.
- Discharge Q may be missing, stale or unreliable at low water; compare
  timestamps. get_station_info, get_latest_measurements,
  get_recent_measurements and get_measurement_history return a comment per
  timeseries that explains such cases and reports disturbances or stations
  out of service.
- Measurements are raw data (Rohdaten) and unverified; small jumps of about
  1 cm are usually measurement noise.
"""

mcp = FastMCP("Pegelonline", instructions=INSTRUCTIONS)

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
