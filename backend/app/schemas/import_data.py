from typing import Literal

from pydantic import BaseModel


class ImportResponse(BaseModel):
    status: Literal["success", "error"]
    filename: str | None = None
    size_bytes: int | None = None
    message: str
