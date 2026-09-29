"""Real import -> dataset-scoped UI, concurrent forecasts and inspection workflow."""
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from time import monotonic, sleep
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app.core.dependencies import get_ml_service
from app.db.database import engine
from app.services import forecast_jobs
from main import app
from tests.test_dataset_import import api, source_files, upload, PreparedPredictionMLService  # noqa: F401


def wait_for_job(dataset_id):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        job = forecast_jobs.latest_job(engine, dataset_id)
        if job and job["status"] not in {"running", "stopping"}:
            return job
        sleep(0.02)
    raise AssertionError("Forecast batch did not finish")


def prepared(api):
    client, _, ids = api
    files, _ = source_files()
    dataset_id = upload(client, ids, files)
    assert client.post(f"/api/datasets/{dataset_id}/prepare").status_code == 202
    return client, dataset_id


def test_real_catalog_and_inspection_lifecycle(api):
    client, dataset_id = prepared(api)
    base = f"/api/datasets/{dataset_id}"
    dispatcher = {"X-Employee-ID": "1001"}
    technician = {"X-Employee-ID": "2001"}
    other = {"X-Employee-ID": "2002"}
    initial = client.get(base + "/workspace", headers=dispatcher)
    assert initial.status_code == 200, initial.text
    data = initial.json()
    assert [sensor["id"] for sensor in data["sensors"]] == [196746]
    assert data["objects"][0]["name"] == "Объект из загруженного справочника"
    assert data["checks"] == []
    details = client.get(base + "/sensors/196746", headers=dispatcher)
    assert details.status_code == 200, details.text
    assert details.json()["sensor"]["name"] == "Газ ПК27"
    assert details.json()["object"]["name"] == "Объект из загруженного справочника"
    assert len(details.json()["events"]) == 10
    assert details.json()["events"][0]["value"] == "Обнаружен газ"
    assert details.json()["checks"] == [] and details.json()["history"] == []
    assert client.get(base + "/sensors/42", headers=dispatcher).status_code == 404
    body = {"sensor_id": 196746, "assignee_id": "2001", "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    assert client.post(base + "/checks", json=body, headers=technician).status_code == 403
    assert client.post(base + "/checks", json={**body, "sensor_id": 42}, headers=dispatcher).status_code == 404
    response = client.post(base + "/checks", json=body, headers=dispatcher)
    assert response.status_code == 201, response.text
    check = response.json()
    details = client.get(base + "/sensors/196746", headers=dispatcher).json()
    assert details["checks"][0]["id"] == check["id"]
    assert details["history"][0]["action"] == "Назначена проверка. Исполнитель: Алексей К."
    assert client.post(base + "/checks", json=body, headers=dispatcher).status_code == 409
    assert client.get(base + "/workspace", headers=other).json()["checks"] == []
    assert client.get(base + "/workspace", headers=other).json()["sensors"] == []
    endpoint = base + f"/checks/{check['id']}"
    assert client.patch(endpoint, json={"action": "start", "revision": 0}, headers=dispatcher).status_code == 403
    assert client.patch(endpoint, json={"action": "complete", "revision": 0}, headers=technician).status_code == 409
    check = client.patch(endpoint, json={"action": "start", "revision": 0}, headers=technician).json()
    assert check["status"] == "В работе"
    report = {"action": "complete", "revision": check["revision"], "outcome": "unresolved", "work_description": "Осмотр датчика", "result": "Нужна замена"}
    assert client.patch(endpoint, json={**report, "result": " "}, headers=technician).status_code == 422
    check = client.patch(endpoint, json=report, headers=technician).json()
    assert check["status"] == "В работе" and check["completed_at"] is None
    assert client.patch(endpoint, json=report, headers=technician).status_code == 409  # stale revision
    check = client.patch(endpoint, json={**report, "revision": check["revision"], "outcome": "fixed", "result": "Датчик заменён"}, headers=technician).json()
    assert check["status"] == "Завершена" and check["completed_at"]
    assert client.get(base + "/workspace", headers=dispatcher).json()["checks"][0]["result"] == "Датчик заменён"
    history = client.get(base + "/sensors/196746", headers=dispatcher).json()["history"]
    assert [entry["action"] for entry in history] == [
        "Проверка завершена: неисправность устранена",
        "Сохранён отчёт: неисправность не устранена, проверка остаётся в работе",
        "Техспециалист начал проверку",
        "Назначена проверка. Исполнитель: Алексей К.",
    ]
    # Another imported DB cannot see or mutate this check.
    _, second = prepared(api)
    assert client.get(f"/api/datasets/{second}/workspace", headers=dispatcher).json()["checks"] == []
    assert client.patch(f"/api/datasets/{second}/checks/{check['id']}", json={"action": "start", "revision": 0}, headers=technician).status_code == 404


def test_batch_endpoint_and_individual_share_results(api, monkeypatch):
    monkeypatch.setattr(forecast_jobs, "LOCK_ID", 418739211)
    client, dataset_id = prepared(api)
    ml = PreparedPredictionMLService()
    app.dependency_overrides[get_ml_service] = lambda: ml
    base = f"/api/datasets/{dataset_id}/forecasts"
    assert client.get(base).json() == {"job": None, "predictions": []}
    response = client.post(base)
    assert response.status_code == 202, response.text
    job = wait_for_job(UUID(dataset_id))
    assert job["total"] == job["predicted"] == 1
    assert ml.request == (UUID(dataset_id), 196746)
    result = client.get(base).json()["predictions"][0]
    assert result["result"]["probability"] == 0.25
    individual = client.get(f"/api/ml/predict/196746?dataset_id={dataset_id}")
    assert individual.json() == result["result"]
    ml.request = None
    assert client.post(base).status_code == 202
    assert wait_for_job(UUID(dataset_id))["predicted"] == 1
    assert ml.request is None  # Reuse completed predictions on restart/retry.


def test_bounded_parallelism_partial_failures_and_restart_recovery(api, monkeypatch):
    _, dataset_id = prepared(api)
    dataset_id = UUID(dataset_id)
    forecast_jobs.ensure_tables(engine)
    monkeypatch.setattr(forecast_jobs, "LOCK_ID", 418739212)
    monkeypatch.setattr(forecast_jobs, "WORKERS", 2)
    barrier, lock = Barrier(2), Lock()
    active = peak = 0

    class Service:
        def predict_dataset(self, dataset, sensor):
            nonlocal active, peak
            assert dataset == dataset_id
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if sensor in {1, 2}:
                    barrier.wait(timeout=3)  # Fails if the worker is accidentally sequential.
                if sensor == 3:
                    response = httpx.Response(409, json={"detail": "Нет истории"}, request=httpx.Request("POST", "http://ml-test"))
                    raise httpx.HTTPStatusError("no history", request=response.request, response=response)
                if sensor == 4:
                    raise httpx.ConnectError("offline")
                return {"sensor_id": sensor, "probability": 0.2, "horizon_hours": 168, "model_version": "test"}
            finally:
                with lock:
                    active -= 1

    forecast_jobs.start_job(engine, dataset_id, [1, 2, 3, 4, 5], Service())
    job = wait_for_job(dataset_id)
    assert peak == 2
    assert job["status"] == "completed"
    assert (job["completed"], job["predicted"], job["skipped"], job["failed"]) == (5, 3, 1, 1)
    # Emulate a terminated server: durable running row, but no advisory lock.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO public.astra_forecast_jobs(id,dataset_id,status,total) VALUES (:id,:dataset,'running',5)"), {"id": uuid4(), "dataset": dataset_id})
    interrupted = forecast_jobs.latest_job(engine, dataset_id)
    assert interrupted["status"] == "interrupted"
    assert len(forecast_jobs.predictions(engine, dataset_id)) == 5


def test_batch_stop_finishes_inflight_work_and_can_resume(api, monkeypatch):
    _, dataset_id = prepared(api)
    dataset_id = UUID(dataset_id)
    monkeypatch.setattr(forecast_jobs, "LOCK_ID", 418739213)
    monkeypatch.setattr(forecast_jobs, "WORKERS", 2)
    started, release, lock = Event(), Event(), Lock()
    called = []

    class Service:
        def predict_dataset(self, dataset, sensor):
            assert dataset == dataset_id
            with lock:
                called.append(sensor)
                if len(called) == 2:
                    started.set()
            assert release.wait(timeout=3)
            return {"sensor_id": sensor, "probability": 0.2, "horizon_hours": 168, "model_version": "test"}

    forecast_jobs.start_job(engine, dataset_id, [1, 2, 3, 4, 5], Service())
    assert started.wait(timeout=3)
    assert forecast_jobs.stop_job(engine, dataset_id)["status"] == "stopping"
    release.set()
    stopped = wait_for_job(dataset_id)
    assert stopped["status"] == "stopped"
    assert (stopped["completed"], stopped["predicted"]) == (2, 2)
    assert set(called) == {1, 2}
    with pytest.raises(ValueError, match="Активный расчёт"):
        forecast_jobs.stop_job(engine, dataset_id)

    # A later run keeps completed results and processes only the remainder.
    forecast_jobs.start_job(engine, dataset_id, [1, 2, 3, 4, 5], Service())
    resumed = wait_for_job(dataset_id)
    assert resumed["status"] == "completed"
    assert resumed["completed"] == resumed["predicted"] == 5


def test_batch_transport_parallelism_stop_resume_and_partial_results(api, monkeypatch):
    _, dataset_id = prepared(api)
    dataset_id = UUID(dataset_id)
    monkeypatch.setattr(forecast_jobs, "LOCK_ID", 418739214)
    monkeypatch.setattr(forecast_jobs, "WORKERS", 2)
    monkeypatch.setattr(forecast_jobs, "BATCH_SIZE", 2)
    started, release, lock = Event(), Event(), Lock()
    called = []

    class Service:
        def predict_dataset_batch(self, dataset, sensors):
            assert dataset == dataset_id
            with lock:
                called.append(sensors)
                if len(called) == 2:
                    started.set()
            assert release.wait(timeout=5)
            return {"predictions": [
                {"sensor_id": sensor, "status": "skipped", "error": "Нет истории"}
                if sensor == 3 else
                {"sensor_id": sensor, "status": "ready", "result": {
                    "sensor_id": sensor, "probability": 0.2, "horizon_hours": 168, "model_version": "test"}}
                for sensor in sensors
            ]}

    forecast_jobs.start_job(engine, dataset_id, list(range(1, 8)), Service())
    assert started.wait(timeout=5)
    forecast_jobs.stop_job(engine, dataset_id)
    release.set()
    stopped = wait_for_job(dataset_id)
    assert stopped["status"] == "stopped"
    assert (stopped["completed"], stopped["predicted"], stopped["skipped"]) == (4, 3, 1)
    assert sorted(called) == [[1, 2], [3, 4]]
    forecast_jobs.start_job(engine, dataset_id, list(range(1, 8)), Service())
    resumed = wait_for_job(dataset_id)
    assert resumed["status"] == "completed"
    assert (resumed["completed"], resumed["predicted"], resumed["skipped"]) == (7, 6, 1)
    assert sorted(called) == [[1, 2], [3, 4], [5, 6], [7]]


def test_malformed_batch_cannot_save_results_for_other_sensors(api):
    _, dataset_id = prepared(api)
    dataset_id = UUID(dataset_id)
    forecast_jobs.ensure_tables(engine)

    class Service:
        def predict_dataset_batch(self, dataset, sensors):
            return {"predictions": [{"sensor_id": 99, "status": "skipped"}]}

    counts = forecast_jobs._predict_batch(engine, Service(), dataset_id, [1, 2])
    assert counts == {"failed": 2}
    results = forecast_jobs.predictions(engine, dataset_id)
    assert [p["sensor_id"] for p in results] == [1, 2]
    assert all(p["status"] == "error" for p in results)
