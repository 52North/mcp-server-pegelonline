"""Tests for the shared HTTP client: identification and connection retries."""

import tomllib
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

from conftest import STATION_URL
from pegelonline_mcp import __version__
from pegelonline_mcp.http_client import CONNECT_RETRIES, get_json


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


def test_version_matches_pyproject():
    # The RPM does not install the package, so the version cannot come from
    # its metadata; this keeps the copy in __init__.py in step.
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert __version__ == project["version"]
