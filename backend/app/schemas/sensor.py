from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SensorStatus = Literal[
    "OK",
    "WARNING",
    "CRITICAL",
]

SensorValueType = Literal[
    "numeric",
    "binary",
    "datetime",
    "text",
]


class SensorResponse(BaseModel):
    id: int
    name: str
    type: str

    engineering_system: str | None = None
    object_id: int | None = None

    value_type: SensorValueType | None = None

    value: float | str | None = None

    occurred_at: datetime | None = None

    status: SensorStatus

    risk: float = Field(
        ge=0.0,
        le=1.0,
    )
