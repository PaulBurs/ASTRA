from app.ml.dummy import DummyMLService
from app.ml.service import MLService
from app.repositories.dummy_sensor_repository import DummySensorRepository
from app.repositories.sensor_repository import SensorRepository


_ml_service: MLService = DummyMLService()

_sensor_repository: SensorRepository = DummySensorRepository()


def get_ml_service() -> MLService:
    return _ml_service


def get_sensor_repository() -> SensorRepository:
    return _sensor_repository
