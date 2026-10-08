"""Declarative argument constraints shared by the tool modules.

FastMCP validates them before the tool runs and publishes them in the tool
input schema.
"""

from typing import Annotated

from pydantic import Field

Count = Annotated[int, Field(ge=1)]
RadiusKm = Annotated[float, Field(gt=0)]
