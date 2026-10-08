"""Access to the upstream Pegelonline APIs (dict API and official REST API)."""

import logging

from config import BASE_URL, OFFICIAL_API_URL
from http_client import get_json

logger = logging.getLogger("pegelonline-dict")


async def search(params: dict | None = None) -> list[dict]:
    """Stations matching the dict API search filters; None values are ignored."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    data = await get_json(f"{BASE_URL}/search", params=params)
    return data.get("stations", [])


async def fetch_station(uuid: str, current: bool = False) -> dict:
    """Station metadata with its timeseries, optionally with current measurements."""
    params = {"includeTimeseries": "true"}
    if current:
        params["includeCurrentMeasurement"] = "true"
    return await get_json(f"{OFFICIAL_API_URL}/stations/{uuid}.json", params=params)


async def fetch_measurements(uuid: str, parameter: str, count: int) -> list[dict]:
    """The last ``count`` measurements of a station parameter, most recent first."""
    url = f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}/measurements.json"

    # Measurements are typically spaced 15 minutes apart. Request a window
    # twice that size server-side instead of downloading the full history,
    # and fall back to the full history if the window has gaps.
    window_minutes = max(count * 30, 60)
    data = await get_json(url, params={"start": f"PT{window_minutes}M"})
    if len(data) < count:
        logger.debug(
            "fetch_measurements: %dM window yielded %d < %d, fetching full history",
            window_minutes, len(data), count,
        )
        data = await get_json(url)

    # The API returns measurements in chronological order
    recent = data[-count:] if data else []
    recent.reverse()
    return recent


async def fetch_waters() -> list[dict]:
    """All water bodies known to the official API."""
    return await get_json(f"{OFFICIAL_API_URL}/waters.json")
