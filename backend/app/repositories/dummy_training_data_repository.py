from collections.abc import Iterator
from datetime import datetime

from app.repositories.training_data_repository import (
    TrainingDataRepository,
)


class DummyTrainingDataRepository(
    TrainingDataRepository
):
    """Минимальный набор данных для разработки ML pipeline."""

    def iter_events(
        self,
        sensor_ids: list[int],
        start: datetime,
        end: datetime,
        batch_size: int = 50_000,
    ) -> Iterator[list[dict]]:
        events = [
            {
                "event_id": 1,
                "sensor_id": 900001,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    8,
                    0,
                ),
                "value_type": "numeric",
                "numeric_value": 0.01,
                "datetime_value": None,
                "text_value": None,
            },
            {
                "event_id": 2,
                "sensor_id": 900001,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    8,
                    10,
                ),
                "value_type": "numeric",
                "numeric_value": 0.03,
                "datetime_value": None,
                "text_value": None,
            },
            {
                "event_id": 3,
                "sensor_id": 900001,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    8,
                    20,
                ),
                "value_type": "text",
                "numeric_value": None,
                "datetime_value": None,
                "text_value": "Обнаружен газ",
            },
        ]

        selected = [
            event
            for event in events
            if event["sensor_id"] in sensor_ids
            and start
            <= event["occurred_at"]
            < end
        ]

        for index in range(
            0,
            len(selected),
            batch_size,
        ):
            yield selected[
                index:index + batch_size
            ]
