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
uv run fastmcp dev server.py
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

The API combines multiple parameters with a logical AND.

## Resources

- `water-bodies://list`: Returns a list of all available water bodies (Gewässer).
- `states://list`: Returns a list of all federal states (Bundesländer) that have gauge stations.
- `states://{state}/stations`: Returns a list of all stations within a specific federal state (e.g., `states://Nordrhein-Westfalen/stations`).
