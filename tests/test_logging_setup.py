"""Tests for the logging setup of the stdio and uvicorn runtimes."""

import logging
import os
import subprocess
import sys

import pytest

from pegelonline_mcp.logging_setup import QUIET_LOGGERS, configure_logging


@pytest.fixture
def restore_logging():
    """configure_logging changes process-wide state; undo it after the test."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    quiet_levels = {name: logging.getLogger(name).level for name in QUIET_LOGGERS}
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, quiet_level in quiet_levels.items():
        logging.getLogger(name).setLevel(quiet_level)


def test_configure_logging_quiets_per_request_loggers(restore_logging, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    configure_logging()

    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_configure_logging_falls_back_to_info_on_unknown_level(
    restore_logging, monkeypatch, capsys
):
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    configure_logging()

    assert logging.getLogger().level == logging.INFO
    assert "Unknown LOG_LEVEL 'VERBOSE', using INFO" in capsys.readouterr().err


def fastmcp_logger_state(env: dict[str, str]) -> tuple[int, bool]:
    """Handler count and propagation of the fastmcp logger in a fresh interpreter.

    The package has to be imported before FastMCP, which this test process
    did long ago (conftest imports FastMCP first).
    """
    code = (
        "import logging, pegelonline_mcp.asgi; "
        "log = logging.getLogger('fastmcp'); "
        "print(len(log.handlers), log.propagate)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    count, propagate = result.stdout.split()
    return int(count), propagate == "True"


def test_fastmcp_leaves_logging_to_the_runtime():
    env = {k: v for k, v in os.environ.items() if k != "FASTMCP_LOG_ENABLED"}

    assert fastmcp_logger_state(env) == (0, True)
