"""Adapters from an isolated pipeline schema to existing dashboard/prediction contracts."""
from sqlalchemy import text

from astra_pipeline.registry import schema_name
from app.repositories.postgres_sensor_repository import PostgresSensorRepository
from app.repositories.sensor_repository import SensorRepository
from app.repositories.ml_data_repository import MLDataRepository


class PreparedSensorRepository(SensorRepository):
    def __init__(self, engine, dataset_id):
        self.engine, self.schema = engine, schema_name(dataset_id)

    def _query(self, sensor_id=None):
        where = 'WHERE c."ид_канала_данных" = :sensor_id' if sensor_id is not None else ""
        with self.engine.connect() as conn:
            rows = conn.execute(text(f'''
                SELECT c."ид_канала_данных" AS sensor_id,
                       c."название_датчика" AS sensor_name,
                       c."тип_датчика" AS sensor_type,
                       c."тип_инж_системы" AS engineering_system,
                       c."ид_объект" AS object_id,
                       e."значение_число" AS numeric_value,
                       e."значение_дата_время" AS datetime_value,
                       e."значение_текст" AS text_value,
                       e."тип_значения" AS value_type,
                       e."дата_время_события" AS occurred_at
                FROM {self.schema}.ref_channels c
                LEFT JOIN {self.schema}.latest_sensor_events e USING ("ид_канала_данных")
                {where}
                ORDER BY c."ид_канала_данных"
            '''), {"sensor_id": sensor_id}).mappings().all()
        return [PostgresSensorRepository._to_sensor(dict(row)) for row in rows]

    def get_all(self):
        return self._query()

    def get_by_id(self, sensor_id):
        rows = self._query(sensor_id)
        return rows[0] if rows else None


class PreparedMLDataRepository(MLDataRepository):
    def __init__(self, engine, dataset_id):
        self.engine, self.schema = engine, schema_name(dataset_id)

    def get_latest_event_time(self, sensor_id):
        with self.engine.connect() as conn:
            return conn.execute(text(f'''
                SELECT "дата_время_события" FROM {self.schema}.latest_sensor_events
                WHERE "ид_канала_данных" = :id
            '''), {"id": sensor_id}).scalar_one_or_none()

    def get_events(self, sensor_id, start, end, limit=5000):
        if not 1 <= limit <= 5000 or start > end:
            raise ValueError("Invalid history interval or limit")
        with self.engine.connect() as conn:
            rows = conn.execute(text(f'''
                SELECT "ид_события" AS event_id, "дата_время_события" AS occurred_at,
                       "тип_значения" AS value_type, "значение_число" AS numeric_value,
                       "значение_дата_время" AS datetime_value, "значение_текст" AS text_value
                FROM {self.schema}.ext_journal_prepared
                WHERE "ид_канала_данных" = :id AND "дата_время_события" >= :start
                  AND "дата_время_события" <= :end
                ORDER BY "дата_время_события" DESC, "ид_события" DESC LIMIT :limit
            '''), {"id": sensor_id, "start": start, "end": end, "limit": limit}).mappings().all()
        return [dict(row) for row in reversed(rows)]
