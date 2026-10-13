"""Declarative argument constraints shared by the tool modules.

FastMCP validates them before the tool runs and publishes them in the tool
input schema.
"""

from typing import Annotated, Literal

from pydantic import Field

from pegelonline_mcp.client import HISTORY_MINUTES

# Station limits: more than the ~730 stations
Count = Annotated[int, Field(ge=1, le=1000)]
# "The last N values" of a timeseries; time spans go to get_measurement_history
RecentCount = Annotated[int, Field(ge=1, le=100)]
# 1000 km around any point in Germany covers the whole country
RadiusKm = Annotated[float, Field(gt=0, le=1000)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
# A time span reaching back further than the kept history adds nothing
Hours = Annotated[float, Field(gt=0, le=HISTORY_MINUTES // 60)]
# Rows of a measurement history: raw values, or min/mean/max per hour or
# day; auto takes raw values while they fit
Resolution = Literal["auto", "raw", "hour", "day"]
