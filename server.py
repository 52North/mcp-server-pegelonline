from fastmcp import FastMCP
import httpx
from typing import Optional, List

# Initialize FastMCP server
mcp = FastMCP("Pegelonline Dict API")

BASE_URL = "https://dict-api.pegelonline.wsv.de"
OFFICIAL_API_URL = "https://pegelonline.wsv.de/webservices/rest-api/v2"

@mcp.tool()
async def search_stations(
    station: Optional[str] = None,
    gewaesser: Optional[str] = None,
    agency: Optional[str] = None,
    land: Optional[str] = None,
    country: Optional[str] = None,
    einzugsgebiet: Optional[str] = None,
    kreis: Optional[str] = None,
    parameter: Optional[str] = None,
    bbox: Optional[str] = None,
    q: Optional[str] = None
) -> dict:
    """
    Search for Pegelonline stations using various optional parameters.
    Multiple parameters are combined with AND.
    
    Args:
        station: Search by station name (e.g., 'Köln').
        gewaesser: Search by water body (e.g., 'Rhein').
        agency: Search by agency (e.g., 'Dresden').
        land: Search by state/land (e.g., 'Hamburg').
        country: Search by country (e.g., 'Deutschland').
        einzugsgebiet: Search by catchment area (e.g., 'Ems').
        kreis: Search by district/county (e.g., 'Emsland').
        parameter: Search by observation parameter (e.g., 'Wassertemperatur').
        bbox: Search by bounding box (minLon, minLat, maxLon, maxLat, e.g., '7,52,8,53').
        q: General search across all parameters.
    """
    params = {
        "station": station,
        "gewaesser": gewaesser,
        "agency": agency,
        "land": land,
        "country": country,
        "einzugsgebiet": einzugsgebiet,
        "kreis": kreis,
        "parameter": parameter,
        "bbox": bbox,
        "q": q
    }
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/search", params=params)
        response.raise_for_status()
        return response.json()

@mcp.resource("water-bodies://list")
async def list_water_bodies() -> str:
    """List all available water bodies (Gewässer)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{OFFICIAL_API_URL}/waters.json")
        response.raise_for_status()
        waters = response.json()
        return "\n".join([f"{w['longname']} ({w['shortname']})" for w in waters])

@mcp.resource("states://list")
async def list_states() -> str:
    """List all federal states (Bundesländer) that have stations."""
    async with httpx.AsyncClient() as client:
        # We fetch all stations from the dict-api to get unique states
        response = await client.get(f"{BASE_URL}/search")
        response.raise_for_status()
        data = response.json()
        states = sorted(list(set(s.get("land") for s in data.get("stations", []) if s.get("land"))))
        return "\n".join(states)

@mcp.resource("states://{state}/stations")
async def list_stations_in_state(state: str) -> str:
    """List all stations in a specific federal state."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/search", params={"land": state})
        response.raise_for_status()
        data = response.json()
        stations = data.get("stations", [])
        return "\n".join([f"{s['longname']} (UUID: {s['uuid']}, Gewässer: {s['water']['longname']})" for s in stations])

if __name__ == "__main__":
    mcp.run()
