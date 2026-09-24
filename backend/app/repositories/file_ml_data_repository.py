import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from app.data_sources.duckdb_event_source import (
    DuckDBEventSource,
)
from app.repositories.ml_data_repository import (
    MLDataRepository,
)


CACHE_VERSION = 1


class FileMLDataRepository(
    MLDataRepository
):
    """
    История событий для online ML inference
    напрямую из исходного CSV.

    Исходный CSV не копируется.

    Для быстрых запросов создаётся производный
    Parquet-кэш только за последние 24 часа
    относительно последнего события каждого датчика.
    """

    MAX_EVENTS = 5000
    CACHE_LOOKBACK_HOURS = 24

    def __init__(
        self,
        source_path: str | Path | None = None,
    ):
        self.event_source = (
            DuckDBEventSource(
                source_path=source_path,
            )
        )

        self.events_file = (
            self.event_source.events_file
        )

        self.cache_dir = Path(
            os.getenv(
                "SOURCE_CACHE_PATH",
                "/data/cache",
            )
        )

        self.history_cache_file = (
            self.cache_dir
            / (
                "ml_history_"
                f"{self.CACHE_LOOKBACK_HOURS}h"
                ".parquet"
            )
        )

        self.history_metadata_file = (
            self.cache_dir
            / (
                "ml_history_"
                f"{self.CACHE_LOOKBACK_HOURS}h"
                ".json"
            )
        )

    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        event = (
            self.event_source
            .get_latest_event(
                sensor_id
            )
        )

        if event is None:
            return None

        occurred_at = event.get(
            "occurred_at"
        )

        if isinstance(
            occurred_at,
            datetime,
        ):
            return occurred_at

        return None

    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        if (
            limit <= 0
            or limit > self.MAX_EVENTS
        ):
            raise ValueError(
                "limit must be between "
                f"1 and {self.MAX_EVENTS}"
            )

        if start > end:
            raise ValueError(
                "start must not be later than end"
            )

        latest_time = (
            self.get_latest_event_time(
                sensor_id
            )
        )

        if latest_time is None:
            return []

        earliest_cached_time = (
            latest_time
            - timedelta(
                hours=(
                    self.CACHE_LOOKBACK_HOURS
                )
            )
        )

        if start < earliest_cached_time:
            raise ValueError(
                "File ML cache contains only "
                f"the latest "
                f"{self.CACHE_LOOKBACK_HOURS} "
                "hours for each sensor"
            )

        self._ensure_history_cache()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT
                    event_id,
                    occurred_at,
                    value_type,
                    numeric_value,
                    datetime_value,
                    text_value

                FROM read_parquet(?)

                WHERE sensor_id = ?
                  AND occurred_at >= ?
                  AND occurred_at <= ?

                ORDER BY
                    occurred_at DESC,
                    event_id DESC

                LIMIT ?
                """,
                [
                    str(
                        self.history_cache_file
                    ),
                    sensor_id,
                    start,
                    end,
                    limit,
                ],
            )

            rows = self._fetch_dicts(
                cursor
            )

        # Аналогично PostgreSQL repository:
        # SQL берёт сначала самые новые,
        # ML получает от старых к новым.
        rows.reverse()

        return rows

    def _ensure_history_cache(
        self,
    ) -> None:
        if self._history_cache_is_current():
            return

        self._rebuild_history_cache()

        if not self._history_cache_is_current():
            raise RuntimeError(
                "Failed to build ML history cache"
            )

    def _history_cache_is_current(
        self,
    ) -> bool:
        if (
            not self.history_cache_file.exists()
            or not self.history_metadata_file.exists()
        ):
            return False

        try:
            metadata = json.loads(
                self.history_metadata_file
                .read_text(
                    encoding="utf-8"
                )
            )

            source_stat = (
                self.events_file.stat()
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return False

        return (
            metadata.get("cache_version")
            == CACHE_VERSION
            and metadata.get(
                "source_path"
            )
            == str(self.events_file)
            and metadata.get(
                "source_size"
            )
            == source_stat.st_size
            and metadata.get(
                "source_mtime_ns"
            )
            == source_stat.st_mtime_ns
            and metadata.get(
                "lookback_hours"
            )
            == self.CACHE_LOOKBACK_HOURS
        )

    def _rebuild_history_cache(
        self,
    ) -> None:
        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Гарантируем, что latest_events.parquet
        # существует и соответствует текущему CSV.
        self.event_source.get_latest_events()

        latest_cache_file = (
            self.event_source.cache_file
        )

        temporary_file = (
            self.cache_dir
            / (
                "ml_history_"
                f"{self.CACHE_LOOKBACK_HOURS}h"
                ".tmp.parquet"
            )
        )

        temporary_metadata_file = (
            self.cache_dir
            / (
                "ml_history_"
                f"{self.CACHE_LOOKBACK_HOURS}h"
                ".tmp.json"
            )
        )

        for path in (
            temporary_file,
            temporary_metadata_file,
        ):
            if path.exists():
                path.unlink()

        source_path = self._sql_literal(
            self.events_file
        )

        latest_path = self._sql_literal(
            latest_cache_file
        )

        output_path = self._sql_literal(
            temporary_file
        )

        source_sql = (
            self.event_source
            ._typed_events_sql(
                source_path
            )
        )

        query = f"""
            WITH source AS (
                {source_sql}
            ),

            latest AS (
                SELECT
                    sensor_id,
                    occurred_at AS as_of

                FROM read_parquet(
                    {latest_path}
                )

                WHERE
                    sensor_id IS NOT NULL
                    AND occurred_at IS NOT NULL
            )

            SELECT
                source.event_id,
                source.sensor_id,
                source.occurred_at,
                source.value_type,
                source.numeric_value,
                source.datetime_value,
                source.text_value

            FROM source

            INNER JOIN latest
                ON (
                    latest.sensor_id
                    = source.sensor_id
                )

            WHERE
                source.event_id
                    IS NOT NULL

                AND source.occurred_at
                    IS NOT NULL

                AND source.value_type
                    IN (
                        'numeric',
                        'binary',
                        'datetime',
                        'text'
                    )

                AND source.occurred_at
                    >= (
                        latest.as_of
                        - INTERVAL
                            '{self.CACHE_LOOKBACK_HOURS}'
                            HOUR
                    )

                AND source.occurred_at
                    <= latest.as_of
        """

        try:
            with self._connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                        {query}
                    )
                    TO {output_path}
                    (
                        FORMAT PARQUET,
                        COMPRESSION ZSTD
                    )
                    """
                )

            temporary_file.replace(
                self.history_cache_file
            )

            source_stat = (
                self.events_file.stat()
            )

            metadata = {
                "cache_version": (
                    CACHE_VERSION
                ),
                "source_path": str(
                    self.events_file
                ),
                "source_size": (
                    source_stat.st_size
                ),
                "source_mtime_ns": (
                    source_stat.st_mtime_ns
                ),
                "lookback_hours": (
                    self.CACHE_LOOKBACK_HOURS
                ),
            }

            temporary_metadata_file.write_text(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            temporary_metadata_file.replace(
                self.history_metadata_file
            )

        except Exception:
            for path in (
                temporary_file,
                temporary_metadata_file,
            ):
                if path.exists():
                    path.unlink()

            raise

    @staticmethod
    def _connect():
        return duckdb.connect(
            database=":memory:",
            read_only=False,
        )

    @staticmethod
    def _fetch_dicts(
        cursor,
    ) -> list[dict[str, Any]]:
        column_names = [
            item[0]
            for item in cursor.description
        ]

        return [
            dict(
                zip(
                    column_names,
                    row,
                )
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _sql_literal(
        path: Path,
    ) -> str:
        escaped = str(path).replace(
            "'",
            "''",
        )

        return f"'{escaped}'"
