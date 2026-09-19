from app.ml.service import MLService
from app.repositories.sensor_repository import SensorRepository


class SensorNotFoundError(Exception):
    """Датчик с указанным ID не найден."""


class PredictionService:
    """Связывает данные датчика и ML-прогноз."""

    def __init__(
        self,
        sensor_repository: SensorRepository,
        ml_service: MLService,
    ):
        self.sensor_repository = sensor_repository
        self.ml_service = ml_service

    def predict(self, sensor_id: int) -> dict:
        sensor = self.sensor_repository.get_by_id(sensor_id)

        if sensor is None:
            raise SensorNotFoundError(sensor_id)

        return self.ml_service.predict(sensor_id)
