"""Disposable, deterministic PostgreSQL fixture for inference equivalence/benchmarks."""
from contextlib import contextmanager
from uuid import uuid4
from sqlalchemy import text
from astra_pipeline.registry import ensure_registry, schema_name


@contextmanager
def inference_dataset(engine, channels=64):
    dataset = uuid4()
    schema = schema_name(dataset)
    ensure_registry(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO astra_datasets(id,status,stage,files) VALUES (:id,'ready','inference test','[]')"), {'id': dataset})
            conn.execute(text(f'CREATE SCHEMA {schema}'))
            conn.execute(text(f'''CREATE TABLE {schema}.map_channel AS
                SELECT ch::bigint AS "ид_канала_данных", 2::smallint AS "код_типа_датчика",
                    (42+ch%2)::smallint AS "код_объекта", 1::smallint AS "код_комплекса",
                    0::smallint AS "объект_охранный", 5::smallint AS "пикет"
                FROM generate_series(1,:channels) ch UNION ALL
                SELECT 9000,2,42,1,0,5 UNION ALL SELECT 9001,2,42,1,0,5'''), {'channels': channels})
            conn.execute(text(f'''CREATE TABLE {schema}.dataset_ml AS
                SELECT m.*, TIMESTAMP '2024-12-31 23:45:30' - h*interval '6 hours'
                    + (m."ид_канала_данных"%3)*interval '7 seconds' AS "дата_время_события",
                    0::smallint AS "код_типа_значения", (CASE WHEN h%13=0 THEN 19 ELSE 0 END)::smallint AS "код_состояния",
                    0::smallint AS "состояние_техническое", (CASE WHEN h%13=0 AND m."ид_канала_данных"<>3 THEN 1 ELSE 0 END)::smallint AS "тревожное_событие",
                    0::smallint AS "тревожное_по_справочнику", 0::smallint AS "служебное_значение",
                    0::smallint AS "мало_истории_значение", 0::smallint AS "мало_истории_dt",
                    (CASE WHEN h%7=0 THEN NULL ELSE (h%10)*0.05 END)::real AS "значение",
                    (h%5*0.1)::real AS "значение_z", 9.0::real AS "лог_dt", 0.1::real AS "лог_dt_z"
                FROM {schema}.map_channel m CROSS JOIN generate_series(0,365) h
                WHERE m."ид_канала_данных"<9000'''))
            conn.execute(text(f'''INSERT INTO {schema}.dataset_ml SELECT 9000,2,42,1,0,5,
                TIMESTAMP '2021-12-31',0,0,0,0,0,0,0,0,0.1,0.0,1.0,0.0'''))
            conn.execute(text(f'CREATE INDEX ON {schema}.dataset_ml ("ид_канала_данных", "дата_время_события")'))
            conn.execute(text(f'ANALYZE {schema}.dataset_ml'))
            conn.execute(text(f'''CREATE VIEW {schema}.latest_sensor_events AS
                SELECT DISTINCT "ид_канала_данных" FROM {schema}.dataset_ml'''))
        yield dataset
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
            conn.execute(text('DELETE FROM astra_datasets WHERE id=:id'), {'id': dataset})
