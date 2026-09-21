from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ValueType = Literal[
    "numeric",
    "binary",
    "datetime",
    "text",
]


class MLEvent(BaseModel):
    event_id: int
    occurred_at: datetime
    value_type: ValueType

    numeric_value: float | None = None
    datetime_value: datetime | None = None
    text_value: str | None = None


class PredictionInput(BaseModel):
    sensor_id: int

    sensor_type: str | None = None
    engineering_system: str | None = None
    sensor_name: str | None = None
    object_id: int | None = None

    as_of: datetime
    lookback_hours: int = Field(ge=1)

    events: list[MLEvent]


class PredictionOutput(BaseModel):
    sensor_id: int

    probability: float = Field(
        ge=0.0,
        le=1.0,
    )

    horizon_hours: int = Field(
        ge=1,
    )

    model_version: str


class HealthOutput(BaseModel):
    available: bool
    model_version: str


class TrainOutput(BaseModel):
    status: str
    model_version: str
    message: str
