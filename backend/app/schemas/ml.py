from typing import Literal

from pydantic import BaseModel


class MLHealthResponse(BaseModel):
    status: Literal["available", "unavailable"]


class MLTrainResponse(BaseModel):
    status: str
    model_version: str
    message: str
