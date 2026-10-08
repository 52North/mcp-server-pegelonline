"""Shared HTTP client for the upstream APIs.

Not named ``http.py``: in the flat module layout that would shadow the
standard library ``http`` package that httpx, starlette and uvicorn import.
"""

import logging
import time
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

logger = logging.getLogger("pegelonline-dict")

# Shared client for all requests; the process lifetime bounds its lifecycle
http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))


async def get_json(url: str, params: dict | None = None) -> Any:
    """GET a JSON document, translating transport errors into clear MCP errors."""
    logger.info("GET %s params=%s", url, params)
    start = time.monotonic()
    try:
        response = await http_client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("GET %s failed with HTTP %s", url, status)
        if status == 404:
            raise ToolError(
                f"Upstream API returned 404 for {url} - check that the "
                "station UUID and parameter shortname are valid."
            ) from exc
        raise ToolError(f"Upstream API returned HTTP {status} for {url}.") from exc
    except httpx.TimeoutException as exc:
        logger.warning("GET %s timed out", url)
        raise ToolError(f"Request to {url} timed out after 30s.") from exc
    except httpx.RequestError as exc:
        logger.warning("GET %s failed: %s", url, exc)
        raise ToolError(f"Could not reach upstream API at {url}: {exc}") from exc
    logger.info(
        "GET %s -> %s (%.0f ms)", url, response.status_code,
        (time.monotonic() - start) * 1000,
    )
    return response.json()
