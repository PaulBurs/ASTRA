import csv
import json
import os
import threading
from pathlib import Path
from typing import Any

import duckdb


EVENT_COLUMNS = {
    "ид_события",
    "ид_канала_данных",
    "тревожное_raw",
    "значение_датчика_raw",
    "дата_время_события",
    "тип_значения",
    "значение_число",
    "значение_дата_время",
    "значение_текст",
}

CACHE_VERSION = 1

# Source Agent handles sync FastAPI endpoints in a thread pool.
# Multiple requests can therefore try to build the same cache at once.
# A module-level lock serializes cache rebuilds across repository instances.
LATEST_EVENTS_CACHE_LOCK = threading.Lock()


class DuckDBEventSource:
    """
    Read-only access to ext_journal_prepared CSV.

    The source CSV stays in its original location.
    DuckDB queries it directly.

    A small persistent Parquet cache stores only the latest event
    for each sensor. The original CSV is never copied into ASTRA.
    """

    def __init__(
        self,
        source_path: str | Path | None = None,
    ):
        configured_path = (
            source_path
            or os.getenv(
                "SOURCE_DATA_PATH",
                "/data/source",
            )
        )

        self.source_path = Path(
            configured_path
        ).resolve()

        self.events_file = (
            self._find_events_file()
        )

        self.cache_dir = Path(
            os.getenv(
                "SOURCE_CACHE_PATH",
                "/data/cache",
            )
        )

        self.cache_file = (
            self.cache_dir
            / "latest_events.parquet"
        )

        self.cache_metadata_file = (
            self.cache_dir
            / "latest_events.json"
        )

        self._latest_cache: (
            dict[int, dict[str, Any]]
            | None
        ) = None

        self._cache_mtime_ns: int | None = None

    def preview(
        self,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 100:
            raise ValueError(
                "limit must be between 1 and 100"
            )

        query = f"""
            SELECT
                event_id,
                sensor_id,
                alarm_raw,
                sensor_value_raw,
                occurred_at,
                value_type,
                numeric_value,
                datetime_value,
                text_value
            FROM (
                {self._typed_events_sql()}
            )
            LIMIT {int(limit)}
        """

        with self._connect() as connection:
            cursor = connection.execute(
                query,
                [str(self.events_file)],
            )

            return self._fetch_dicts(
                cursor
            )

    def get_latest_event(
        self,
        sensor_id: int,
    ) -> dict[str, Any] | None:
        """
        Return the latest event for one sensor.

        The first call builds/loads the shared latest-events cache.
        Subsequent lookups are in-memory and do not rescan the 21 GB CSV.
        """
        latest_events = (
            self.get_latest_events()
        )

        event = latest_events.get(
            sensor_id
        )

        if event is None:
            return None

        return dict(event)

    def get_latest_events(
        self,
    ) -> dict[int, dict[str, Any]]:
        """
        Return the latest event for every sensor.

        Priority:
        1. in-process memory cache;
        2. persistent Parquet cache;
        3. one full CSV scan to rebuild the Parquet cache.

        Cache rebuilding is protected by a shared lock because the
        Source Agent may execute several synchronous requests at once.
        """

        if self._cache_is_current():
            assert self._latest_cache is not None

            return {
                sensor_id: dict(event)
                for sensor_id, event
                in self._latest_cache.items()
            }

        persistent = (
            self._load_persistent_cache()
        )

        if persistent is None:
            with LATEST_EVENTS_CACHE_LOCK:
                # Another request may have finished the cache while
                # this request was waiting for the lock.
                persistent = (
                    self._load_persistent_cache()
                )

                if persistent is None:
                    self._rebuild_persistent_cache()

                    persistent = (
                        self._load_persistent_cache()
                    )

        if persistent is None:
            raise RuntimeError(
                "Failed to build latest-events cache"
            )

        self._latest_cache = persistent

        self._cache_mtime_ns = (
            self.events_file
            .stat()
            .st_mtime_ns
        )

        return {
            sensor_id: dict(event)
            for sensor_id, event
            in persistent.items()
        }

    def _cache_is_current(
        self,
    ) -> bool:
        if (
            self._latest_cache is None
            or self._cache_mtime_ns is None
        ):
            return False

        try:
            current_mtime = (
                self.events_file
                .stat()
                .st_mtime_ns
            )
        except OSError:
            return False

        return (
            current_mtime
            == self._cache_mtime_ns
        )

    def _load_persistent_cache(
        self,
    ) -> dict[int, dict[str, Any]] | None:
        if (
            not self.cache_file.exists()
            or not self.cache_metadata_file.exists()
        ):
            return None

        try:
            metadata = json.loads(
                self.cache_metadata_file
                .read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None

        try:
            source_stat = (
                self.events_file.stat()
            )
        except OSError:
            return None

        if (
            metadata.get("cache_version")
            != CACHE_VERSION
            or metadata.get("source_path")
            != str(self.events_file)
            or metadata.get("source_size")
            != source_stat.st_size
            or metadata.get(
                "source_mtime_ns"
            )
            != source_stat.st_mtime_ns
        ):
            return None

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    SELECT
                        event_id,
                        sensor_id,
                        alarm_raw,
                        sensor_value_raw,
                        occurred_at,
                        value_type,
                        numeric_value,
                        datetime_value,
                        text_value
                    FROM read_parquet(?)
                    ORDER BY sensor_id
                    """,
                    [str(self.cache_file)],
                )

                rows = self._fetch_dicts(
                    cursor
                )
        except (
            duckdb.Error,
            OSError,
        ):
            return None

        return {
            int(row["sensor_id"]): row
            for row in rows
            if row["sensor_id"] is not None
        }

    def _rebuild_persistent_cache(
        self,
    ) -> None:
        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_file = (
            self.cache_dir
            / "latest_events.tmp.parquet"
        )

        if temporary_file.exists():
            temporary_file.unlink()

        source_path = self._sql_literal(
            self.events_file
        )

        cache_path = self._sql_literal(
            temporary_file
        )

        source_sql = (
            self._typed_events_sql(
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

                    arg_max(
                        struct_pack(
                            event_id := event_id,
                            alarm_raw := alarm_raw,
                            sensor_value_raw :=
                                sensor_value_raw,
                            occurred_at := occurred_at,
                            value_type := value_type,
                            numeric_value :=
                                numeric_value,
                            datetime_value :=
                                datetime_value,
                            text_value := text_value
                        ),

                        struct_pack(
                            occurred_at :=
                                occurred_at,
                            event_id :=
                                coalesce(
                                    event_id,
                                    -1
                                )
                        )
                    ) AS event

                FROM source

                WHERE
                    sensor_id IS NOT NULL
                    AND occurred_at IS NOT NULL

                GROUP BY sensor_id
            )

            SELECT
                event.event_id
                    AS event_id,

                sensor_id,

                event.alarm_raw
                    AS alarm_raw,

                event.sensor_value_raw
                    AS sensor_value_raw,

                event.occurred_at
                    AS occurred_at,

                event.value_type
                    AS value_type,

                event.numeric_value
                    AS numeric_value,

                event.datetime_value
                    AS datetime_value,

                event.text_value
                    AS text_value

            FROM latest

            ORDER BY sensor_id
        """

        try:
            with self._connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                        {query}
                    )
                    TO {cache_path}
                    (
                        FORMAT PARQUET,
                        COMPRESSION ZSTD
                    )
                    """
                )

            temporary_file.replace(
                self.cache_file
            )

            source_stat = (
                self.events_file.stat()
            )

            metadata = {
                "cache_version": CACHE_VERSION,
                "source_path": str(
                    self.events_file
                ),
                "source_size": (
                    source_stat.st_size
                ),
                "source_mtime_ns": (
                    source_stat.st_mtime_ns
                ),
            }

            temporary_metadata_file = (
                self.cache_dir
                / "latest_events.tmp.json"
            )

            temporary_metadata_file.write_text(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            temporary_metadata_file.replace(
                self.cache_metadata_file
            )

        except Exception:
            if temporary_file.exists():
                temporary_file.unlink()

            temporary_metadata_file = (
                self.cache_dir
                / "latest_events.tmp.json"
            )

            if temporary_metadata_file.exists():
                temporary_metadata_file.unlink()

            raise

    @staticmethod
    def _typed_events_sql(
        source_expression: str = "?",
    ) -> str:
        return f"""
            SELECT
                try_cast(
                    "ид_события"
                    AS BIGINT
                ) AS event_id,

                try_cast(
                    "ид_канала_данных"
                    AS BIGINT
                ) AS sensor_id,

                nullif(
                    trim("тревожное_raw"),
                    ''
                ) AS alarm_raw,

                nullif(
                    trim(
                        "значение_датчика_raw"
                    ),
                    ''
                ) AS sensor_value_raw,

                coalesce(
                    try_cast(
                        nullif(
                            trim(
                                "дата_время_события"
                            ),
                            ''
                        )
                        AS TIMESTAMP
                    ),

                    try_strptime(
                        nullif(
                            trim(
                                "дата_время_события"
                            ),
                            ''
                        ),
                        '%d.%m.%Y %H:%M:%S'
                    ),

                    try_strptime(
                        nullif(
                            trim(
                                "дата_время_события"
                            ),
                            ''
                        ),
                        '%d.%m.%Y %H:%M'
                    )
                ) AS occurred_at,

                nullif(
                    trim("тип_значения"),
                    ''
                ) AS value_type,

                try_cast(
                    replace(
                        nullif(
                            trim(
                                "значение_число"
                            ),
                            ''
                        ),
                        ',',
                        '.'
                    )
                    AS DOUBLE
                ) AS numeric_value,

                coalesce(
                    try_cast(
                        nullif(
                            trim(
                                "значение_дата_время"
                            ),
                            ''
                        )
                        AS TIMESTAMP
                    ),

                    try_strptime(
                        nullif(
                            trim(
                                "значение_дата_время"
                            ),
                            ''
                        ),
                        '%d.%m.%Y %H:%M:%S'
                    ),

                    try_strptime(
                        nullif(
                            trim(
                                "значение_дата_время"
                            ),
                            ''
                        ),
                        '%d.%m.%Y %H:%M'
                    )
                ) AS datetime_value,

                nullif(
                    trim("значение_текст"),
                    ''
                ) AS text_value

            FROM read_csv_auto(
                {source_expression},
                header = true,
                all_varchar = true
            )
        """

    def _find_events_file(
        self,
    ) -> Path:
        if self.source_path.is_file():
            candidates = [
                self.source_path
            ]
        else:
            candidates = sorted(
                self.source_path.glob(
                    "*.csv"
                )
            )

        for candidate in candidates:
            try:
                columns = (
                    self._read_columns(
                        candidate
                    )
                )
            except (
                OSError,
                UnicodeDecodeError,
            ):
                continue

            if EVENT_COLUMNS.issubset(
                columns
            ):
                return candidate

        raise RuntimeError(
            "Events CSV was not found under "
            f"{self.source_path}"
        )

    @staticmethod
    def _read_columns(
        path: Path,
    ) -> set[str]:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            sample = file.read(
                64 * 1024
            )

            file.seek(0)

            try:
                dialect = csv.Sniffer().sniff(
                    sample,
                    delimiters=",;\t|",
                )
            except csv.Error:
                dialect = csv.excel

            reader = csv.reader(
                file,
                dialect=dialect,
            )

            header = next(
                reader,
                [],
            )

            return {
                str(column).strip()
                for column in header
            }

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

