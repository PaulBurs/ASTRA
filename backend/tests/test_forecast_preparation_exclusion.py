"""Model inference and data preparation never run at the same time."""
import json
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text

from app.db.database import engine
from app.services import forecast_jobs
from app.services.dataset_import_service import DatasetImportService
from astra_pipeline.registry import ensure_registry, get_dataset


@pytest.fixture
def dataset():
    ensure_registry(engine)
    forecast_jobs.ensure_tables(engine)
    created = []

    def make(status, files=None):
        dataset_id = uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO public.astra_datasets(id,status,stage,files) "
                              "VALUES (:id,:status,'test',CAST(:files AS jsonb))"),
                         {"id": dataset_id, "status": status, "files": json.dumps(files or [])})
        created.append(dataset_id)
        return dataset_id

    yield make
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public.astra_datasets WHERE id = ANY(:ids)"), {"ids": created})


def test_forecast_is_refused_while_any_dataset_is_being_prepared(dataset):
    ready = dataset("ready")
    dataset("preparing")
    assert forecast_jobs.preparing(engine)
    with pytest.raises(ValueError, match="подготовка данных"):
        forecast_jobs.start_job(engine, ready, [1, 2], ml_service=None)
    # the refused start released the batch lock and created no job
    assert not forecast_jobs.running(engine)
    assert forecast_jobs.latest_job(engine, ready) is None


def test_preparation_is_refused_while_a_forecast_is_running(dataset, tmp_path):
    files = [dict(name=name, size=1, uploaded=True, role=role) for name, role in
             (("c.csv", "channels"), ("o.csv", "objects"), ("e.csv", "events"))]
    uploaded = dataset("uploading", files)
    service = DatasetImportService(engine, root=tmp_path)
    with engine.connect() as holder:          # what a live forecast batch holds
        assert holder.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": forecast_jobs.LOCK_ID}).scalar()
        holder.commit()
        try:
            assert forecast_jobs.running(engine)
            tasks = BackgroundTasks()
            with pytest.raises(HTTPException) as error:
                service.start(uploaded, tasks)
            assert error.value.status_code == 409
            assert "расчёт прогнозов" in error.value.detail
            assert not tasks.tasks
            assert get_dataset(engine, uploaded)["status"] == "uploading"   # the upload can be prepared later
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": forecast_jobs.LOCK_ID})
            holder.commit()
    assert not forecast_jobs.running(engine)
