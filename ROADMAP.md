# Roadmap

Backlog of technical and functional enhancements for the Pegelonline Dict API MCP server, based on a review of the current implementation in [server.py](server.py).

## Technical & code enhancements

| # | Status | Item | Notes |
|---|--------|------|-------|
| 1 | ✅ Done | Reuse a single `httpx.AsyncClient` (module-level or lifespan-managed) instead of opening a new one per call in all 6 tool/resource functions; add an explicit `httpx.Timeout` | Module-level client with a 30s timeout |
| 2 | ✅ Done | Centralize HTTP error handling — catch `httpx.HTTPStatusError` / `RequestError` / `TimeoutException` and return a clear message instead of letting raw exceptions propagate to the MCP client | Raised as `ToolError` in `_get_json`, with a dedicated hint for 404 (invalid UUID/parameter) |
| 3 | ✅ Done | Extract a shared `_get_json(url, params)` helper — all 6 functions currently duplicate the `async with httpx.AsyncClient() as client: ... raise_for_status() ... .json()` pattern | All tools and resources go through `_get_json` |
| 4 | ✅ Done | Remove unused `List` import from `typing` in [server.py](server.py) | |
| 5 | ✅ Done | Guard `search_stations` output size — a broad or empty query can return hundreds of stations and blow up LLM context; add a `limit`/`max_results` param or a summarized response mode | `limit` param (default 50); response reports `total_matches` / `returned` / `truncated`, and the aggregated MQTT/link lists are rebuilt from the truncated station list to stay consistent |
| 6 | ✅ Done | Fix `states://list` resource — it downloads *every* station via an unfiltered `/search` just to compute distinct `land` values on every single call; add a short in-memory TTL cache (states change essentially never) | In-memory cache with 6h TTL (~600ms → ~1ms on cache hit) |
| 7 | ✅ Done | Cache `water-bodies://list` too, same reasoning | Same 6h TTL cache |
| 8 | ✅ Done | `get_recent_measurements` pulls the *entire* measurement history for a parameter and slices the last N locally — check whether the official API supports `start`/`end` query params to fetch only the tail server-side | The API supports ISO-8601 periods (`start=PT90M`); the tool now fetches a window of `count × 30min` (min 1h) and only falls back to the full history if the window has gaps |
| 9 | ✅ Done | Make `BASE_URL` / `OFFICIAL_API_URL` overridable via environment variables (current hardcoded values as defaults) | `PEGELONLINE_DICT_API_URL` / `PEGELONLINE_API_URL` |
| 10 | Open | Add automated tests with `pytest` + `pytest-httpx` (or `respx`) mocking both upstream APIs — currently zero tests exist | Medium effort, biggest reliability win |
| 11 | Open | Add `ruff` (lint) and `mypy`/`pyright` (types) as dev dependencies | Low effort |
| 12 | Open | Add a GitHub Actions CI workflow: `uv sync` → ruff → pytest on push/PR | Low/medium effort, depends on #10/#11 |
| 13 | ✅ Done | Add structured `logging` for outgoing requests/responses to ease debugging tool calls made through Claude | Logs method/URL/params, status and duration to stderr; level configurable via `LOG_LEVEL` |
| 14 | Open | Add a `LICENSE` file — currently missing | Trivial |

## Functional enhancements (new tools/resources)

| # | Status | Item | Notes |
|---|--------|------|-------|
| 1 | ✅ Done | `get_station_info` tool — return one station's static metadata (name, agency, coordinates, water body, available parameters) without measurements | Returns uuid, number, names, agency, coordinates, river km, water body and the available parameters (shortname, longname, unit, equidistance, gauge zero) from the official API |
| 2 | Open | `get_measurement_history` tool — accept `start`/`end` date params for a bounded historical range, not just "last N" | Enables trend questions ("how did the level change last week?") |
| 3 | Open | `get_characteristic_values` tool — expose the official API's `/stations/{uuid}/{parameter}/characteristicvalues.json` (MNW/MHW/HSW etc.) | Lets the LLM say whether a current reading is high/low/normal — pairs directly with the `state` field `get_latest_measurements` already returns |
| 4 | ✅ Done | `find_nearest_stations` tool — nearest stations to a given lat/lon + radius | Uses the official API's server-side `latitude`/`longitude`/`radius` filter, then sorts nearest-first with a local haversine distance (`distance_km` included per station); `radius_km` and `limit` params with truncation metadata like `search_stations` |
| 5 | Open | `agencies://list` resource | Mirrors `water-bodies://list`/`states://list` for the `agency` search dimension, which is searchable but not browsable today |
| 6 | Open | `einzugsgebiete://list` resource | Same idea for catchment areas (`einzugsgebiet`) — completes resource coverage of all dict-API search dimensions |
| 7 | Open | `compare_stations` tool — fetch the same parameter's latest value across multiple UUIDs in one call | Avoids N round trips for "compare these 3 stations" questions |
| 8 | Open | Human-readable state translation — decode `stateMnwMhw`/`stateNswHsw` numeric codes into plain-language flood/low-water categories in tool output | Small effort, removes guesswork for the LLM/user |
| 9 | ✅ Done | `show_stations_map` tool — interactive inline map (MCP App) of all stations within a search radius | Leaflet + OpenStreetMap UI (`stations_map.html`) registered as `ui://pegelonline-dict/stations-map` and linked to the tool via `AppConfig`; renders inline in MCP-Apps-capable clients (radius circle, station markers with popups), other clients get the structured station list |
