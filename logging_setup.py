"""Logging configuration for the stdio (dev) runtime."""

import logging
import os
import sys

# Default log format across runtimes. uvicorn applies the
# log format via packaging/log-config.yaml.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    """Configure root logging for the stdio (dev) runtime.

    Logs go to stderr so they never corrupt the JSON-RPC protocol on stdout.
    Under uvicorn the ``--log-config`` file (packaging/log-config.yaml) owns logging,
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
