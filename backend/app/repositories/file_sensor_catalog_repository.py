import csv
import os
from pathlib import Path
from typing import Any

from app.repositories.sensor_catalog_repository import (
    SensorCatalogRepository,
)


REQUIRED_COLUMNS = {
    "ид_канала_данных",
    "тип_инж_системы",
    "тип_датчика",
    "тег_инженерной_системы",
    "название_датчика",
    "ид_объект",
}


class FileSensorCatalogRepository(
    SensorCatalogRepository
):
    """
    Read-only sensor catalog backed by the source CSV.

    Source data is not copied to PostgreSQL.
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

        self._sensors: dict[
            int,
            dict[str, Any],
        ] | None = None

    def get_sensor_ids(
        self,
        engineering_system: str | None = None,
        sensor_type: str | None = None,
    ) -> list[int]:
        sensors = self._load_sensors()

        result: list[int] = []

        for sensor_id, metadata in sensors.items():
            if (
                engineering_system is not None
                and metadata["engineering_system"]
                != engineering_system
            ):
                continue

            if (
                sensor_type is not None
                and metadata["sensor_type"]
                != sensor_type
            ):
                continue

            result.append(sensor_id)

        return sorted(result)

    def get_sensor_metadata(
        self,
        sensor_id: int,
    ) -> dict[str, Any] | None:
        sensors = self._load_sensors()

        metadata = sensors.get(sensor_id)

        if metadata is None:
            return None

        return dict(metadata)

    def _load_sensors(
        self,
    ) -> dict[int, dict[str, Any]]:
        if self._sensors is not None:
            return self._sensors

        file_path = self._find_channels_file()

        sensors: dict[
            int,
            dict[str, Any],
        ] = {}

        with file_path.open(
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

            reader = csv.DictReader(
                file,
                dialect=dialect,
            )

            if reader.fieldnames is None:
                raise RuntimeError(
                    "Channels CSV has no header"
                )

            fieldnames = {
                name.strip()
                for name in reader.fieldnames
            }

            missing = (
                REQUIRED_COLUMNS
                - fieldnames
            )

            if missing:
                raise RuntimeError(
                    "Channels CSV is missing columns: "
                    + ", ".join(
                        sorted(missing)
                    )
                )

            for row in reader:
                sensor_id = self._parse_int(
                    row.get(
                        "ид_канала_данных"
                    )
                )

                if sensor_id is None:
                    continue

                sensors[sensor_id] = {
                    "sensor_id": sensor_id,
                    "engineering_system": (
                        self._clean(
                            row.get(
                                "тип_инж_системы"
                            )
                        )
                    ),
                    "sensor_type": (
                        self._clean(
                            row.get(
                                "тип_датчика"
                            )
                        )
                    ),
                    "engineering_system_tag": (
                        self._clean(
                            row.get(
                                "тег_инженерной_системы"
                            )
                        )
                    ),
                    "sensor_name": (
                        self._clean(
                            row.get(
                                "название_датчика"
                            )
                        )
                    ),
                    "object_id": (
                        self._parse_int(
                            row.get(
                                "ид_объект"
                            )
                        )
                    ),
                }

        self._sensors = sensors

        return sensors

    def _find_channels_file(
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

            if REQUIRED_COLUMNS.issubset(
                columns
            ):
                return candidate

        raise RuntimeError(
            "Sensor catalog CSV was not found "
            f"under {self.source_path}"
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
    def _clean(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @staticmethod
    def _parse_int(
        value: str | None,
    ) -> int | None:
        cleaned = (
            FileSensorCatalogRepository
            ._clean(value)
        )

        if cleaned is None:
            return None

        try:
            return int(cleaned)
        except ValueError:
            try:
                return int(
                    float(cleaned)
                )
            except ValueError:
                return None
