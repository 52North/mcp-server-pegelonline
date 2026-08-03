# Pegelonline Dict API MCP Server

An MCP Server that provides tools to search for gauge stations in Germany using the Pegelonline Dict API.

## Features

- **Search Tool**: Find stations by name, water body, agency, state, country, catchment area, district, observation parameter, or geographic bounding box.
- **FastMCP Integration**: Built with FastMCP for easy integration into the MCP ecosystem.

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
uv run fastmcp dev inspector server.py
```

To preview the MCP App UI (interactive station map) in the browser:
```bash
uv run fastmcp dev apps server.py
```

To run the server normally:
```bash
uv run python server.py
```

### Registering with Gemini CLI

To use this server with Gemini CLI, register it with the following command:

```bash
gemini mcp add pegelonline-dict -- uv --directory /path/to/mcp-server-pegelonline-dict-api run python server.py
```

*Note: Replace `/path/to/mcp-server-pegelonline-dict-api` with the absolute path to this project's directory.*

### Registering with Claude Code

The repository ships a project-scoped [`.mcp.json`](.mcp.json), so Claude Code picks the
server up automatically when started inside this directory. To register it manually
(e.g., with user scope):

```bash
claude mcp add pegelonline-dict -- uv --directory /path/to/mcp-server-pegelonline-dict-api run python server.py
```

Note: Claude Code is a CLI and does not render MCP Apps — the `show_stations_map`
tool falls back to its structured station list there.

### Registering with Claude Desktop

Claude Desktop supports MCP Apps, so `show_stations_map` renders the interactive
Leaflet map inline. Add the server to `%APPDATA%\Claude\claude_desktop_config.json`
(Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "pegelonline-dict": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-server-pegelonline-dict-api",
        "run", "python", "server.py"
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
   uv run fastmcp run server.py --transport http --port 8000
   ```
2. Expose it via a public HTTPS URL (for testing e.g. `cloudflared tunnel --url http://localhost:8000`;
   for production deploy it to a host).
3. In claude.ai open **Settings → Connectors → Add custom connector** and enter the
   MCP endpoint URL (FastMCP serves it under `/mcp`, e.g. `https://your-host/mcp`).
4. Enable the connector in a conversation. MCP Apps are rendered inline, so the
   station map works there as well.

## Tools

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

### `get_station_info`

Returns static metadata for a station by `uuid`: names, agency, coordinates,
river kilometer, water body and the available observation parameters
(shortname, longname, unit, measurement interval, gauge zero).

### `get_latest_measurements`

Returns the latest measurement of every parameter (e.g., water level, flow,
temperature) for a station by `uuid`.

### `get_recent_measurements`

Returns the most recent `count` measurements (default: 2) for one parameter
(`W`, `Q`, ...) of a station by `uuid`, most recent first.

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
`limit` (default: 50).

## Resources

- `water-bodies://list`: Returns a list of all available water bodies (Gewässer).
- `states://list`: Returns a list of all federal states (Bundesländer) that have gauge stations.
- `states://{state}/stations`: Returns a list of all stations within a specific federal state (e.g., `states://Nordrhein-Westfalen/stations`).
- `ui://pegelonline-dict/stations-map`: Leaflet map UI (`stations_map.html`) rendered inline by MCP-Apps-capable clients for the `show_stations_map` tool.

## Environment variables

- `PEGELONLINE_DICT_API_URL`: Override the Dict API base URL.
- `PEGELONLINE_API_URL`: Override the official Pegelonline REST API base URL.
- `LOG_LEVEL`: Logging level for the **stdio** runtime (`uv run python server.py`),
  written to stderr (default: `INFO`).

## Logging

Logs always go to **stderr** in the format `<time> <LEVEL> <logger> <message>`, so
they never interfere with the stdio JSON-RPC channel and are captured by journald
in production. The two runtimes are configured differently but share this format:

- **stdio (dev)** — `uv run python server.py` configures logging in-process; tune it
  with `LOG_LEVEL`.
- **HTTP / uvicorn (prod)** — logging is driven by a
  [`--log-config`](https://www.uvicorn.org/settings/#logging) file
  ([`packaging/log-config.yaml`](packaging/log-config.yaml)), which unifies the app,
  `uvicorn`, and access logs under one format. Edit that file (format string or
  levels) and restart to change production logging. Note the
  effective level in this mode comes from the file, not `LOG_LEVEL`.

  ```bash
  uv run uvicorn main:app --port 8000 --log-config packaging/log-config.yaml
  ```
