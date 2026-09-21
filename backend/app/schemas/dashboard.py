from pydantic import BaseModel, Field

from app.schemas.health import HealthResponse
from app.schemas.sensor import SensorResponse


class DashboardSummary(BaseModel):
    total_sensors: int = Field(ge=0)
    ok: int = Field(ge=0)
    warning: int = Field(ge=0)
    critical: int = Field(ge=0)
    max_risk: float = Field(ge=0.0, le=1.0)


class DashboardResponse(BaseModel):
    system: HealthResponse
    summary: DashboardSummary
    sensors: list[SensorResponse]
