"""Shared HTTP and caching helpers for the Pegelonline Dict API MCP server."""

import logging
import os
import sys
import time
from typing import Any, Optional

import httpx
from fastmcp.exceptions import ToolError

logger = logging.getLogger("pegelonline-dict")

# Default log format across runtimes. uvicorn applies the
# log format via packaging/log-config.yaml.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    """Configure root logging for the stdio (dev) runtime.

    Logs go to stderr so they never corrupt the JSON-RPC protocol on stdout.
    Under uvicorn the ``--log-config`` file (packaging/log-config.yaml) owns logging,
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)

# Shared client for all requests; the process lifetime bounds its lifecycle
http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


async def get_json(url: str, params: Optional[dict] = None) -> Any:
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
