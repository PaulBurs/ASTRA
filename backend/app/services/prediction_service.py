from datetime import timedelta

from app.ml.contracts import MLPredictionInput
from app.ml.service import MLService
from app.repositories.ml_data_repository import (
    MLDataRepository,
)
from app.repositories.sensor_repository import (
    SensorRepository,
)


class SensorNotFoundError(Exception):
    """Датчик не найден."""


class SensorDataNotFoundError(Exception):
    """Для датчика отсутствует история событий."""


class PredictionService:
    """Подготавливает данные датчика и передаёт их ML."""

    LOOKBACK_HOURS = 24

    def __init__(
        self,
        sensor_repository: SensorRepository,
        ml_data_repository: MLDataRepository,
        ml_service: MLService,
    ):
        self.sensor_repository = sensor_repository
        self.ml_data_repository = ml_data_repository
        self.ml_service = ml_service

    def predict(
        self,
        sensor_id: int,
    ) -> dict:
        sensor = self.sensor_repository.get_by_id(
            sensor_id
        )

        if sensor is None:
            raise SensorNotFoundError(sensor_id)

        as_of = (
            self.ml_data_repository
            .get_latest_event_time(sensor_id)
        )

        if as_of is None:
            raise SensorDataNotFoundError(sensor_id)

        start = as_of - timedelta(
            hours=self.LOOKBACK_HOURS
        )

        events = self.ml_data_repository.get_events(
            sensor_id=sensor_id,
            start=start,
            end=as_of,
        )

        if not events:
            raise SensorDataNotFoundError(sensor_id)

        prediction_input = MLPredictionInput(
            sensor_id=sensor_id,
            sensor_type=sensor.get("type"),
            engineering_system=sensor.get(
                "engineering_system"
            ),
            sensor_name=sensor.get("name"),
            object_id=sensor.get("object_id"),
            as_of=as_of,
            lookback_hours=self.LOOKBACK_HOURS,
            events=events,
        )

        return self.ml_service.predict(
            prediction_input
        )
