"""ASGI entry point for serving the MCP server over Streamable HTTP.

The MCP endpoint is served at ``/mcp`` and the LB health probe at ``/healthz``.
The server runs stateless, so any instance behind a load balancer can answer
any request without sticky sessions.
"""

from pegelonline_mcp.server import mcp

# Streamable HTTP ASGI app (Starlette). Mounts the MCP endpoint at /mcp and
# carries the /healthz custom route registered in server.py.
# Stateless: every request gets a fresh transport and no session is kept in
# memory. The server holds no per-client state and never sends requests or
# notifications to the client, so nothing is lost; GET /mcp answers 405.
app = mcp.http_app(stateless_http=True)
