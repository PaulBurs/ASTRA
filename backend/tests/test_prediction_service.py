from app.ml.service import MLService
from app.repositories.sensor_repository import SensorRepository
from app.services.prediction_service import (
    PredictionService,
    SensorNotFoundError,
)


class TestSensorRepository(SensorRepository):
    def get_all(self) -> list[dict]:
        return [
            {
                "id": 1,
                "name": "Test sensor",
                "type": "temperature",
                "value": 25.0,
                "status": "OK",
                "risk": 0.1,
            }
        ]

    def get_by_id(self, sensor_id: int) -> dict | None:
        for sensor in self.get_all():
            if sensor["id"] == sensor_id:
                return sensor

        return None


class TestMLService(MLService):
    def health(self) -> bool:
        return True

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "test-v1",
            "message": "Test training",
        }

    def predict(self, sensor_id: int) -> dict:
        return {
            "sensor_id": sensor_id,
            "probability": 0.75,
            "horizon_hours": 24,
            "model_version": "test-v1",
        }


def test_prediction_service_predicts_existing_sensor():
    service = PredictionService(
        sensor_repository=TestSensorRepository(),
        ml_service=TestMLService(),
    )

    result = service.predict(1)

    assert result["sensor_id"] == 1
    assert result["probability"] == 0.75


def test_prediction_service_rejects_unknown_sensor():
    service = PredictionService(
        sensor_repository=TestSensorRepository(),
        ml_service=TestMLService(),
    )

    try:
        service.predict(999999)
    except SensorNotFoundError:
        return

    assert False, "SensorNotFoundError was not raised"
