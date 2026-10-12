"""MCP server for gauge stations on German federal waterways (Pegelonline)."""

import os

__version__ = "0.1.0"

# FastMCP attaches its own Rich log handler on import unless this is off.
# Every entry point imports this package before FastMCP, so the runtime's
# logging setup (stdio or uvicorn --log-config) formats all logs instead.
os.environ.setdefault("FASTMCP_LOG_ENABLED", "false")
