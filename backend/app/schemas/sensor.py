from typing import Literal

from pydantic import BaseModel
from pydantic import BaseModel, Field


class SensorResponse(BaseModel):
    id: int
    name: str
    type: str
    value: float
    status: Literal["OK", "WARNING", "CRITICAL"]
    risk: float = Field(ge=0.0, le=1.0)
