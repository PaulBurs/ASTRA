from sqlalchemy import text

from app.db.database import engine
from app.repositories.sensor_repository import (
    SensorRepository,
)


class PostgresSensorRepository(SensorRepository):
    """
    Датчики ASTRA из PostgreSQL.

    Метаданные:
        astra_channels

    Последнее состояние:
        ext_journal_prepared
    """

    def get_all(self) -> list[dict]:
        query = text(
            """
            SELECT
                c.sensor_id,
                c.sensor_name,
                c.sensor_type,
                c.engineering_system,
                c.object_id,

                e.numeric_value,
                e.datetime_value,
                e.text_value,
                e.value_type,
                e.occurred_at

            FROM astra_channels AS c

            LEFT JOIN LATERAL (
                SELECT
                    numeric_value,
                    datetime_value,
                    text_value,
                    value_type,
                    occurred_at
                FROM ext_journal_prepared
                WHERE sensor_id = c.sensor_id
                ORDER BY
                    occurred_at DESC,
                    event_id DESC
                LIMIT 1
            ) AS e ON TRUE

            ORDER BY c.sensor_id
            """
        )

        with engine.connect() as connection:
            rows = (
                connection.execute(query)
                .mappings()
                .all()
            )

        return [
            self._to_sensor(dict(row))
            for row in rows
        ]

    def get_by_id(
        self,
        sensor_id: int,
    ) -> dict | None:
        query = text(
            """
            SELECT
                c.sensor_id,
                c.sensor_name,
                c.sensor_type,
                c.engineering_system,
                c.object_id,

                e.numeric_value,
                e.datetime_value,
                e.text_value,
                e.value_type,
                e.occurred_at

            FROM astra_channels AS c

            LEFT JOIN LATERAL (
                SELECT
                    numeric_value,
                    datetime_value,
                    text_value,
                    value_type,
                    occurred_at
                FROM ext_journal_prepared
                WHERE sensor_id = c.sensor_id
                ORDER BY
                    occurred_at DESC,
                    event_id DESC
                LIMIT 1
            ) AS e ON TRUE

            WHERE c.sensor_id = :sensor_id
            """
        )

        with engine.connect() as connection:
            row = (
                connection.execute(
                    query,
                    {"sensor_id": sensor_id},
                )
                .mappings()
                .first()
            )

        if row is None:
            return None

        return self._to_sensor(dict(row))

    @staticmethod
    def _to_sensor(row: dict) -> dict:
        value_type = row["value_type"]
        value: float | str | None = None

        if value_type in {
            "numeric",
            "binary",
        }:
            if row["numeric_value"] is not None:
                value = float(
                    row["numeric_value"]
                )

        elif value_type == "text":
            value = row["text_value"]

        elif value_type == "datetime":
            datetime_value = row[
                "datetime_value"
            ]

            if datetime_value is not None:
                value = (
                    datetime_value.isoformat()
                )

        # Пока настоящая модель риска
        # к dashboard не подключена.
        status = "OK"
        risk = 0.0

        return {
            "id": row["sensor_id"],
            "name": (
                row["sensor_name"]
                or f"Sensor {row['sensor_id']}"
            ),
            "type": row["sensor_type"],
            "engineering_system": (
                row["engineering_system"]
            ),
            "object_id": row["object_id"],
            "value_type": value_type,
            "value": value,
            "occurred_at": row["occurred_at"],
            "status": status,
            "risk": risk,
        }
