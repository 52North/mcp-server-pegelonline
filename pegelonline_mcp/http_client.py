"""Shared HTTP client for the upstream APIs."""

import asyncio
import logging
import time
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from pegelonline_mcp import __version__

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
# A failed connection attempt never reached the server, so it is safe to
# retry; read timeouts and HTTP errors are not retried.
CONNECT_RETRIES = 2
RETRY_DELAY_SECONDS = 0.5
# Identifies this server to the Pegelonline operators
USER_AGENT = (
    f"mcp-server-pegelonline/{__version__} "
    "(+https://github.com/52North/mcp-server-pegelonline)"
)

# Shared client for all requests; the process lifetime bounds its lifecycle.
# No custom transport: with one, httpx ignores HTTPS_PROXY and NO_PROXY.
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(TIMEOUT_SECONDS), headers={"User-Agent": USER_AGENT}
)


async def _get(url: str, params: dict | None) -> httpx.Response:
    """GET that retries failed connection attempts with a growing delay."""
    attempt = 1
    while True:
        try:
            return await http_client.get(url, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt > CONNECT_RETRIES:
                raise
            logger.warning(
                "GET %s failed to connect (attempt %d/%d), retrying: %s",
                url, attempt, CONNECT_RETRIES + 1, exc,
            )
            await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
            attempt += 1


async def get_json(url: str, params: dict | None = None) -> Any:
    """GET a JSON document.

    Failed connection attempts are retried up to CONNECT_RETRIES times.
    Transport errors, HTTP errors and invalid JSON become clear MCP errors.
    """
    logger.info("GET %s params=%s", url, params)
    start = time.monotonic()
    try:
        response = await _get(url, params)
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
        raise ToolError(
            f"Request to {url} timed out after {TIMEOUT_SECONDS:g}s."
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("GET %s failed: %s", url, exc)
        raise ToolError(f"Could not reach upstream API at {url}: {exc}") from exc
    logger.info(
        "GET %s -> %s (%.0f ms)", url, response.status_code,
        (time.monotonic() - start) * 1000,
    )
    try:
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "unknown")
        logger.warning("GET %s returned no JSON (%s)", url, content_type)
        raise ToolError(
            f"Upstream API returned no valid JSON for {url} "
            f"(content type: {content_type})."
        ) from exc
