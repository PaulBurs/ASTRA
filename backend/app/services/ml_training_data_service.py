from collections.abc import Iterator
from datetime import datetime

from app.repositories.sensor_catalog_repository import (
    SensorCatalogRepository,
)
from app.repositories.training_data_repository import (
    TrainingDataRepository,
)


class TrainingSensorsNotFoundError(Exception):
    """Не найдено каналов под заданные условия."""


class MLTrainingDataService:
    """
    Высокоуровневый доступ к данным для обучения ML.

    ML-коду не нужно знать:
    - структуру PostgreSQL;
    - имена таблиц;
    - SQL-запросы.
    """

    def __init__(
        self,
        sensor_catalog_repository: SensorCatalogRepository,
        training_data_repository: TrainingDataRepository,
    ):
        self.sensor_catalog_repository = (
            sensor_catalog_repository
        )
        self.training_data_repository = (
            training_data_repository
        )

    def get_sensor_ids(
        self,
        engineering_system: str,
        sensor_type: str,
    ) -> list[int]:
        sensor_ids = (
            self.sensor_catalog_repository.get_sensor_ids(
                engineering_system=engineering_system,
                sensor_type=sensor_type,
            )
        )

        if not sensor_ids:
            raise TrainingSensorsNotFoundError(
                "No sensors found for "
                f"engineering_system={engineering_system!r}, "
                f"sensor_type={sensor_type!r}"
            )

        return sensor_ids

    def iter_training_events(
        self,
        engineering_system: str,
        sensor_type: str,
        start: datetime,
        end: datetime,
        batch_size: int = 50_000,
    ) -> Iterator[list[dict]]:
        sensor_ids = self.get_sensor_ids(
            engineering_system=engineering_system,
            sensor_type=sensor_type,
        )

        yield from self.training_data_repository.iter_events(
            sensor_ids=sensor_ids,
            start=start,
            end=end,
            batch_size=batch_size,
        )
