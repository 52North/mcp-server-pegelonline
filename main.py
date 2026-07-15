"""ASGI entry point for serving the MCP server over Streamable HTTP.

The MCP endpoint is served at ``/mcp`` and the LB health probe at ``/healthz``.
"""

from server import mcp

# Streamable HTTP ASGI app (Starlette). Mounts the MCP endpoint at /mcp and
# carries the /healthz custom route registered in server.py.
app = mcp.http_app()
