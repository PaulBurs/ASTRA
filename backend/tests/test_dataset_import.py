"""Upload -> actual pipeline SQL -> actual ML reader, using disposable UUID schemas."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.datasets import get_import_service
from app.core.dependencies import get_ml_service
from app.db.database import engine
from app.ml.service import MLService
from app.services.dataset_import_service import DatasetImportService
from astra_pipeline.csv_input import CHANNELS, OBJECTS, RAW, prepared_event
from astra_pipeline.registry import ensure_registry, schema_name, update_dataset
from lct_features import ALL_COLUMNS, OnlineFeaturizer
from main import app
from ml.src.api import app as ml_app
from ml.src.datasets import iter_feature_batches, validate_dataset


class PreparedPredictionMLService(MLService):
    def __init__(self):
        self.request = None

    def health(self):
        return True

    def train(self):
        raise AssertionError("Import must not train the model")

    def predict(self, prediction_input):
        raise AssertionError("Prepared datasets must use dataset inference")

    def predict_dataset(self, dataset_id, sensor_id):
        self.request = (dataset_id, sensor_id)
        return {
            "sensor_id": sensor_id,
            "probability": 0.25,
            "horizon_hours": 168,
            "model_version": "trained-test-v1",
        }


def csv_bytes(columns, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def source_files():
    events = []
    for i in range(8):
        ts = datetime(2024, 1, 1, 12) + timedelta(minutes=i)
        events.append([i + 1, 196746, ts.date(), ts.time(), "false", f"0.{i + 1:02}"])
    # Separate files overlap, as often happens when selecting yearly/sample exports.
    return {
        "channels.csv": csv_bytes(CHANNELS, [[196746, "Газовая охрана", "Газовый датчик", "tag", "Газ ПК27", 5122]]),
        "objects.csv": csv_bytes(OBJECTS, [[5122, 3, 5, "controlHouse", "Объект из загруженного справочника"]]),
        "part1.csv": csv_bytes(RAW, events[:5]),
        "part2.csv": csv_bytes(RAW, events[4:] + [
            [99, 999999999, "2024-01-01", "12:10:00", "f", "Норма"],
            [100, 196746, "2024-01-01", "12:11:00", "true", "Обнаружен газ"],
        ]),
    }, events


@pytest.fixture
def api(tmp_path, monkeypatch):
    ensure_registry(engine)
    service = DatasetImportService(engine, tmp_path)
    app.dependency_overrides[get_import_service] = lambda: service
    ml_client = TestClient(ml_app)
    training_calls = []
    monkeypatch.setattr("ml.src.api.train", lambda: training_calls.append(True))
    monkeypatch.setattr("ml.src.api.validate_dataset", lambda id: validate_dataset(id, engine=engine))
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml-test")

    def ml_post(url, **kwargs):
        response = ml_client.post(url.removeprefix("http://ml-test"))
        return httpx.Response(response.status_code, json=response.json(), request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.dataset_import_service.httpx.post", ml_post)
    ids = []
    client = TestClient(app)
    yield client, service, ids
    assert not training_calls, "Import must never start training"
    app.dependency_overrides.clear()
    for id in ids:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name(id)} CASCADE"))
            conn.execute(text("DELETE FROM public.astra_datasets WHERE id=:id"), {"id": UUID(id)})


def upload(client, ids, files):
    response = client.post("/api/datasets", json={"files": [
        {"name": name, "size": len(data)} for name, data in files.items()
    ]})
    assert response.status_code == 201, response.text
    id = response.json()["id"]
    ids.append(id)
    for index, data in enumerate(files.values()):
        response = client.put(f"/api/datasets/{id}/files/{index}", content=data)
        assert response.status_code == 200, response.text
    return id


def test_files_to_pipeline_to_ml(api):
    client, _, ids = api
    files, raw_events = source_files()
    id = upload(client, ids, files)
    assert client.post(f"/api/datasets/{id}/prepare").status_code == 202
    status = client.get(f"/api/datasets/{id}").json()
    assert status["status"] == "ready", status
    assert status["counts"] == {
        "source_rows": 11, "event_rows": 9, "duplicate_rows": 1,
        "orphan_rows": 1, "feature_rows": 9, "channels": 1, "objects": 1, "feature_days": 120,
    }
    assert status["ml_check"]["columns"] == ALL_COLUMNS
    assert status["ml_check"]["sample"]
    # Exercise the exact batching entry point intended for the later training button.
    batches = list(iter_feature_batches(UUID(id), batch_size=4, engine=engine))
    assert [len(batch) for batch in batches] == [4, 4, 1]
    rows = [row for batch in batches for row in batch]
    fz = OnlineFeaturizer(on_late="raise")
    for row, raw in zip(rows, raw_events):
        expected = fz.process_raw(raw[1], f"{raw[2]} {raw[3]}", raw[4], raw[5])
        for column in ALL_COLUMNS:
            if isinstance(expected[column], float):
                assert row[column] == pytest.approx(expected[column], abs=2e-5)
            else:
                assert row[column] == expected[column]
    assert rows[-1]["тревожное_событие"] == 1
    assert rows[-1]["код_состояния"] == 19
    # The new dataset works regardless of the legacy DATA_SOURCE=agent/dummy setting.
    response = client.get(f"/api/sensors?dataset_id={id}")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Газ ПК27"
    assert response.json()[0]["value"] == "Обнаружен газ"
    prediction_service = PreparedPredictionMLService()
    app.dependency_overrides[get_ml_service] = lambda: prediction_service
    response = client.get(f"/api/ml/predict/196746?dataset_id={id}")
    assert response.status_code == 200, response.text
    assert response.json()["model_version"] == "trained-test-v1"
    assert response.json()["horizon_hours"] == 168
    assert prediction_service.request == (UUID(id), 196746)
    assert client.post(f"/api/datasets/{id}/prepare").status_code == 409
    assert client.put(f"/api/datasets/{id}/files/0", content=b"bad").status_code == 409
    assert client.delete(f"/api/datasets/{id}").status_code == 409


def test_ml_unavailable_can_retry_without_rebuilding(api, monkeypatch):
    client, _, ids = api
    files, _ = source_files()
    id = upload(client, ids, files)
    original_post = httpx.post
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr("app.services.dataset_import_service.httpx.post", fail)
    client.post(f"/api/datasets/{id}/prepare")
    job = client.get(f"/api/datasets/{id}").json()
    assert job["status"] == "prepared", job
    monkeypatch.setattr("app.services.dataset_import_service.httpx.post", original_post)
    monkeypatch.setattr("app.services.dataset_import_service.build_dataset", lambda *a, **k: pytest.fail("Rebuild was not requested"))
    response = client.post(f"/api/datasets/{id}/validate-ml")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_confirmed_delete_removes_prepared_database_and_related_records(api):
    client, service, ids = api
    files, _ = source_files()
    dataset_id = upload(client, ids, files)
    assert client.post(f"/api/datasets/{dataset_id}/prepare").status_code == 202
    assert client.get(f"/api/datasets/{dataset_id}").json()["status"] == "ready"

    base = f"/api/datasets/{dataset_id}"
    dispatcher = {"X-Employee-ID": "1001"}
    assert client.get(base + "/workspace", headers=dispatcher).status_code == 200
    prediction_service = PreparedPredictionMLService()
    app.dependency_overrides[get_ml_service] = lambda: prediction_service
    assert client.get(f"/api/ml/predict/196746?dataset_id={dataset_id}").status_code == 200
    check = client.post(base + "/checks", headers=dispatcher, json={
        "sensor_id": 196746,
        "assignee_id": "2001",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    })
    assert check.status_code == 201, check.text

    assert client.delete(base).status_code == 409
    assert service.directory(dataset_id).exists()
    assert client.delete(base + "?confirm_delete=true").status_code == 403
    assert client.delete(base + "?confirm_delete=true", headers=dispatcher).status_code == 204
    assert client.get(base).status_code == 404
    assert not service.directory(dataset_id).exists()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema_name(dataset_id)}).scalar() is None
        for table in ("astra_predictions", "astra_checks", "astra_check_history"):
            count = conn.execute(text(f"SELECT count(*) FROM public.{table} WHERE dataset_id=:id"), {"id": UUID(dataset_id)}).scalar_one()
            assert count == 0


def test_invalid_rows_fail_without_publishing_dataset(api):
    client, _, ids = api
    files, _ = source_files()
    files["part1.csv"] = csv_bytes(RAW, [[1, 196746, "2028-01-01", "00:00:00", "f", "0.1"]])
    id = upload(client, ids, files)
    client.post(f"/api/datasets/{id}/prepare")
    job = client.get(f"/api/datasets/{id}").json()
    assert job["status"] == "error"
    assert "2019–2026" in job["error"]
    with engine.connect() as conn:
        assert not conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname=:name"), {"name": schema_name(id)}).first()
    assert client.get(f"/api/sensors?dataset_id={id}").status_code == 409


def test_upload_validation_and_incomplete_file(api):
    client, _, ids = api
    files, _ = source_files()
    manifest = [{"name": name, "size": len(data)} for name, data in files.items()]
    response = client.post("/api/datasets", json={"files": [dict(manifest[0], name="../channels.csv"), *manifest[1:]]})
    assert response.status_code == 422
    response = client.post("/api/datasets", json={"files": manifest})
    id = response.json()["id"]
    ids.append(id)
    assert client.put(f"/api/datasets/{id}/files/0", content=b"partial").status_code == 400
    assert client.post(f"/api/datasets/{id}/prepare").status_code == 409
    assert not client.get(f"/api/datasets/{id}").json()["files"][0]["uploaded"]
    assert client.put(f"/api/datasets/{id}/files/0", content=files["channels.csv"]).status_code == 200


def test_single_worker_and_interrupted_state(api):
    client, service, ids = api
    files, _ = source_files()
    id = upload(client, ids, files)
    with service.lock():
        assert client.post(f"/api/datasets/{id}/prepare").status_code == 409
    with service.lock(id):
        update_dataset(engine, id, status="preparing")
        assert client.get(f"/api/datasets/{id}").json()["status"] == "preparing"
    # Simulates process termination: persistent status but no worker holds the lock.
    assert client.get(f"/api/datasets/{id}").json()["status"] == "error"


def test_prepared_status_during_ml_check_and_after_interruption(api):
    client, service, ids = api
    files, _ = source_files()
    id = upload(client, ids, files)
    with service.lock(id):
        update_dataset(engine, id, status="prepared")
        assert client.get(f"/api/datasets/{id}").json()["error"] is None
    job = client.get(f"/api/datasets/{id}").json()
    assert job["status"] == "prepared"
    assert job["error"]


def test_discard_incomplete_upload_reclaims_files(api):
    client, service, ids = api
    files, _ = source_files()
    id = upload(client, ids, files)
    assert list(service.directory(id).glob("*.csv"))
    with service.lock(id):
        assert client.delete(f"/api/datasets/{id}").status_code == 409
    assert client.delete(f"/api/datasets/{id}").status_code == 204
    assert not list(service.directory(id).glob("*.csv"))
    assert client.get(f"/api/datasets/{id}").status_code == 404


@pytest.mark.parametrize("value,kind,number", [
    ("01.01.1970 03:00:01", "binary", 1),
    ("05.03.2026 09:11:35", "datetime", None),
    ("0.07", "numeric", 0.07), ("Обнаружен газ", "text", None),
])
def test_raw_adapter_uses_pipeline_parser(value, kind, number):
    row = dict(zip(RAW, ["1", "196746", "2024-01-01", "12:00:00", "true", value]))
    result = prepared_event(row, "events")
    assert result[2] == "t"
    assert result[5:7] == (kind, number)


def test_free_space_estimate_follows_measured_peak(tmp_path, monkeypatch):
    # 15 GB of journals: ~57 GB before upload, ~42 GB more once uploaded (was 122 GB).
    from collections import namedtuple
    from fastapi import HTTPException
    from app.services import dataset_import_service as module

    gib = module.GIB
    usage = namedtuple("usage", "total used free")
    service = DatasetImportService(engine, tmp_path)
    monkeypatch.delenv("DATASET_STORAGE_EXPANSION_FACTOR", raising=False)
    monkeypatch.delenv("DATASET_STORAGE_RESERVE_BYTES", raising=False)
    for free, uploaded, ok in ((58, False, True), (56, False, False), (43, True, True), (41, True, False)):
        monkeypatch.setattr(module.shutil, "disk_usage", lambda _: usage(0, 0, free * gib))
        if ok:
            service.require_free_space(15 * gib, sources_uploaded=uploaded)
        else:
            with pytest.raises(HTTPException) as error:
                service.require_free_space(15 * gib, sources_uploaded=uploaded)
            assert error.value.status_code == 507
