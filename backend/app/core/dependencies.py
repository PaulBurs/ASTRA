import os

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
from app.ml.http_service import HTTPMLService


def create_sensor_repository() -> SensorRepository:
    source = os.getenv(
        "DATA_SOURCE",
        "dummy",
    ).lower()

    if source == "postgres":
        return PostgresSensorRepository()

    return DummySensorRepository()


def create_ml_data_repository() -> MLDataRepository:
    source = os.getenv(
        "ML_DATA_SOURCE",
        "dummy",
    ).lower()

    if source == "postgres":
        return PostgresMLDataRepository()

    return DummyMLDataRepository()


def create_sensor_catalog_repository(
) -> SensorCatalogRepository:
    source = os.getenv(
        "ML_DATA_SOURCE",
        "dummy",
    ).lower()

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


def get_sensor_repository() -> SensorRepository:
    return _sensor_repository


def get_ml_data_repository() -> MLDataRepository:
    return _ml_data_repository


def get_sensor_catalog_repository(
) -> SensorCatalogRepository:
    return _sensor_catalog_repository
