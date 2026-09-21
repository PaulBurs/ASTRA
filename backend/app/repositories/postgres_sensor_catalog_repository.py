from sqlalchemy import text

from app.db.database import engine
from app.repositories.sensor_catalog_repository import (
    SensorCatalogRepository,
)


class PostgresSensorCatalogRepository(
    SensorCatalogRepository
):
    """Каталог каналов из PostgreSQL."""

    def get_sensor_ids(
        self,
        engineering_system: str | None = None,
        sensor_type: str | None = None,
    ) -> list[int]:
        conditions: list[str] = []
        params: dict = {}

        if engineering_system is not None:
            conditions.append(
                "engineering_system = :engineering_system"
            )
            params["engineering_system"] = (
                engineering_system
            )

        if sensor_type is not None:
            conditions.append(
                "sensor_type = :sensor_type"
            )
            params["sensor_type"] = sensor_type

        where_clause = ""

        if conditions:
            where_clause = (
                "WHERE " + " AND ".join(conditions)
            )

        query = text(
            f"""
            SELECT sensor_id
            FROM astra_channels
            {where_clause}
            ORDER BY sensor_id
            """
        )

        with engine.connect() as connection:
            result = connection.execute(
                query,
                params,
            )

            return [
                row.sensor_id
                for row in result
            ]

    def get_sensor_metadata(
        self,
        sensor_id: int,
    ) -> dict | None:
        query = text(
            """
            SELECT
                sensor_id,
                engineering_system,
                sensor_type,
                engineering_system_tag,
                sensor_name,
                object_id
            FROM astra_channels
            WHERE sensor_id = :sensor_id
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

        return dict(row)
