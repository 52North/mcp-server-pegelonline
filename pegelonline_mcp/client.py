"""Access to the upstream Pegelonline APIs (dict API and official REST API)."""

import logging
import math
from datetime import datetime, timedelta
from urllib.parse import quote

from fastmcp.exceptions import ToolError

from pegelonline_mcp.config import BASE_URL, OFFICIAL_API_URL
from pegelonline_mcp.http_client import get_json, get_png
from pegelonline_mcp.models import Measurement

logger = logging.getLogger(__name__)

# The official API keeps a little over 31 days of raw measurements, but
# without `start` it returns only the last 10 days. A 35-day period reaches
# back to the oldest kept value.
HISTORY_MINUTES = 35 * 24 * 60

# Interval assumed for a timeseries that reports none; most series are
# spaced 15 minutes apart
DEFAULT_INTERVAL_MINUTES = 15

# Chart size in pixels. Claude counts an image as about width × height / 750
# tokens, so a chart costs about 480 whatever its span.
CHART_WIDTH = 900
CHART_HEIGHT = 400


async def search(params: dict | None = None) -> list[dict]:
    """Stations matching the dict API search filters."""
    data = await get_json(f"{BASE_URL}/search", params=params)
    return data.get("stations", [])


def _segment(value: str) -> str:
    """``value`` escaped as a single URL path segment.

    Escaping keeps "/", "?" and "#" from changing the URL. Segments of only
    dots would still be resolved as relative paths, so they are rejected.
    """
    if not value.strip("."):
        raise ToolError(f"Invalid station or parameter identifier: {value!r}")
    return quote(value, safe="")


async def fetch_station(uuid: str, current: bool = False) -> dict:
    """Station metadata with its timeseries, optionally with current measurements."""
    params = {"includeTimeseries": "true"}
    if current:
        params["includeCurrentMeasurement"] = "true"
    url = f"{OFFICIAL_API_URL}/stations/{_segment(uuid)}.json"
    return await get_json(url, params=params)


def _timeseries_url(uuid: str, parameter: str) -> str:
    """Base URL of a station parameter (timeseries), without suffix."""
    return f"{OFFICIAL_API_URL}/stations/{_segment(uuid)}/{_segment(parameter)}"


def _measurements_url(uuid: str, parameter: str) -> str:
    """URL of the measurements of a station parameter."""
    return f"{_timeseries_url(uuid, parameter)}/measurements.json"


async def fetch_timeseries(uuid: str, parameter: str) -> dict:
    """Metadata of a station parameter: unit, interval, gauge zero and comment."""
    return await get_json(f"{_timeseries_url(uuid, parameter)}.json")


async def fetch_measurements(
    uuid: str, parameter: str, count: int, interval_minutes: int | None = None
) -> list[Measurement]:
    """The last ``count`` measurements of a station parameter, most recent first.

    ``interval_minutes`` is the measurement interval of the timeseries
    (``equidistance``); without it, 15 minutes are assumed.
    """
    url = _measurements_url(uuid, parameter)

    # Request a window twice the span ``count`` values cover at the series'
    # interval server-side instead of downloading the full history, and
    # fall back to the full history if the window has gaps. A window that
    # already spans the full history needs no fallback.
    if not isinstance(interval_minutes, int) or interval_minutes < 1:
        interval_minutes = DEFAULT_INTERVAL_MINUTES
    window_minutes = min(max(count * interval_minutes * 2, 60), HISTORY_MINUTES)
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


def _window_params(start: datetime | timedelta, end: datetime | None) -> dict[str, str]:
    """Query parameters of a time window from ``start`` to ``end``, both included.

    Like the API's own ``start``, ``start`` is a timestamp or a span back from
    now, rounded up to whole minutes. Without ``end``, the window reaches up
    to now.
    """
    if isinstance(start, timedelta):
        params = {"start": f"PT{math.ceil(start / timedelta(minutes=1))}M"}
    else:
        params = {"start": start.isoformat()}
    if end is not None:
        params["end"] = end.isoformat()
    return params


async def fetch_measurements_since(
    uuid: str, parameter: str, start: datetime | timedelta, end: datetime | None = None
) -> list[Measurement]:
    """Measurements of a station parameter in a time window, see ``_window_params``.

    Oldest first, as the API returns them.
    """
    url = _measurements_url(uuid, parameter)
    return await get_json(url, params=_window_params(start, end))


async def fetch_measurements_chart(
    uuid: str, parameter: str, start: datetime | timedelta, end: datetime | None = None
) -> bytes:
    """PNG line chart of a station parameter in a time window, see ``_window_params``."""
    url = f"{_timeseries_url(uuid, parameter)}/measurements.png"
    params = {
        **_window_params(start, end),
        "width": str(CHART_WIDTH),
        "height": str(CHART_HEIGHT),
    }
    return await get_png(url, params=params)


async def fetch_waters() -> list[dict]:
    """All water bodies known to the official API."""
    return await get_json(f"{OFFICIAL_API_URL}/waters.json")
