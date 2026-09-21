from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MLEvent(BaseModel):
    event_id: int
    occurred_at: datetime

    value_type: Literal[
        "numeric",
        "binary",
        "datetime",
        "text",
    ]

    numeric_value: float | None = None
    datetime_value: datetime | None = None
    text_value: str | None = None


class MLPredictionInput(BaseModel):
    sensor_id: int

    sensor_type: str | None = None
    engineering_system: str | None = None
    sensor_name: str | None = None
    object_id: int | None = None

    as_of: datetime
    lookback_hours: int

    events: list[MLEvent]
