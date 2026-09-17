from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    application: str
    database: Literal["connected", "disconnected"]
    ml: Literal["available", "unavailable"]
