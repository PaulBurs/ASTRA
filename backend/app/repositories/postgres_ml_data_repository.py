from datetime import datetime

from sqlalchemy import text

from app.db.database import engine
from app.repositories.ml_data_repository import (
    MLDataRepository,
)


class PostgresMLDataRepository(MLDataRepository):
    """История событий для online ML inference."""

    MAX_EVENTS = 5000

    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        query = text(
            """
            SELECT occurred_at
            FROM ext_journal_prepared
            WHERE sensor_id = :sensor_id
            ORDER BY
                occurred_at DESC,
                event_id DESC
            LIMIT 1
            """
        )

        with engine.connect() as connection:
            return connection.execute(
                query,
                {"sensor_id": sensor_id},
            ).scalar_one_or_none()

    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        if limit <= 0 or limit > self.MAX_EVENTS:
            raise ValueError(
                "limit must be between "
                f"1 and {self.MAX_EVENTS}"
            )

        if start > end:
            raise ValueError(
                "start must not be later than end"
            )

        query = text(
            """
            SELECT
                event_id,
                occurred_at,
                value_type,
                numeric_value,
                datetime_value,
                text_value
            FROM ext_journal_prepared
            WHERE sensor_id = :sensor_id
              AND occurred_at >= :start
              AND occurred_at <= :end
            ORDER BY
                occurred_at DESC,
                event_id DESC
            LIMIT :limit
            """
        )

        with engine.connect() as connection:
            result = connection.execute(
                query,
                {
                    "sensor_id": sensor_id,
                    "start": start,
                    "end": end,
                    "limit": limit,
                },
            )

            rows = [
                dict(row)
                for row in result.mappings()
            ]

        # SQL получает сначала самые новые события.
        # ML получает временной ряд от старых к новым.
        rows.reverse()

        return rows
