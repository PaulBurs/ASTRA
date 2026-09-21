import os
from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import (
    bindparam,
    create_engine,
    text,
)


MAX_BATCH_SIZE = 100_000


def create_ml_engine():
    database_url = os.getenv(
        "ML_DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "ML_DATABASE_URL is not configured"
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def get_sensor_ids(
    engineering_system: str,
    sensor_type: str,
) -> list[int]:
    engine = create_ml_engine()

    query = text(
        """
        SELECT sensor_id
        FROM astra_channels
        WHERE engineering_system = :engineering_system
          AND sensor_type = :sensor_type
        ORDER BY sensor_id
        """
    )

    with engine.connect() as connection:
        result = connection.execute(
            query,
            {
                "engineering_system": (
                    engineering_system
                ),
                "sensor_type": sensor_type,
            },
        )

        return [
            row.sensor_id
            for row in result
        ]


def iter_training_events(
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
        or batch_size > MAX_BATCH_SIZE
    ):
        raise ValueError(
            "invalid batch_size"
        )

    engine = create_ml_engine()

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
