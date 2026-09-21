from datetime import datetime

from app.repositories.ml_data_repository import (
    MLDataRepository,
)


class DummyMLDataRepository(MLDataRepository):
    """Тестовая история событий до подключения реальной БД."""

    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        return datetime(
            2026,
            3,
            5,
            9,
            11,
            35,
        )

    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        events = [
            {
                "event_id": 1,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    8,
                    50,
                ),
                "value_type": "numeric",
                "numeric_value": 0.01,
                "datetime_value": None,
                "text_value": None,
            },
            {
                "event_id": 2,
                "occurred_at": datetime(
                    2026,
                    3,
                    5,
                    9,
                    0,
                ),
                "value_type": "numeric",
                "numeric_value": 0.03,
                "datetime_value": None,
                "text_value": None,
            },
        ]

        return events[:limit]
