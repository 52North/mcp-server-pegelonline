"""Errors the caller of a tool has to correct, e.g. an invalid time window."""

import logging

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


def caller_error(message: str) -> ToolError:
    """A ToolError for a request the caller has to correct, logged as a warning.

    FastMCP logs a ToolError at its log level without the message, so the
    reason is logged here; ERROR stays for upstream failures.
    """
    logger.warning("Rejected: %s", message)
    return ToolError(message, log_level=logging.WARNING)
