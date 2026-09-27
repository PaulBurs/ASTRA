"""Read prepared feature batches. This module never trains or invokes a model."""
from uuid import UUID

from sqlalchemy import text

from astra_pipeline.registry import get_dataset, schema_name
from lct_features import ALL_COLUMNS
from ml.src.data import create_ml_engine


def prepared_dataset(engine, dataset_id):
    job = get_dataset(engine, dataset_id)
    if job["status"] not in {"prepared", "ready"}:
        raise ValueError("Набор данных ещё не подготовлен")
    return job


def iter_feature_batches(dataset_id: UUID, batch_size=10_000, *, engine=None):
    """The training button can consume this iterator later, without loading all rows."""
    if not 1 <= batch_size <= 100_000:
        raise ValueError("batch_size must be between 1 and 100000")
    owned_engine = engine is None
    engine = engine or create_ml_engine()
    try:
        prepared_dataset(engine, dataset_id)
        schema = schema_name(dataset_id)
        with engine.connect() as conn:
            result = conn.execution_options(stream_results=True, yield_per=batch_size).execute(text(
                f'SELECT * FROM {schema}.v_dataset_ml ORDER BY "ид_канала_данных", "дата_время_события"'
            ))
            for rows in result.mappings().partitions(batch_size):
                yield [dict(row) for row in rows]
    finally:
        if owned_engine:
            engine.dispose()


def validate_dataset(dataset_id: UUID, *, engine=None):
    owned_engine = engine is None
    engine = engine or create_ml_engine()
    try:
        job = prepared_dataset(engine, dataset_id)
        schema = schema_name(dataset_id)
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT * FROM {schema}.v_dataset_ml LIMIT 5")).mappings().all()
        if not rows:
            raise ValueError("Подготовленная таблица признаков пуста")
        if list(rows[0]) != ALL_COLUMNS:
            raise ValueError("Столбцы подготовленной таблицы не совпадают с контрактом ML")
        return {
            "dataset_id": str(dataset_id), "status": "ready",
            "row_count": job["counts"]["feature_rows"],
            "columns": ALL_COLUMNS, "sample": [dict(row) for row in rows],
        }
    finally:
        if owned_engine:
            engine.dispose()
