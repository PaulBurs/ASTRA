"""Persisted import jobs and streamed uploads; no training is started here."""
import fcntl
import json
import logging
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from astra_pipeline.build import build_dataset
from astra_pipeline.csv_input import detect_role
from astra_pipeline.registry import ensure_registry, get_dataset, schema_name, update_dataset
from app.services import forecast_jobs

logger = logging.getLogger(__name__)
GIB = 1024**3


class DatasetImportService:
    def __init__(self, engine, root: Path | None = None):
        self.engine = engine
        self.root = root or Path(os.getenv("DATASET_UPLOAD_DIR") or (
            Path(__file__).resolve().parents[2].parent / "data" / "uploads"
        ))

    def directory(self, dataset_id):
        return self.root / UUID(str(dataset_id)).hex

    def require_free_space(self, source_bytes: int, *, sources_uploaded: bool) -> None:
        # Includes uploaded CSV, logged event storage, ML features, indexes and
        # temporary sorts. Compact imports share raw/clean event storage.
        factor = max(2.0, float(os.getenv("DATASET_STORAGE_EXPANSION_FACTOR", "8")))
        reserve = int(os.getenv("DATASET_STORAGE_RESERVE_BYTES", str(2 * GIB)))
        database_bytes = source_bytes * (factor - (1 if sources_uploaded else 0))
        required = int(database_bytes) + reserve
        free = shutil.disk_usage(self.root).free
        if required > free:
            raise HTTPException(
                507,
                "Недостаточно места для подготовки: требуется ориентировочно "
                f"{required / GIB:.0f} ГБ, доступно {free / GIB:.0f} ГБ",
            )

    def lock(self, dataset_id=None):
        directory = self.directory(dataset_id) if dataset_id else self.root
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / ".lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            detail = (
                "Операция с этим набором уже выполняется"
                if dataset_id else
                "Сейчас подготавливается другой набор данных. Дождитесь завершения и "
                "повторите запуск подготовки — загружать файлы заново не нужно"
            )
            raise HTTPException(409, detail) from None
        return handle

    def create(self, files):
        ensure_registry(self.engine)
        self.root.mkdir(parents=True, exist_ok=True)
        total = sum(file.size for file in files)
        maximum = int(os.getenv("DATASET_MAX_UPLOAD_BYTES", str(64 * 1024**3)))
        if total > maximum:
            raise HTTPException(413, "Превышен допустимый суммарный размер файлов")
        self.require_free_space(total, sources_uploaded=False)
        dataset_id = uuid4()
        entries = [dict(name=file.name, size=file.size, uploaded=False, role=None) for file in files]
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO public.astra_datasets (id, status, stage, files)
                VALUES (:id, 'uploading', 'Ожидание файлов', CAST(:files AS jsonb))
            """), {"id": dataset_id, "files": json.dumps(entries, ensure_ascii=False)})
        return self.status(dataset_id)

    def status(self, dataset_id):
        try:
            job = get_dataset(self.engine, dataset_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        if job["status"] == "preparing" or (job["status"] == "prepared" and not job["error"]):
            # A live worker holds this lock. After a process restart the lock is
            # released, so the UI gets an actionable error instead of polling forever.
            try:
                handle = self.lock(dataset_id)
            except HTTPException:
                return job
            with handle:
                job = get_dataset(self.engine, dataset_id)
                if job["status"] == "preparing":
                    update_dataset(self.engine, dataset_id, status="error",
                                   stage="Подготовка прервана",
                                   error="Сервис перезапустился во время подготовки. Загрузите файлы новым набором")
                    job = get_dataset(self.engine, dataset_id)
                elif job["status"] == "prepared" and not job["error"]:
                    update_dataset(self.engine, dataset_id, stage="Данные готовы. Повторите проверку ML",
                                   error="Проверка подключения ML была прервана")
                    job = get_dataset(self.engine, dataset_id)
        return job

    async def upload(self, dataset_id, index: int, request):
        # One file per raw HTTP request: stream directly to the persistent volume,
        # avoiding multipart's temporary copy of multi-gigabyte files in /tmp.
        self.status(dataset_id)
        with self.lock(dataset_id):
            job = get_dataset(self.engine, dataset_id)
            if job["status"] != "uploading":
                raise HTTPException(409, "Набор уже передан на подготовку")
            if index < 0 or index >= len(job["files"]):
                raise HTTPException(404, "Файл не найден в списке загрузки")
            item = job["files"][index]
            if item["uploaded"]:
                raise HTTPException(409, "Файл уже загружен")
            directory = self.directory(dataset_id)
            partial, destination = directory / f"{index}.part", directory / f"{index}.csv"
            received = 0
            try:
                with partial.open("wb") as target:
                    async for chunk in request.stream():
                        received += len(chunk)
                        if received > item["size"]:
                            raise HTTPException(413, "Размер файла превышает заявленный")
                        target.write(chunk)
                    if received != item["size"]:
                        raise HTTPException(400, "Файл передан не полностью")
                try:
                    role = detect_role(partial)
                except (ValueError, UnicodeError) as error:
                    raise HTTPException(422, f"{item['name']}: {error}") from error
                partial.replace(destination)
                item.update(uploaded=True, role=role)
                update_dataset(self.engine, dataset_id, files=job["files"], stage="Файл загружен: " + item["name"])
            finally:
                partial.unlink(missing_ok=True)
        return self.status(dataset_id)

    def start(self, dataset_id, background_tasks):
        self.status(dataset_id)
        handle = self.lock(dataset_id)
        build_lock = None
        try:
            job = get_dataset(self.engine, dataset_id)
            if job["status"] != "uploading":
                raise HTTPException(409, "Подготовка этого набора уже была запущена")
            files = job["files"]
            if not all(file["uploaded"] for file in files):
                raise HTTPException(409, "Дождитесь завершения загрузки всех файлов")
            roles = [file["role"] for file in files]
            if roles.count("channels") != 1 or roles.count("objects") != 1:
                raise HTTPException(422, "Нужны ровно один справочник каналов и один справочник объектов")
            if not any(role in {"events", "prepared_events"} for role in roles):
                raise HTTPException(422, "Выберите хотя бы один журнал событий")
            if roles.count("states") > 1:
                raise HTTPException(422, "Выбран более чем один справочник состояний")
            self.require_free_space(
                sum(int(file["size"]) for file in files),
                sources_uploaded=True,
            )
            build_lock = self.lock()
            update_dataset(self.engine, dataset_id, status="preparing", stage="Запуск подготовки", error=None)
            background_tasks.add_task(self.run, dataset_id, handle, build_lock)
        except BaseException:
            handle.close()
            if build_lock:
                build_lock.close()
            raise
        return get_dataset(self.engine, dataset_id)

    def discard(self, dataset_id, *, include_prepared=False):
        self.status(dataset_id)
        if include_prepared:
            running_forecast = forecast_jobs.latest_job(self.engine, dataset_id)
            if running_forecast and running_forecast["status"] in {"running", "stopping"}:
                raise HTTPException(
                    409,
                    "Сначала дождитесь завершения расчёта прогнозов, затем повторите удаление",
                )
        with self.lock(dataset_id):
            job = get_dataset(self.engine, dataset_id)
            allowed = {"uploading", "error"}
            if include_prepared:
                allowed.update({"prepared", "ready"})
            if job["status"] not in allowed:
                detail = (
                    "Подтвердите полное удаление подготовленной базы"
                    if job["status"] in {"prepared", "ready"}
                    else "Нельзя удалить базу, пока выполняется подготовка"
                )
                raise HTTPException(409, detail)
            with self.engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name(dataset_id)} CASCADE"))
                conn.execute(text("DELETE FROM public.astra_datasets WHERE id=:id"), {"id": UUID(str(dataset_id))})
        # The registry row owns checks, forecasts and prediction rows through
        # cascading foreign keys. Remove the private uploaded-file directory too.
        shutil.rmtree(self.directory(dataset_id), ignore_errors=True)

    def clear_uploads(self, dataset_id, file_count):
        for index in range(file_count):
            for suffix in ("csv", "part"):
                (self.directory(dataset_id) / f"{index}.{suffix}").unlink(missing_ok=True)

    def run(self, dataset_id, handle, build_lock):
        with handle, build_lock:
            job = None
            try:
                job = get_dataset(self.engine, dataset_id)
                files = [dict(file, path=str(self.directory(dataset_id) / f"{index}.csv"))
                         for index, file in enumerate(job["files"])]
                counts = build_dataset(
                    self.engine, dataset_id, files,
                    lambda stage, counts: update_dataset(self.engine, dataset_id, stage=stage, counts=counts),
                )
                update_dataset(self.engine, dataset_id, status="prepared", counts=counts,
                               stage="Данные подготовлены. Проверка чтения ML-движком")
                # Originals are browser uploads in our private UUID directory. The
                # source files on the user's computer are never changed.
            except Exception as error:
                logger.exception("Dataset %s failed", dataset_id)
                update_dataset(self.engine, dataset_id, status="error", stage="Ошибка подготовки", error=str(error))
                return
            finally:
                if job is not None:
                    self.clear_uploads(dataset_id, len(job["files"]))
            self.validate_ml(dataset_id)

    def validate_ml(self, dataset_id):
        job = get_dataset(self.engine, dataset_id)
        if job["status"] not in {"prepared", "ready"}:
            raise HTTPException(409, "Данные ещё не подготовлены")
        try:
            base_url = os.getenv("ML_SERVICE_URL", "").rstrip("/")
            if not base_url:
                raise ValueError("ML_SERVICE_URL не настроен")
            response = httpx.post(f"{base_url}/datasets/{dataset_id}/validate", timeout=30)
            response.raise_for_status()
            result = response.json()
            if (result.get("dataset_id") != str(dataset_id) or result.get("status") != "ready"
                    or result.get("row_count") != job["counts"]["feature_rows"]):
                raise ValueError("ML-движок вернул несовместимый результат проверки")
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("ML validation failed for %s: %s", dataset_id, error)
            update_dataset(self.engine, dataset_id, status="prepared",
                           stage="Данные готовы. Не удалось проверить подключение ML",
                           error="Проверьте доступность ML-сервиса и повторите проверку")
        else:
            update_dataset(self.engine, dataset_id, status="ready", ml_check=result,
                           stage="Данные доступны ML-движку", error=None)
        return get_dataset(self.engine, dataset_id)
