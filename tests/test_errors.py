"""Tests for the errors the caller of a tool has to correct."""

import logging

import pytest
from fastmcp.exceptions import ToolError

from pegelonline_mcp.errors import caller_error


def test_caller_error_is_logged_as_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pegelonline_mcp"):
        error = caller_error("start must lie before end")

    assert isinstance(error, ToolError)
    assert str(error) == "start must lie before end"
    # FastMCP logs the error at this level, without its message
    assert error.log_level == logging.WARNING
    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        ("pegelonline_mcp.errors", logging.WARNING, "Rejected: start must lie before end")
    ]
