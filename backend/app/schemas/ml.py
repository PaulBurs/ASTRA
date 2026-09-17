from typing import Literal

from pydantic import BaseModel, Field


class MLHealthResponse(BaseModel):
    status: Literal["available", "unavailable"]


class MLTrainResponse(BaseModel):
    status: str
    model_version: str
    message: str
    
    
class MLPredictionResponse(BaseModel):
    sensor_id: int
    probability: float = Field(ge=0.0, le=1.0)
    horizon_hours: int = Field(ge=24)
    model_version: str
