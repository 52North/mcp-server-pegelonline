"""stdio entry point: ``mcp-server-pegelonline`` or ``python -m pegelonline_mcp``."""

from pegelonline_mcp.logging_setup import configure_logging
from pegelonline_mcp.server import mcp


def main() -> None:
    # Configure logging for dev setup.
    # uvicorn logging is configured via --log-config.
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
