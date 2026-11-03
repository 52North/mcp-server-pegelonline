"""Pytest plugin that lets respx mock the httpx2 client.

respx patches httpx and httpcore only. This plugin makes both names resolve to
httpx2 and httpcore2, so it has to run before anything imports httpx: pytest
loads it through ``-p`` in ``addopts``, before the plugins installed with
packages such as respx. conftest.py checks that it did.
"""

import httpx2

httpx2.alias_httpx()
