"""Logging configuration for the stdio (dev) runtime."""

import logging
import os
import sys

# Default log format across runtimes. uvicorn applies the
# log format via packaging/log-config.yaml.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Loggers that report every request at INFO, duplicating the application's
# own request logs; packaging/log-config.yaml quiets them for uvicorn.
QUIET_LOGGERS = ("httpx", "mcp.server.lowlevel")

logger = logging.getLogger("pegelonline-dict")


def configure_logging() -> None:
    """Configure root logging for the stdio (dev) runtime.

    Logs go to stderr so they never corrupt the JSON-RPC protocol on stdout.
    Under uvicorn the ``--log-config`` file (packaging/log-config.yaml) owns logging.
    An unknown ``LOG_LEVEL`` falls back to INFO with a warning.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(level_name)

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.INFO if level is None else level)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if level is None:
        logger.warning("Unknown LOG_LEVEL %r, using INFO", level_name)
