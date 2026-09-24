from pathlib import Path
from typing import Any

from app.data_sources.duckdb_event_source import (
    DuckDBEventSource,
)
from app.repositories.file_sensor_catalog_repository import (
    FileSensorCatalogRepository,
)
from app.repositories.sensor_repository import (
    SensorRepository,
)


class FileSensorRepository(
    SensorRepository
):
    """
    Датчики ASTRA напрямую из внешних CSV.

    Метаданные:
        channels CSV

    Последнее состояние:
        ext_journal_prepared CSV

    Исходные файлы не копируются
    в PostgreSQL.
    """

    def __init__(
        self,
        source_path: str | Path | None = None,
    ):
        self.catalog = (
            FileSensorCatalogRepository(
                source_path=source_path,
            )
        )

        self.events = DuckDBEventSource(
            source_path=source_path,
        )

    def get_all(self) -> list[dict]:
        sensor_ids = (
            self.catalog.get_sensor_ids()
        )

        latest_events = (
            self.events.get_latest_events()
        )

        result: list[dict] = []

        for sensor_id in sensor_ids:
            metadata = (
                self.catalog
                .get_sensor_metadata(
                    sensor_id
                )
            )

            if metadata is None:
                continue

            event = latest_events.get(
                sensor_id
            )

            result.append(
                self._to_sensor(
                    metadata,
                    event,
                )
            )

        return result

    def get_by_id(
        self,
        sensor_id: int,
    ) -> dict | None:
        metadata = (
            self.catalog
            .get_sensor_metadata(
                sensor_id
            )
        )

        if metadata is None:
            return None

        event = (
            self.events
            .get_latest_event(
                sensor_id
            )
        )

        return self._to_sensor(
            metadata,
            event,
        )

    @classmethod
    def _to_sensor(
        cls,
        metadata: dict[str, Any],
        event: dict[str, Any] | None,
    ) -> dict:
        value_type: str | None = None
        value: float | str | None = None
        occurred_at = None

        if event is not None:
            value_type = event.get(
                "value_type"
            )

            occurred_at = event.get(
                "occurred_at"
            )

            value = cls._event_value(
                event
            )

        # Настоящий ML-risk подключим
        # отдельно.
        status = "OK"
        risk = 0.0

        sensor_id = int(
            metadata["sensor_id"]
        )

        return {
            "id": sensor_id,
            "name": (
                metadata.get(
                    "sensor_name"
                )
                or f"Sensor {sensor_id}"
            ),
            "type": (
                metadata.get(
                    "sensor_type"
                )
                or "Неизвестный тип"
            ),
            "engineering_system": (
                metadata.get(
                    "engineering_system"
                )
            ),
            "object_id": (
                metadata.get(
                    "object_id"
                )
            ),
            "value_type": value_type,
            "value": value,
            "occurred_at": occurred_at,
            "status": status,
            "risk": risk,
        }

    @staticmethod
    def _event_value(
        event: dict[str, Any],
    ) -> float | str | None:
        value_type = event.get(
            "value_type"
        )

        if value_type in {
            "numeric",
            "binary",
        }:
            numeric_value = event.get(
                "numeric_value"
            )

            if numeric_value is not None:
                return float(
                    numeric_value
                )

            return None

        if value_type == "text":
            return event.get(
                "text_value"
            )

        if value_type == "datetime":
            datetime_value = event.get(
                "datetime_value"
            )

            if datetime_value is None:
                return None

            if hasattr(
                datetime_value,
                "isoformat",
            ):
                return (
                    datetime_value
                    .isoformat()
                )

            return str(
                datetime_value
            )

        return None
