"""Tests for the shared HTTP client: identification, connection retries and PNGs."""

import tomllib
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

from conftest import CHART_PNG, CHART_URL, STATION_URL
from pegelonline_mcp import __version__
from pegelonline_mcp.http_client import CONNECT_RETRIES, get_json, get_png


async def test_requests_identify_the_server(respx_mock):
    route = respx_mock.get(STATION_URL).respond(json={})

    await get_json(STATION_URL)

    user_agent = route.calls.last.request.headers["User-Agent"]
    assert user_agent.startswith(f"mcp-server-pegelonline/{__version__} ")
    assert "github.com/52North/mcp-server-pegelonline" in user_agent


async def test_failed_connections_are_retried(respx_mock):
    route = respx_mock.get(STATION_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.ConnectTimeout("connect timed out"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    assert await get_json(STATION_URL) == {"ok": True}
    assert route.call_count == CONNECT_RETRIES + 1


async def test_retries_give_up_after_the_last_attempt(respx_mock):
    route = respx_mock.get(STATION_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(ToolError, match="Could not reach upstream API"):
        await get_json(STATION_URL)
    assert route.call_count == CONNECT_RETRIES + 1


@pytest.mark.parametrize(
    "mock",
    [
        {"side_effect": httpx.ReadTimeout("read timed out")},
        {"return_value": httpx.Response(503)},
    ],
    ids=["read-timeout", "server-error"],
)
async def test_other_failures_are_not_retried(respx_mock, mock):
    # The request may have reached the server, so it is not sent again
    route = respx_mock.get(STATION_URL).mock(**mock)

    with pytest.raises(ToolError):
        await get_json(STATION_URL)
    assert route.call_count == 1


@pytest.mark.parametrize("content_type", ["image/png", "image/png; charset=UTF-8"])
async def test_get_png_returns_the_image(respx_mock, content_type):
    respx_mock.get(CHART_URL).respond(content=CHART_PNG, content_type=content_type)

    assert await get_png(CHART_URL) == CHART_PNG


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, html="<html>Wartungsarbeiten</html>"),
        httpx.Response(200, json={"status": 200}),
        httpx.Response(200, content=CHART_PNG),
    ],
    ids=["html", "json", "no-content-type"],
)
async def test_get_png_rejects_other_content(respx_mock, response):
    respx_mock.get(CHART_URL).mock(return_value=response)

    with pytest.raises(ToolError, match="no PNG image"):
        await get_png(CHART_URL)


async def test_get_png_shares_retries_and_errors(respx_mock):
    route = respx_mock.get(CHART_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(404, json={"status": 404, "message": "Timeseries does not exist."}),
        ]
    )

    with pytest.raises(ToolError, match="404.*check that the station UUID"):
        await get_png(CHART_URL)
    assert route.call_count == 2


def test_version_matches_pyproject():
    # The RPM does not install the package, so the version cannot come from
    # its metadata; this keeps the copy in __init__.py in step.
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert __version__ == project["version"]
