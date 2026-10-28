"""HTTP health response; never disclose configuration or source data."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Literal["rush"] = "rush"
    status: Literal["ready"] = "ready"
    schema_version: int
