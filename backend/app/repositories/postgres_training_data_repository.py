from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import bindparam, text

from app.db.database import engine
from app.repositories.training_data_repository import (
    TrainingDataRepository,
)


class PostgresTrainingDataRepository(
    TrainingDataRepository
):
    """Потоковое чтение истории для обучения ML."""

    MAX_BATCH_SIZE = 100_000

    def iter_events(
        self,
        sensor_ids: list[int],
        start: datetime,
        end: datetime,
        batch_size: int = 50_000,
    ) -> Iterator[list[dict]]:
        if not sensor_ids:
            return

        if start >= end:
            raise ValueError(
                "start must be earlier than end"
            )

        if (
            batch_size <= 0
            or batch_size > self.MAX_BATCH_SIZE
        ):
            raise ValueError(
                "batch_size must be between "
                f"1 and {self.MAX_BATCH_SIZE}"
            )

        query = text(
            """
            SELECT
                event_id,
                sensor_id,
                occurred_at,
                value_type,
                numeric_value,
                datetime_value,
                text_value
            FROM ext_journal_prepared
            WHERE sensor_id IN :sensor_ids
              AND occurred_at >= :start
              AND occurred_at < :end
            ORDER BY
                sensor_id,
                occurred_at,
                event_id
            """
        ).bindparams(
            bindparam(
                "sensor_ids",
                expanding=True,
            )
        )

        with engine.connect() as connection:
            result = (
                connection
                .execution_options(
                    stream_results=True,
                    yield_per=batch_size,
                )
                .execute(
                    query,
                    {
                        "sensor_ids": sensor_ids,
                        "start": start,
                        "end": end,
                    },
                )
            )

            mappings = result.mappings()

            while True:
                rows = mappings.fetchmany(
                    batch_size
                )

                if not rows:
                    break

                yield [
                    dict(row)
                    for row in rows
                ]
