import os
from uuid import UUID

from fastapi import HTTPException
from astra_pipeline.registry import ensure_registry, get_dataset
from app.db.database import engine
from app.repositories.prepared_dataset_repository import PreparedSensorRepository, PreparedMLDataRepository

from app.ml.dummy import DummyMLService
from app.ml.service import MLService

from app.repositories.dummy_ml_data_repository import (
    DummyMLDataRepository,
)
from app.repositories.dummy_sensor_catalog_repository import (
    DummySensorCatalogRepository,
)
from app.repositories.dummy_sensor_repository import (
    DummySensorRepository,
)
from app.repositories.ml_data_repository import (
    MLDataRepository,
)
from app.repositories.postgres_ml_data_repository import (
    PostgresMLDataRepository,
)
from app.repositories.file_ml_data_repository import (
    FileMLDataRepository,
)
from app.repositories.postgres_sensor_catalog_repository import (
    PostgresSensorCatalogRepository,
)
from app.repositories.postgres_sensor_repository import (
    PostgresSensorRepository,
)
from app.repositories.sensor_catalog_repository import (
    SensorCatalogRepository,
)
from app.repositories.sensor_repository import (
    SensorRepository,
)
from app.repositories.file_sensor_repository import (
    FileSensorRepository,
)
from app.repositories.file_sensor_catalog_repository import (
    FileSensorCatalogRepository,
)
from app.repositories.agent_sensor_repository import (
    AgentSensorRepository,
)
from app.ml.http_service import HTTPMLService
from app.repositories.agent_ml_data_repository import (
    AgentMLDataRepository,
)


def create_sensor_repository() -> SensorRepository:
    source = os.getenv(
        "DATA_SOURCE",
        "dummy",
    ).lower()

    if source == "agent":
        return AgentSensorRepository()

    if source == "file":
        return FileSensorRepository()

    if source == "postgres":
        return PostgresSensorRepository()

    return DummySensorRepository()


def create_ml_data_repository() -> MLDataRepository:
    source = os.getenv(
        "ML_DATA_SOURCE",
        "dummy",
    ).lower()

    if source == "agent":
        return AgentMLDataRepository()

    if source == "file":
        return FileMLDataRepository()

    if source == "postgres":
        return PostgresMLDataRepository()

    return DummyMLDataRepository()


def create_sensor_catalog_repository() -> SensorCatalogRepository:
    source = os.getenv(
        "ML_DATA_SOURCE",
        "dummy",
    ).lower()

    if source == "file":
        return FileSensorCatalogRepository()

    if source == "postgres":
        return PostgresSensorCatalogRepository()

    return DummySensorCatalogRepository()


def create_ml_service() -> MLService:
    ml_service_url = os.getenv(
        "ML_SERVICE_URL",
        "",
    ).strip()

    if ml_service_url:
        return HTTPMLService(
            ml_service_url
        )

    return DummyMLService()


_ml_service: MLService = create_ml_service()

_sensor_repository: SensorRepository = (
    create_sensor_repository()
)

_ml_data_repository: MLDataRepository = (
    create_ml_data_repository()
)

_sensor_catalog_repository: SensorCatalogRepository = (
    create_sensor_catalog_repository()
)


def get_ml_service() -> MLService:
    return _ml_service


def require_prepared_dataset(dataset_id: UUID):
    ensure_registry(engine)
    try:
        job = get_dataset(engine, dataset_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    if job["status"] not in {"prepared", "ready"}:
        raise HTTPException(409, "Данные ещё не подготовлены")


def get_sensor_repository(dataset_id: UUID | None = None) -> SensorRepository:
    if dataset_id is not None:
        require_prepared_dataset(dataset_id)
        return PreparedSensorRepository(engine, dataset_id)
    return _sensor_repository


def get_ml_data_repository(dataset_id: UUID | None = None) -> MLDataRepository:
    if dataset_id is not None:
        require_prepared_dataset(dataset_id)
        return PreparedMLDataRepository(engine, dataset_id)
    return _ml_data_repository


def get_sensor_catalog_repository(
) -> SensorCatalogRepository:
    return _sensor_catalog_repository
