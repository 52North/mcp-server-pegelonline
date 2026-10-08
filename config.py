"""Runtime configuration from environment variables."""

import os

BASE_URL = os.environ.get(
    "PEGELONLINE_DICT_API_URL", "https://dict-api.pegelonline.wsv.de"
).rstrip("/")
OFFICIAL_API_URL = os.environ.get(
    "PEGELONLINE_API_URL", "https://pegelonline.wsv.de/webservices/rest-api/v2"
).rstrip("/")
