"""Shared dataset identity and state; backend and ML use the same PostgreSQL DB."""
import json
from uuid import UUID

from sqlalchemy import text


def schema_name(dataset_id: str | UUID) -> str:
    # Only server-generated UUIDs can become SQL identifiers.
    return "ds_" + UUID(str(dataset_id)).hex


def ensure_registry(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.astra_datasets (
                id UUID PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                files JSONB NOT NULL,
                counts JSONB NOT NULL DEFAULT '{}',
                ml_check JSONB,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))


def get_dataset(engine, dataset_id: str | UUID) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM public.astra_datasets WHERE id = :id"
        ), {"id": UUID(str(dataset_id))}).mappings().first()
    if row is None:
        raise LookupError("Набор данных не найден")
    return dict(row)


def update_dataset(engine, dataset_id: str | UUID, **fields) -> None:
    allowed = {"status", "stage", "files", "counts", "ml_check", "error"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("Invalid dataset update")
    assignments = []
    params = {"id": UUID(str(dataset_id))}
    for key, value in fields.items():
        if key in {"files", "counts", "ml_check"}:
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = json.dumps(value, ensure_ascii=False)
        else:
            assignments.append(f"{key} = :{key}")
            params[key] = value
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE public.astra_datasets SET " + ", ".join(assignments)
            + ", updated_at = now() WHERE id = :id"
        ), params)
