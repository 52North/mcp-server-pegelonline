"""Declarative argument constraints shared by the tool modules.

FastMCP validates them before the tool runs and publishes them in the tool
input schema.
"""

from typing import Annotated

from pydantic import Field

from pegelonline_mcp.client import HISTORY_MINUTES

Count = Annotated[int, Field(ge=1)]
RadiusKm = Annotated[float, Field(gt=0)]
# A time span reaching back further than the kept history adds nothing
Hours = Annotated[float, Field(gt=0, le=HISTORY_MINUTES // 60)]
