"""Tests for the Streamable HTTP app served by uvicorn in production.

Each test runs the app's lifespan itself, which starts the MCP session manager.
It cannot live in a fixture: the lifespan's task group must be exited in the
task that entered it, and pytest-asyncio tears fixtures down in another task.
"""

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from pegelonline_mcp.asgi import app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def asgi_client(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("base_url", "http://test")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)


async def test_healthz():
    # A plain route: it needs no MCP session manager, hence no lifespan
    async with asgi_client() as http:
        response = await http.get("/healthz")

    assert response.status_code == 200
    assert response.text == "ok"


async def test_any_instance_answers_without_session():
    # Behind a load balancer without sticky sessions, a request may reach an
    # instance that never saw the client's initialize. A stateful server
    # answers 404 "Session not found" here.
    async with app.router.lifespan_context(app), asgi_client() as http:
        response = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**MCP_HEADERS, "Mcp-Session-Id": "issued-by-another-instance"},
        )

    assert response.status_code == 200
    assert "search_stations" in response.text


async def test_client_over_streamable_http():
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=asgi_client
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        tools = await client.list_tools()

    assert "search_stations" in {tool.name for tool in tools}
