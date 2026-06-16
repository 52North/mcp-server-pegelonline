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

@mcp.tool()
async def get_latest_measurements(uuid: str) -> dict:
    """
    Fetch the latest measurements (e.g., water level, flow, temperature) for a specific station.
    
    Args:
        uuid: The unique identifier (UUID) of the station.
    """
    url = f"{OFFICIAL_API_URL}/stations/{uuid}.json"
    params = {
        "includeTimeseries": "true",
        "includeCurrentMeasurement": "true"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Clean up the response to only return relevant measurement data
        measurements = []
        for ts in data.get("timeseries", []):
            curr = ts.get("currentMeasurement")
            if curr:
                measurements.append({
                    "parameter": ts.get("longname"),
                    "shortname": ts.get("shortname"),
                    "value": curr.get("value"),
                    "unit": ts.get("unit"),
                    "timestamp": curr.get("timestamp"),
                    "state": curr.get("stateMnwMhw") or curr.get("stateNswHsw")
                })
        
        return {
            "station": data.get("longname"),
            "water": data.get("water", {}).get("longname"),
            "measurements": measurements
        }

@mcp.tool()
async def get_recent_measurements(uuid: str, parameter: str, count: int = 2) -> dict:
    """
    Fetch the most recent measurements for a specific parameter of a station.
    
    Args:
        uuid: The unique identifier (UUID) of the station.
        parameter: The shortname of the parameter (e.g., 'W' for water level, 'Q' for flow).
        count: Number of recent measurements to fetch (default: 2).
    """
    url = f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}/measurements.json"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        
        # The API returns measurements in chronological order, so we take the last 'count' items
        recent = data[-count:] if data else []
        recent.reverse() # Most recent first
        
        return {
            "uuid": uuid,
            "parameter": parameter,
            "measurements": recent
        }

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
