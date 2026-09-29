import csv
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

BACKEND_ROOT = (
    PROJECT_ROOT
    / "backend"
)

sys.path.insert(
    0,
    str(BACKEND_ROOT),
)
sys.path.insert(0, str(PROJECT_ROOT))
from source_agent.paths import resolve_source_path

CACHE_ROOT = (
    Path(os.getenv("SOURCE_CACHE_PATH", str(Path.home() / ".cache" / "astra" / "source-agent")))
)

os.environ[
    "SOURCE_CACHE_PATH"
] = str(CACHE_ROOT)


import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.repositories.file_sensor_repository import (
    FileSensorRepository,
)
from app.repositories.file_ml_data_repository import (
    FileMLDataRepository,
)


logger = logging.getLogger("astra.source_agent")


app = FastAPI(
    title="ASTRA Source Agent",
    version="0.2.0",
)


CHANNEL_COLUMNS = {
    "ид_канала_данных",
    "тип_инж_системы",
    "тип_датчика",
    "ид_объект",
}

EVENT_COLUMNS = {
    "ид_события",
    "ид_канала_данных",
    "дата_время_события",
    "тип_значения",
}

OBJECT_COLUMNS = {
    "ид_объект",
    "иерархия_уровень",
    "родитель",
    "вид_объекта",
    "диспетчерское_название_объекта",
}


class SourceConnectRequest(BaseModel):
    path: str


active_source: Path | None = None
active_files: dict[str, Path] = {}

pending_source: Path | None = None
pending_files: dict[str, Path] = {}

source_state = "disconnected"
source_error: str | None = None
source_sensor_count: int | None = None

source_state_lock = threading.RLock()


def serialize_files(
    files: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    return {
        role: {
            "path": str(path),
            "name": path.name,
            "size_bytes": path.stat().st_size,
        }
        for role, path in files.items()
    }


def source_status_payload() -> dict[str, Any]:
    with source_state_lock:
        state = source_state
        error = source_error
        sensor_count = source_sensor_count

        if state == "connected":
            current_path = active_source
            current_files = dict(active_files)
        else:
            current_path = pending_source
            current_files = dict(pending_files)

    return {
        "state": state,
        "connected": (
            state == "connected"
            and current_path is not None
        ),
        "path": (
            str(current_path)
            if current_path is not None
            else None
        ),
        "files": serialize_files(
            current_files
        ),
        "error": error,
        "sensor_count": sensor_count,
    }


@app.get("/health")
def health() -> dict:
    with source_state_lock:
        state = source_state

    return {
        "status": "ok",
        "source_state": state,
        "source_connected": (
            state == "connected"
        ),
    }


@app.get("/source/status")
def source_status() -> dict[str, Any]:
    return source_status_payload()


def prepare_source(
    source_path: Path,
    detected: dict[str, Path],
) -> None:
    global active_source
    global active_files
    global pending_source
    global pending_files
    global source_state
    global source_error
    global source_sensor_count

    logger.info(
        "Preparing source %s",
        source_path,
    )

    try:
        repository = FileSensorRepository(
            source_path=source_path,
        )

        sensor_count = len(
            repository.get_all()
        )
    except Exception as error:
        logger.exception(
            "Source preparation failed for %s",
            source_path,
        )

        with source_state_lock:
            source_state = "error"
            source_error = str(error)
            source_sensor_count = None

        return

    with source_state_lock:
        # Only publish the source after the cache is fully ready.
        active_source = source_path
        active_files = dict(detected)

        pending_source = None
        pending_files = {}

        source_state = "connected"
        source_error = None
        source_sensor_count = sensor_count

    logger.info(
        "Source %s is ready: %s sensors",
        source_path,
        sensor_count,
    )


@app.post("/source/connect")
def connect_source(
    request: SourceConnectRequest,
):
    global active_source
    global active_files
    global pending_source
    global pending_files
    global source_state
    global source_error
    global source_sensor_count

    try:
        source_path = resolve_source_path(request.path)
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=(
                "Source path does not exist "
                f"or cannot be accessed: {error}"
            ),
        ) from error

    if not source_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "For now ASTRA expects "
                "a directory containing CSV files"
            ),
        )

    with source_state_lock:
        if (
            source_state == "connected"
            and active_source == source_path
        ):
            return JSONResponse(
                status_code=200,
                content=source_status_payload(),
            )

        if source_state == "preparing":
            if pending_source == source_path:
                return JSONResponse(
                    status_code=202,
                    content=source_status_payload(),
                )

            raise HTTPException(
                status_code=409,
                detail=(
                    "Another data source is already "
                    "being prepared"
                ),
            )

    detected = detect_source_files(
        source_path
    )

    missing = {
        "channels",
        "events",
        "objects",
    } - set(detected)

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Required source files "
                    "were not detected"
                ),
                "missing": sorted(missing),
                "detected": {
                    role: path.name
                    for role, path
                    in detected.items()
                },
            },
        )

    with source_state_lock:
        # The current source is deliberately hidden while the new
        # source is being prepared, so the UI cannot read stale data.
        active_source = None
        active_files = {}

        pending_source = source_path
        pending_files = dict(detected)

        source_state = "preparing"
        source_error = None
        source_sensor_count = None

    worker = threading.Thread(
        target=prepare_source,
        args=(
            source_path,
            dict(detected),
        ),
        name="astra-source-prepare",
        daemon=True,
    )
    worker.start()

    return JSONResponse(
        status_code=202,
        content=source_status_payload(),
    )


@app.get("/data/sensors")
def get_sensors() -> list[dict[str, Any]]:
    source_path = require_active_source()

    repository = FileSensorRepository(
        source_path=source_path,
    )

    return repository.get_all()


@app.get("/data/sensors/{sensor_id}")
def get_sensor(
    sensor_id: int,
) -> dict[str, Any]:
    source_path = require_active_source()

    repository = FileSensorRepository(
        source_path=source_path,
    )

    sensor = repository.get_by_id(
        sensor_id
    )

    if sensor is None:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found",
        )

    return sensor


@app.get(
    "/data/ml/{sensor_id}/latest"
)
def get_latest_ml_event(
    sensor_id: int,
) -> dict[str, Any]:
    source_path = require_active_source()

    repository = FileMLDataRepository(
        source_path=source_path,
    )

    occurred_at = (
        repository.get_latest_event_time(
            sensor_id
        )
    )

    return {
        "sensor_id": sensor_id,
        "occurred_at": occurred_at,
    }


@app.get(
    "/data/ml/{sensor_id}/events"
)
def get_ml_events(
    sensor_id: int,
    start: datetime,
    end: datetime,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    source_path = require_active_source()

    repository = FileMLDataRepository(
        source_path=source_path,
    )

    try:
        return repository.get_events(
            sensor_id=sensor_id,
            start=start,
            end=end,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


def require_active_source() -> Path:
    with source_state_lock:
        state = source_state
        current_source = active_source

    if (
        state != "connected"
        or current_source is None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Data source is not ready"
                if state == "preparing"
                else "Data source is not connected"
            ),
        )

    return current_source


def detect_source_files(
    source_path: Path,
) -> dict[str, Path]:
    detected: dict[str, Path] = {}

    for path in sorted(
        source_path.glob("*.csv")
    ):
        try:
            columns = read_columns(
                path
            )
        except (
            OSError,
            UnicodeDecodeError,
        ):
            continue

        if CHANNEL_COLUMNS.issubset(
            columns
        ):
            detected["channels"] = path

        if EVENT_COLUMNS.issubset(
            columns
        ):
            detected["events"] = path

        if OBJECT_COLUMNS.issubset(
            columns
        ):
            detected["objects"] = path

    return detected


def read_columns(
    path: Path,
) -> set[str]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        sample = file.read(
            64 * 1024
        )

        file.seek(0)

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=",;\t|",
            )
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(
            file,
            dialect=dialect,
        )

        header = next(
            reader,
            [],
        )

        return {
            str(column).strip()
            for column in header
        }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9100,
    )
