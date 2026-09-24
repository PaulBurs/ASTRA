import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


router = APIRouter(
    prefix="/api/data-source",
    tags=["data-source"],
)


SOURCE_AGENT_URL = os.getenv(
    "SOURCE_AGENT_URL",
    "http://host.docker.internal:9100",
).rstrip("/")


class DataSourceConnectRequest(BaseModel):
    path: str


def proxy_json_response(
    response: httpx.Response,
) -> JSONResponse:
    try:
        content = response.json()
    except ValueError:
        content = {
            "detail": response.text,
        }

    return JSONResponse(
        status_code=response.status_code,
        content=content,
    )


@router.get("/status")
def get_data_source_status():
    try:
        response = httpx.get(
            f"{SOURCE_AGENT_URL}/source/status",
            timeout=5.0,
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Source agent is unavailable: "
                f"{error}"
            ),
        ) from error

    return proxy_json_response(
        response
    )


@router.post("/connect")
def connect_data_source(
    request: DataSourceConnectRequest,
):
    try:
        # Source Agent now starts preparation in the background,
        # so this request should return almost immediately with 202.
        response = httpx.post(
            f"{SOURCE_AGENT_URL}/source/connect",
            json={
                "path": request.path,
            },
            timeout=15.0,
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Source agent is unavailable: "
                f"{error}"
            ),
        ) from error

    return proxy_json_response(
        response
    )

