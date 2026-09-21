from datetime import datetime

import pytest

from app.ml.contracts import MLPredictionInput
from app.ml.service import MLService
from app.repositories.ml_data_repository import (
    MLDataRepository,
)
from app.repositories.sensor_repository import (
    SensorRepository,
)
from app.services.prediction_service import (
    PredictionService,
    SensorDataNotFoundError,
    SensorNotFoundError,
)


class TestSensorRepository(SensorRepository):
    def get_all(self) -> list[dict]:
        return [
            {
                "id": 1,
                "name": "Gas sensor",
                "type": "Газовый датчик",
                "engineering_system": "Газовая охрана",
                "object_id": 100,
                "value_type": "numeric",
                "value": 0.03,
                "occurred_at": None,
                "status": "OK",
                "risk": 0.1,
            }
        ]

    def get_by_id(
        self,
        sensor_id: int,
    ) -> dict | None:
        for sensor in self.get_all():
            if sensor["id"] == sensor_id:
                return sensor

        return None


class TestMLDataRepository(MLDataRepository):
    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        if sensor_id != 1:
            return None

        return datetime(
            2026,
            3,
            5,
            12,
            0,
        )

    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        if sensor_id != 1:
            return []

        return [
            {
                "event_id": 10,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    11,
                    50,
                ),
                "value_type": "numeric",
                "numeric_value": 0.03,
                "datetime_value": None,
                "text_value": None,
            }
        ]


class EmptyMLDataRepository(
    TestMLDataRepository
):
    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
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

    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        assert prediction_input.sensor_id == 1
        assert prediction_input.lookback_hours == 24

        assert (
            prediction_input.engineering_system
            == "Газовая охрана"
        )

        assert len(prediction_input.events) == 1

        assert (
            prediction_input.events[0].numeric_value
            == 0.03
        )

        return {
            "sensor_id": prediction_input.sensor_id,
            "probability": 0.75,
            "horizon_hours": 24,
            "model_version": "test-v1",
        }


def create_service(
    ml_data_repository: MLDataRepository
    | None = None,
) -> PredictionService:
    return PredictionService(
        sensor_repository=TestSensorRepository(),
        ml_data_repository=(
            ml_data_repository
            or TestMLDataRepository()
        ),
        ml_service=TestMLService(),
    )


def test_prediction_service_passes_data_to_ml():
    service = create_service()

    result = service.predict(1)

    assert result["sensor_id"] == 1
    assert result["probability"] == 0.75


def test_prediction_service_rejects_unknown_sensor():
    service = create_service()

    with pytest.raises(SensorNotFoundError):
        service.predict(999999)


def test_prediction_service_requires_history():
    service = create_service(
        EmptyMLDataRepository()
    )

    with pytest.raises(
        SensorDataNotFoundError
    ):
        service.predict(1)
