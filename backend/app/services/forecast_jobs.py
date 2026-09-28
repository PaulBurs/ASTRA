"""Durable prediction results and a bounded, restart-safe batch queue."""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Thread
from uuid import uuid4

import httpx
from sqlalchemy import text

from app.schemas.ml import MLPredictionResponse

log = logging.getLogger(__name__)
LOCK_ID = 418739201  # One batch per ML service, including across API processes.
WORKERS = max(1, min(4, int(os.getenv("FORECAST_WORKERS", "2"))))


def ensure_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(418739202)"))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS public.astra_predictions (
            dataset_id uuid NOT NULL REFERENCES public.astra_datasets(id) ON DELETE CASCADE,
            sensor_id bigint NOT NULL, status text NOT NULL, result jsonb,
            error text, updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_id, sensor_id))'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS public.astra_forecast_jobs (
            id uuid PRIMARY KEY, dataset_id uuid NOT NULL REFERENCES public.astra_datasets(id) ON DELETE CASCADE,
            status text NOT NULL, total integer NOT NULL, completed integer NOT NULL DEFAULT 0,
            predicted integer NOT NULL DEFAULT 0, skipped integer NOT NULL DEFAULT 0,
            failed integer NOT NULL DEFAULT 0, error text, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now())'''))


def save_prediction(engine, dataset_id, sensor_id, result=None, *, status="ready", error=None):
    if result is not None:
        result = MLPredictionResponse.model_validate(result).model_dump()
        if result["sensor_id"] != sensor_id:
            raise ValueError("ML returned a different sensor")
    with engine.begin() as conn:
        conn.execute(text('''INSERT INTO public.astra_predictions(dataset_id,sensor_id,status,result,error)
            VALUES (:dataset,:sensor,:status,CAST(:result AS jsonb),:error)
            ON CONFLICT(dataset_id,sensor_id) DO UPDATE SET status=excluded.status,
                result=excluded.result,error=excluded.error,updated_at=now()'''),
            dict(dataset=dataset_id, sensor=sensor_id, status=status,
                 result=json.dumps(result) if result else None, error=error))
    return result


def predictions(engine, dataset_id):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text('''SELECT sensor_id,status,result,error,updated_at
            FROM public.astra_predictions WHERE dataset_id=:id ORDER BY sensor_id'''),
            {"id": dataset_id}).mappings()]


def latest_job(engine, dataset_id):
    # A crashed process releases its session lock. Recover its persisted status,
    # retaining completed predictions so the next run can resume cheaply.
    with engine.begin() as conn:
        unlocked = conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}).scalar()
        if unlocked:
            try:
                conn.execute(text("UPDATE public.astra_forecast_jobs SET status='interrupted', "
                                  "error='Расчёт прерван перезапуском сервера. Запустите его повторно.', "
                                  "updated_at=now() WHERE status='running'"))
                conn.execute(text("UPDATE public.astra_forecast_jobs SET status='stopped', "
                                  "error=NULL, updated_at=now() WHERE status='stopping'"))
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
        row = conn.execute(text('''SELECT * FROM public.astra_forecast_jobs
            WHERE dataset_id=:id ORDER BY created_at DESC LIMIT 1'''), {"id": dataset_id}).mappings().first()
        return dict(row) if row else None


def _predict_one(engine, ml_service, dataset_id, sensor_id):
    try:
        save_prediction(engine, dataset_id, sensor_id, ml_service.predict_dataset(dataset_id, sensor_id))
        return "predicted"
    except httpx.HTTPStatusError as exc:
        detail = "ML-сервис не смог рассчитать прогноз"
        try:
            payload = exc.response.json()
            if isinstance(payload.get("detail"), str):
                detail = payload["detail"]
        except ValueError:
            pass
        skipped = exc.response.status_code in {404, 409}
        save_prediction(engine, dataset_id, sensor_id, status="skipped" if skipped else "error", error=detail)
        return "skipped" if skipped else "failed"
    except Exception:
        log.exception("Prediction failed for dataset %s sensor %s", dataset_id, sensor_id)
        save_prediction(engine, dataset_id, sensor_id, status="error", error="Не удалось рассчитать прогноз. Повторите попытку.")
        return "failed"


def _run(engine, lock_conn, job_id, dataset_id, sensor_ids, ml_service):
    try:
        stored = predictions(engine, dataset_id)
        cached_ready = {p["sensor_id"] for p in stored if p["status"] == "ready"}.intersection(sensor_ids)
        cached_skipped = {p["sensor_id"] for p in stored if p["status"] == "skipped"}.intersection(sensor_ids)
        cached = cached_ready | cached_skipped
        done = len(cached)
        with engine.begin() as conn:
            state = conn.execute(text("UPDATE public.astra_forecast_jobs SET completed=:done,predicted=:predicted,skipped=:skipped "
                                      "WHERE id=:id RETURNING status"),
                                 {"id": job_id, "done": done, "predicted": len(cached_ready),
                                  "skipped": len(cached_skipped)}).scalar_one_or_none()
        stop_requested = state != "running"
        remaining = iter(sensor for sensor in sensor_ids if sensor not in cached)
        # Submit only WORKERS tasks at once; 11,000 sensors do not become 11,000
        # simultaneous HTTP requests or resident feature matrices.
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            pending = set()
            for _ in range(0 if stop_requested else WORKERS):
                sensor = next(remaining, None)
                if sensor is not None:
                    pending.add(pool.submit(_predict_one, engine, ml_service, dataset_id, sensor))
            while pending:
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    outcome = future.result()
                    with engine.begin() as conn:
                        state = conn.execute(text(f"UPDATE public.astra_forecast_jobs SET completed=completed+1, {outcome}={outcome}+1, updated_at=now() WHERE id=:id RETURNING status"), {"id": job_id}).scalar_one_or_none()
                    stop_requested = stop_requested or state != "running"
                    sensor = None if stop_requested else next(remaining, None)
                    if sensor is not None:
                        pending.add(pool.submit(_predict_one, engine, ml_service, dataset_id, sensor))
        with engine.begin() as conn:
            conn.execute(text("UPDATE public.astra_forecast_jobs SET "
                              "status=CASE WHEN status='stopping' THEN 'stopped' ELSE 'completed' END, "
                              "updated_at=now() WHERE id=:id"), {"id": job_id})
    except Exception:
        log.exception("Batch prediction failed")
        with engine.begin() as conn:
            conn.execute(text("UPDATE public.astra_forecast_jobs SET status='error',error='Ошибка расчёта. Можно повторить запуск.',updated_at=now() WHERE id=:id"), {"id": job_id})
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            lock_conn.commit()
        finally:
            lock_conn.close()


def start_job(engine, dataset_id, sensor_ids, ml_service):
    previous = latest_job(engine, dataset_id)
    lock_conn = engine.connect()
    locked = lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}).scalar()
    lock_conn.commit()
    if not locked:
        lock_conn.close()
        if previous and previous["status"] in {"running", "stopping"}:
            return previous
        raise ValueError("Уже рассчитывается прогноз другого набора данных. Дождитесь завершения.")
    try:
        job_id = uuid4()
        with engine.begin() as conn:
            job = dict(conn.execute(text('''INSERT INTO public.astra_forecast_jobs(id,dataset_id,status,total)
                VALUES (:id,:dataset,'running',:total) RETURNING *'''),
                dict(id=job_id, dataset=dataset_id, total=len(sensor_ids))).mappings().one())
        Thread(target=_run, args=(engine, lock_conn, job_id, dataset_id, sensor_ids, ml_service), daemon=True).start()
        return job
    except Exception:
        lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
        lock_conn.commit()
        lock_conn.close()
        raise


def stop_job(engine, dataset_id):
    """Request cooperative cancellation without discarding completed predictions."""
    with engine.begin() as conn:
        job = conn.execute(text('''SELECT * FROM public.astra_forecast_jobs
            WHERE dataset_id=:id ORDER BY created_at DESC LIMIT 1 FOR UPDATE'''),
            {"id": dataset_id}).mappings().first()
        if not job or job["status"] not in {"running", "stopping"}:
            raise ValueError("Активный расчёт прогнозов не найден")
        if job["status"] == "running":
            job = conn.execute(text('''UPDATE public.astra_forecast_jobs
                SET status='stopping',error=NULL,updated_at=now()
                WHERE id=:id RETURNING *'''), {"id": job["id"]}).mappings().one()
        return dict(job)
