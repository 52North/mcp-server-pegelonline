# Pegelonline MCP Server

An MCP server for gauge stations on German federal waterways: it finds stations via
the Pegelonline Dict API and reads their metadata and measurements from the official
Pegelonline REST API.

## Features

- **Station search**: `search_stations` filters by name, water body, agency, state,
  country, catchment area, district, observation parameter or bounding box;
  `find_nearest_stations` searches around a coordinate.
- **Station details**: `get_station_info` returns metadata and the observed
  parameters.
- **Measurements**: `get_latest_measurements` and `get_recent_measurements` return
  the latest values, `get_measurement_history` any span of the last 31 days as
  compact rows or hourly and daily summaries; all with unit and timeseries comment.
- **Characteristic values**: `get_characteristic_values` returns a water level's
  reference values (MNW, MW, MHW, HSW, record low and high, tidal values) with the
  current value, so a reading can be told high or low.
- **Charts**: `get_measurements_chart` returns the official line chart of such a
  span as an image for the model, about 480 image tokens whatever the span.
- **Interactive map**: `show_stations_map` renders the stations on a Leaflet map
  (MCP App) in Claude Desktop and claude.ai.
- **Resources**: water bodies, federal states and the stations per state.
- **Read-only**: every tool is annotated as read-only.
- **Deployment**: stdio for local clients, stateless Streamable HTTP for servers,
  packaged as an RPM for RHEL 9.

## Setup

### Prerequisites

- [uv](https://github.com/astral-sh/uv) installed on your system.

### Installation

1. Clone this repository (or copy the files).
2. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

To run the server in dev mode (with inspector):
```bash
uv run fastmcp dev inspector pegelonline_mcp/server.py
```

To preview the MCP App UI (interactive station map) in the browser:
```bash
uv run fastmcp dev apps pegelonline_mcp/server.py
```

To run the server normally (stdio transport):
```bash
uv run mcp-server-pegelonline
```
`uv sync` installs the `mcp-server-pegelonline` command; `uv run python -m pegelonline_mcp`
does the same.

Without a clone, `uvx` runs the server straight from GitHub:
```bash
uvx --from git+https://github.com/52North/mcp-server-pegelonline mcp-server-pegelonline
```
In the client registrations below, this command can replace
`uv --directory /path/to/mcp-server-pegelonline run mcp-server-pegelonline`.
`uvx` resolves the dependencies afresh instead of using `uv.lock`, so it may run newer
versions than the tested ones.

To run the tests (upstream APIs are mocked; tool responses are compared against
JSON snapshots in `tests/__snapshots__/`, refresh them with `--snapshot-update`):
```bash
uv run pytest
```

Lint and type checks (both configured in `pyproject.toml`, versions pinned in `uv.lock`):
```bash
uv run ruff check
uv run mypy
```

The CI workflow (`.github/workflows/ci.yml`) runs these checks, the tests and a
check that `packaging/requirements.txt` matches `uv.lock` on every push to
`master` and every pull request.

### Registering with Gemini CLI

To use this server with Gemini CLI, register it with the following command:

```bash
gemini mcp add pegelonline-dict -- uv --directory /path/to/mcp-server-pegelonline run mcp-server-pegelonline
```

*Note: Replace `/path/to/mcp-server-pegelonline` with the absolute path to this project's directory.*

### Registering with Claude Code

The repository ships a project-scoped [`.mcp.json`](.mcp.json), so Claude Code picks the
server up automatically when started inside this directory. To register it manually
(e.g., with user scope):

```bash
claude mcp add pegelonline-dict -- uv --directory /path/to/mcp-server-pegelonline run mcp-server-pegelonline
```

Note: Claude Code is a CLI and does not render MCP Apps — the `show_stations_map`
tool falls back to its structured station list there. Nor does it display images:
the chart from `get_measurements_chart` reaches only the model.

### Registering with Claude Desktop

Claude Desktop supports MCP Apps, so `show_stations_map` renders the interactive
Leaflet map inline. The chart from `get_measurements_chart`, by contrast, appears only
inside the expanded tool call. Add the server to `%APPDATA%\Claude\claude_desktop_config.json`
(Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "pegelonline-dict": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-server-pegelonline",
        "run", "mcp-server-pegelonline"
      ]
    }
  }
}
```

Use absolute paths; if Claude Desktop cannot find `uv`, use the absolute path to the
`uv` executable as `command`. Fully restart Claude Desktop afterwards (quit from the
tray icon, not just the window).

### Registering with claude.ai (web)

claude.ai cannot spawn local processes — the server must be reachable over HTTPS
using the Streamable HTTP transport:

1. Run the server with HTTP transport:
   ```bash
   uv run uvicorn pegelonline_mcp.asgi:app --port 8000 --log-config packaging/log-config.yaml
   ```
2. Expose it via a public HTTPS URL (for testing e.g. `cloudflared tunnel --url http://localhost:8000`;
   for production deploy it to a host).
3. In claude.ai open **Settings → Connectors → Add custom connector** and enter the
   MCP endpoint URL (FastMCP serves it under `/mcp`, e.g. `https://your-host/mcp`).
4. Enable the connector in a conversation. MCP Apps are rendered inline, so the
   station map works there as well.

## Tools

All tools only read from the Pegelonline APIs and are annotated with
`readOnlyHint` and `openWorldHint`, so clients can allow them without asking
for confirmation.

Each tool except `get_measurements_chart` publishes an output schema that describes
its response, generated from the types in
[`pegelonline_mcp/models.py`](pegelonline_mcp/models.py). The server validates every
such response against it. Fields taken from the upstream APIs may be `null`, since
some stations lack e.g. coordinates or a district. `get_measurements_chart` returns
MCP image content (`image/png`) instead.

### `search_stations`

Searches for stations with the following optional parameters:
- `station`: Station name (e.g., 'Köln').
- `gewaesser`: Water body (e.g., 'Rhein').
- `agency`: Competent agency (e.g., 'Dresden').
- `land`: Federal state (e.g., 'Hamburg').
- `country`: Country (e.g., 'Deutschland').
- `einzugsgebiet`: Catchment area (e.g., 'Ems').
- `kreis`: District (e.g., 'Emsland').
- `parameter`: Observation parameter (e.g., 'Wassertemperatur').
- `bbox`: Bounding box (minLon, minLat, maxLon, maxLat).
- `q`: General search query.

The API combines multiple parameters with a logical AND. An optional `limit`
(default: 50) caps the number of returned stations; the response reports
`total_matches` and `truncated` so cut-off results are visible.

Text filters match case-insensitive substrings, also of alternative (e.g.,
English) names: `land='Sachsen'` also returns stations in Niedersachsen and
Sachsen-Anhalt.

Each station is returned in compact form: UUID, names, agency, water body,
coordinates, MQTT topic, observation parameters and its `country`, `land`,
`kreis` and `einzugsgebiet`, so exact matches can be checked. Further details
come from `get_station_info`.

### `get_station_info`

Returns static metadata for a station by `uuid`: names, agency, coordinates,
river kilometer, water body and the available observation parameters
(shortname, longname, unit, measurement interval, gauge zero, comment).

### `get_latest_measurements`

Returns the latest measurement of every parameter (e.g., water level, flow,
temperature) for a station by `uuid`, each with the comment on its timeseries
(e.g., a disturbance or why discharge is currently not determined). Water levels
also report two states: `state_mnw_mhw` relative to mean low and mean high
water, and `state_nsw_hsw` relative to the highest navigable water level.

### `get_characteristic_values`

Returns the characteristic values (Kennwerte) of one parameter of a station by
`uuid` (`parameter` defaults to `W`) together with its current value and both
states, from a single request. Only water levels have characteristic values,
about three quarters of them; other parameters return an empty list. Each value
has `shortname`, `longname`, `value` and `unit`, plus `valid_from` for fixed
values (HSW, flood marks), `timespan_start`/`timespan_end` for statistics (MNW,
MW, MHW) or `occurrences` for extremes (NNW, HHW; dates or only years). They
come in the API's order, since not all are water levels: TuGLW is a fairway
depth, and on canals OBW and UBW are heights in `m` while W is in `m+NN`.

### `get_recent_measurements`

Returns the most recent `count` measurements (default: 2, at most 100) for one
parameter (`W`, `Q`, ...) of a station by `uuid`, most recent first. Time spans
are left to `get_measurement_history`, as the measurement interval differs
between timeseries (1, 5, 10, 15 or 60 minutes). The response also carries the
timeseries' `unit`, which differs between stations (e.g., W in `cm` or `m+NN`,
conductivity in `µS/cm` or `mS/cm`), and its `comment`, if any.

### `get_measurement_history`

Returns the measurements of one parameter of a station over a time span, oldest
first: the last `hours` (default: 24) or a window from `start` to `end` (ISO 8601
with UTC offset, both included; `end` defaults to now). A window spans at most
840 hours and starts at most 35 days back; the official API keeps a little over
31 days.

The values come in rows. Each key is the start of an hour in German local time
(CET/CEST) with its UTC offset, and `columns` gives each slot's offset from it in
minutes; 1-minute series use rows of 10 minutes. `null` marks a missing value,
rows without any value are left out, and the hour repeated when daylight saving
time ends appears twice, once with `+02:00` and once with `+01:00`:

```json
{
  "columns": ["+0", "+15", "+30", "+45"],
  "rows": {
    "2026-10-06T12:00+02:00": [48, 48, null, 49],
    "2026-10-06T13:00+02:00": [49, 49, 50, 50]
  }
}
```

`resolution` selects the rows, and the response reports which ones it holds:
- `auto` (default): raw values while the rows hold at most 3360 slots (35 days of
  a 15-minute series), otherwise as `hour`. The whole history of 15- and
  60-minute series always comes raw.
- `raw`: raw values; beyond 3360 slots only the newest rows, with `truncated`.
- `hour`, `day`: `min`, `mean` and `max` per hour or calendar day.

Raw rows need the values on the series' grid. Without a known interval, or with
values off the grid, `auto` and `raw` summarize per hour.

`summary` covers all values of the span in any case: `count`, `missing` grid
slots between the first and last value, `first`, `last`, `min` and `max` with
their timestamps, and `mean`. The response also carries the timeseries' `unit`,
`comment` and `interval_minutes`.

The largest responses reach about 48 000 characters. The tool sets
`_meta["anthropic/maxResultSizeChars"]` to 60 000, so Claude Code keeps them in
context instead of moving them to a file.

### `get_measurements_chart`

Returns the official API's line chart of one parameter of a station as a PNG image
(900 × 400 pixels), for the same time spans as `get_measurement_history`: the last
`hours` (default: 24) or a window from `start` to `end`. The model sees the course
at a glance, with gaps and labeled reference lines such as NNW or MThw, for about
480 image tokens whatever the span; the PNG itself grows to about 190 KB for 35 days
of a 1-minute series. Exact values come from `get_measurement_history`.

The chart has no title, unit or legend: the y-axis shows the values in the
timeseries' unit with a decimal comma, the x-axis German local time. A span without
values gives an empty grid, not an error. Some gauges add a dashed line, e.g. a
forecast; the measured values are the solid line.

The tool sends a single request, so an unknown station or parameter fails with the
usual 404 hint, and a response that is not `image/png` becomes an error.

### `find_nearest_stations`

Returns gauge stations around a coordinate (`latitude`, `longitude`),
filtered by `radius_km` (default: 25) and sorted nearest-first with a
`distance_km` per station. `limit` defaults to 10.

### `show_stations_map`

Shows an **interactive map** (MCP App) of all stations within a search radius
around a coordinate. In clients that support MCP Apps (e.g., Claude Desktop,
claude.ai) the map is rendered inline: OpenStreetMap tiles, a circle for the
search radius and clickable station markers with name, water body, distance
and UUID. Clients without MCP Apps support receive the structured station
list instead. Parameters: `latitude`, `longitude`, `radius_km` (default: 25),
`limit` (default: 50). The map loads Leaflet from unpkg pinned by subresource
integrity hashes and only accepts messages from its host frame.

## Resources

- `water-bodies://list`: Returns a list of all available water bodies (Gewässer).
- `states://list`: Returns a list of all federal states (Bundesländer) that have gauge stations.
- `states://{state}/stations`: Returns a list of all stations within a specific federal state (e.g., `states://Nordrhein-Westfalen/stations`).
- `ui://pegelonline-dict/stations-map`: Leaflet map UI (`pegelonline_mcp/static/stations_map.html`) rendered inline by MCP-Apps-capable clients for the `show_stations_map` tool.

## Environment variables

- `PEGELONLINE_DICT_API_URL`: Override the Dict API base URL.
- `PEGELONLINE_API_URL`: Override the official Pegelonline REST API base URL.
- `LOG_LEVEL`: Logging level for the **stdio** runtime (`uv run mcp-server-pegelonline`),
  written to stderr (default: `INFO`).
- `FASTMCP_LOG_ENABLED`: Defaults to `false`, so FastMCP's own messages go through the
  logging setup below and share its format; `true` brings back FastMCP's Rich console
  output.
- `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`: The standard proxy variables are honored for
  requests to the upstream APIs.

## Logging

Logs always go to **stderr** in the format `<time> <LEVEL> <logger> <message>`, so
they never interfere with the stdio JSON-RPC channel and are captured by journald
in production. The two runtimes are configured differently but share this format:

- **stdio (dev)** — `uv run mcp-server-pegelonline` configures logging in-process; tune it
  with `LOG_LEVEL`.
- **HTTP / uvicorn (prod)** — logging is driven by a
  [`--log-config`](https://www.uvicorn.org/settings/#logging) file
  ([`packaging/log-config.yaml`](packaging/log-config.yaml)), which unifies the app,
  `uvicorn`, and access logs under one format. Edit that file (format string or
  levels) and restart to change production logging. Note the
  effective level in this mode comes from the file, not `LOG_LEVEL`.

  ```bash
  uv run uvicorn pegelonline_mcp.asgi:app --port 8000 --log-config packaging/log-config.yaml
  ```

Both runtimes silence the per-request INFO logs of `httpx` and `mcp.server.lowlevel`,
since the application logs each upstream request itself.
