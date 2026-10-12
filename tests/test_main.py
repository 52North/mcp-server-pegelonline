"""The console script that starts the stdio server."""

from importlib.metadata import entry_points

from pegelonline_mcp.__main__ import main


def test_console_script_starts_main():
    scripts = entry_points(group="console_scripts", name="mcp-server-pegelonline")

    assert len(scripts) == 1
    assert next(iter(scripts)).load() is main
