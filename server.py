from fastmcp import FastMCP
import httpx
from typing import Optional

# Initialize FastMCP server
mcp = FastMCP("Pegelonline Dict API")

BASE_URL = "https://dict-api.pegelonline.wsv.de"

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

if __name__ == "__main__":
    mcp.run()
