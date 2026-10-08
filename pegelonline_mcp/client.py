"""Access to the upstream Pegelonline APIs (dict API and official REST API)."""

import logging

from pegelonline_mcp.config import BASE_URL, OFFICIAL_API_URL
from pegelonline_mcp.http_client import get_json

logger = logging.getLogger("pegelonline-dict")

# The official API keeps a little over 31 days of raw measurements, but
# without `start` it returns only the last 10 days. A 35-day period reaches
# back to the oldest kept value.
HISTORY_MINUTES = 35 * 24 * 60


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


def _measurements_url(uuid: str, parameter: str) -> str:
    """URL of the measurements of a station parameter."""
    return f"{OFFICIAL_API_URL}/stations/{uuid}/{parameter}/measurements.json"


async def fetch_measurements(uuid: str, parameter: str, count: int) -> list[dict]:
    """The last ``count`` measurements of a station parameter, most recent first."""
    url = _measurements_url(uuid, parameter)

    # Measurements are typically spaced 15 minutes apart. Request a window
    # twice that size server-side instead of downloading the full history,
    # and fall back to the full history if the window has gaps. A window
    # that already spans the full history needs no fallback.
    window_minutes = min(max(count * 30, 60), HISTORY_MINUTES)
    data = await get_json(url, params={"start": f"PT{window_minutes}M"})
    if len(data) < count and window_minutes < HISTORY_MINUTES:
        logger.debug(
            "fetch_measurements: %dM window yielded %d < %d, fetching full history",
            window_minutes, len(data), count,
        )
        data = await get_json(url, params={"start": f"PT{HISTORY_MINUTES}M"})

    # The API returns measurements in chronological order
    recent = data[-count:] if data else []
    recent.reverse()
    return recent


async def fetch_measurements_within(
    uuid: str, parameter: str, minutes: int
) -> list[dict]:
    """Measurements of a station parameter within the last ``minutes``.

    Most recent first, like ``fetch_measurements``.
    """
    url = _measurements_url(uuid, parameter)
    data = await get_json(url, params={"start": f"PT{minutes}M"})
    return data[::-1]


async def fetch_waters() -> list[dict]:
    """All water bodies known to the official API."""
    return await get_json(f"{OFFICIAL_API_URL}/waters.json")
