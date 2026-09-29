"""Dataset-scoped catalog, predictions and real inspection records."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from astra_pipeline.registry import schema_name
from app.core.dependencies import require_prepared_dataset, get_ml_service
from app.db.database import engine
from app.repositories.prepared_dataset_repository import PreparedSensorRepository
from app.services import forecast_jobs

router = APIRouter(prefix="/api/datasets/{dataset_id}", tags=["workspace"])
# Same employee IDs as the current application's sign-in screen. These headers
# identify the actor; they are not a replacement for production authentication.
EMPLOYEES = {"1001": "Егор В.", "2001": "Алексей К.", "2002": "Дмитрий П."}


def ready(dataset_id: UUID):
    require_prepared_dataset(dataset_id)
    forecast_jobs.ensure_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(418739203)"))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS public.astra_checks (
            id bigserial PRIMARY KEY, dataset_id uuid NOT NULL REFERENCES public.astra_datasets(id) ON DELETE CASCADE,
            sensor_id bigint NOT NULL, assignee_id text NOT NULL, deadline timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'Новая', outcome text, work_description text, result text,
            created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
            revision integer NOT NULL DEFAULT 0)'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS public.astra_check_history (
            id bigserial PRIMARY KEY,
            check_id bigint NOT NULL REFERENCES public.astra_checks(id) ON DELETE CASCADE,
            dataset_id uuid NOT NULL REFERENCES public.astra_datasets(id) ON DELETE CASCADE,
            sensor_id bigint NOT NULL, actor_id text NOT NULL, action text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())'''))
    return dataset_id


def actor(x_employee_id: str = Header()):
    if x_employee_id not in EMPLOYEES:
        raise HTTPException(403, "Неизвестный сотрудник")
    return x_employee_id


@router.get("/workspace")
def workspace(dataset_id: UUID = Depends(ready), employee: str = Depends(actor)):
    schema = schema_name(dataset_id)
    with engine.connect() as conn:
        objects = [dict(row) for row in conn.execute(text(f'''SELECT "ид_объект" AS id,
            "диспетчерское_название_объекта" AS name FROM {schema}.ref_objects ORDER BY "ид_объект"''')).mappings()]
        checks = [dict(row) for row in conn.execute(text('''SELECT * FROM public.astra_checks
            WHERE dataset_id=:id AND (:dispatcher OR assignee_id=:employee) ORDER BY created_at DESC'''),
            dict(id=dataset_id, dispatcher=employee == "1001", employee=employee)).mappings()]
    sensors = PreparedSensorRepository(engine, dataset_id).get_all()
    if employee != "1001":
        assigned = {row["sensor_id"] for row in checks}
        sensors = [sensor for sensor in sensors if sensor["id"] in assigned]
        object_ids = {sensor["object_id"] for sensor in sensors}
        objects = [obj for obj in objects if obj["id"] in object_ids]
    return {"sensors": sensors, "objects": objects, "checks": checks,
            "assignees": [{"id": key, "name": value} for key, value in EMPLOYEES.items() if key != "1001"]}


@router.get("/sensors/{sensor_id}")
def sensor_details(sensor_id: int, dataset_id: UUID = Depends(ready), employee: str = Depends(actor)):
    """Return only facts stored for this dataset; no generated readings or explanations."""
    sensor = PreparedSensorRepository(engine, dataset_id).get_by_id(sensor_id)
    if sensor is None:
        raise HTTPException(404, "Датчик не найден в выбранной БД")
    schema = schema_name(dataset_id)
    with engine.connect() as conn:
        checks = [dict(row) for row in conn.execute(text('''SELECT * FROM public.astra_checks
            WHERE dataset_id=:dataset AND sensor_id=:sensor
              AND (:dispatcher OR assignee_id=:employee) ORDER BY created_at DESC'''),
            dict(dataset=dataset_id, sensor=sensor_id, dispatcher=employee == "1001", employee=employee)).mappings()]
        if employee != "1001" and not checks:
            raise HTTPException(403, "Датчик не относится к назначенным вам проверкам")
        object_row = conn.execute(text(f'''SELECT "ид_объект" AS id,
            "диспетчерское_название_объекта" AS name, "вид_объекта" AS type
            FROM {schema}.ref_objects WHERE "ид_объект"=:id'''), {"id": sensor["object_id"]}).mappings().first()
        events = [dict(row) for row in conn.execute(text(f'''
            SELECT "ид_события" AS id, "дата_время_события" AS occurred_at,
                   "тип_значения" AS value_type, "значение_число" AS numeric_value,
                   "значение_дата_время" AS datetime_value, "значение_текст" AS text_value,
                   "тревожное_raw" AS alarm
            FROM {schema}.ext_journal_prepared
            WHERE "ид_канала_данных"=:sensor
            ORDER BY "дата_время_события" DESC, "ид_события" DESC LIMIT 20
        '''), {"sensor": sensor_id}).mappings()]
        history = [dict(row) for row in conn.execute(text('''SELECT h.id,h.check_id,h.actor_id,
                   h.action,h.created_at FROM public.astra_check_history h
            WHERE h.dataset_id=:dataset AND h.sensor_id=:sensor
              AND (:dispatcher OR EXISTS (SELECT 1 FROM public.astra_checks c
                    WHERE c.id=h.check_id AND c.assignee_id=:employee))
            ORDER BY h.created_at DESC'''),
            dict(dataset=dataset_id, sensor=sensor_id, dispatcher=employee == "1001", employee=employee)).mappings()]
        prediction = conn.execute(text('''SELECT status,result,error,updated_at
            FROM public.astra_predictions WHERE dataset_id=:dataset AND sensor_id=:sensor'''),
            {"dataset": dataset_id, "sensor": sensor_id}).mappings().first()
    for event in events:
        value_type = event["value_type"]
        value = event["numeric_value"] if value_type in {"numeric", "binary"} else event["datetime_value"] if value_type == "datetime" else event["text_value"]
        event["value"] = value.isoformat() if hasattr(value, "isoformat") else value
        for column in ("numeric_value", "datetime_value", "text_value"):
            event.pop(column)
    if prediction:
        history.append({"id": f"prediction-{sensor_id}", "check_id": None, "actor_id": "ASTRA ML",
                        "action": "Рассчитан прогноз обученной моделью", "created_at": prediction["updated_at"]})
        history.sort(key=lambda row: row["created_at"], reverse=True)
    return {"sensor": sensor, "object": dict(object_row) if object_row else None,
            "events": events, "checks": checks, "history": history,
            "prediction": dict(prediction) if prediction else None,
            "employees": EMPLOYEES}


@router.get("/forecasts")
def forecasts(dataset_id: UUID = Depends(ready)):
    return {"job": forecast_jobs.latest_job(engine, dataset_id), "predictions": forecast_jobs.predictions(engine, dataset_id)}


@router.get("/forecasts/job")
def forecast_job(dataset_id: UUID = Depends(ready)):
    """Only the job state: cheap to poll, unlike the full list of predictions."""
    return {"job": forecast_jobs.latest_job(engine, dataset_id), "preparing": forecast_jobs.preparing(engine)}


@router.post("/forecasts", status_code=202)
def forecast_all(dataset_id: UUID = Depends(ready), ml_service=Depends(get_ml_service)):
    # Sensors of one object go into the same batches: ML reads every object once per batch.
    sensors = PreparedSensorRepository(engine, dataset_id).get_all()
    sensors.sort(key=lambda sensor: (sensor["object_id"] is None, sensor["object_id"] or 0, sensor["id"]))
    sensor_ids = [sensor["id"] for sensor in sensors]
    if not sensor_ids:
        raise HTTPException(409, "В наборе нет датчиков")
    try:
        return forecast_jobs.start_job(engine, dataset_id, sensor_ids, ml_service)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/forecasts/stop", status_code=202)
def stop_forecast(dataset_id: UUID = Depends(ready), employee: str = Depends(actor)):
    if employee != "1001":
        raise HTTPException(403, "Остановка расчёта доступна диспетчеру")
    try:
        return forecast_jobs.stop_job(engine, dataset_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class CheckCreate(BaseModel):
    sensor_id: int
    assignee_id: Literal["2001", "2002"]
    deadline: datetime

    @model_validator(mode="after")
    def future_deadline(self):
        if self.deadline.tzinfo is None or self.deadline <= datetime.now(timezone.utc):
            raise ValueError("Укажите будущий срок проверки с часовым поясом")
        return self


@router.post("/checks", status_code=201)
def create_check(body: CheckCreate, dataset_id: UUID = Depends(ready), employee: str = Depends(actor)):
    if employee != "1001":
        raise HTTPException(403, "Назначение доступно диспетчеру")
    if PreparedSensorRepository(engine, dataset_id).get_by_id(body.sensor_id) is None:
        raise HTTPException(404, "Датчик не найден в выбранной БД")
    with engine.begin() as conn:
        # Serialize duplicate clicks from separate browser tabs.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"check:{dataset_id}:{body.sensor_id}"})
        exists = conn.execute(text("SELECT id FROM public.astra_checks WHERE dataset_id=:id AND sensor_id=:sensor AND status!='Завершена'"), {"id": dataset_id, "sensor": body.sensor_id}).first()
        if exists:
            raise HTTPException(409, "Для этого датчика уже назначена проверка")
        check = dict(conn.execute(text('''INSERT INTO public.astra_checks(dataset_id,sensor_id,assignee_id,deadline)
            VALUES (:id,:sensor_id,:assignee_id,:deadline) RETURNING *'''),
            {"id": dataset_id, **body.model_dump()}).mappings().one())
        conn.execute(text('''INSERT INTO public.astra_check_history(check_id,dataset_id,sensor_id,actor_id,action)
            VALUES (:check,:dataset,:sensor,:actor,:action)'''),
            dict(check=check["id"], dataset=dataset_id, sensor=body.sensor_id, actor=employee,
                 action=f"Назначена проверка. Исполнитель: {EMPLOYEES[body.assignee_id]}"))
        return check


class CheckUpdate(BaseModel):
    revision: int = Field(ge=0)
    action: Literal["start", "complete"]
    outcome: Literal["clear", "fixed", "unresolved"] | None = None
    work_description: str = Field(default="", max_length=10000)
    result: str = Field(default="", max_length=10000)


@router.patch("/checks/{check_id}")
def update_check(check_id: int, body: CheckUpdate, dataset_id: UUID = Depends(ready), employee: str = Depends(actor)):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM public.astra_checks WHERE id=:check AND dataset_id=:dataset FOR UPDATE"),
                           {"check": check_id, "dataset": dataset_id}).mappings().first()
        if not row:
            raise HTTPException(404, "Проверка не найдена")
        if employee != row["assignee_id"]:
            raise HTTPException(403, "Изменение доступно назначенному техспециалисту")
        if row["revision"] != body.revision:
            raise HTTPException(409, "Проверка изменена. Обновите данные")
        if body.action == "start":
            if row["status"] != "Новая":
                raise HTTPException(409, "Проверка уже начата")
            sql = "status='В работе'"
        else:
            if row["status"] != "В работе":
                raise HTTPException(409, "Сначала начните проверку")
            if not body.outcome or not body.result.strip() or not body.work_description.strip():
                raise HTTPException(422, "Укажите результат, выполненные работы и заключение")
            # Unresolved checks stay active and can be completed after follow-up work.
            sql = "status=:status,outcome=:outcome,work_description=:work_description,result=:result,completed_at=:completed"
        updated = dict(conn.execute(text(f"UPDATE public.astra_checks SET {sql},revision=revision+1 WHERE id=:id RETURNING *"),
            {**body.model_dump(), "id": check_id,
             "status": "В работе" if body.outcome == "unresolved" else "Завершена",
             "completed": None if body.outcome == "unresolved" else datetime.now(timezone.utc)}).mappings().one())
        if body.action == "start":
            action = "Техспециалист начал проверку"
        elif body.outcome == "unresolved":
            action = "Сохранён отчёт: неисправность не устранена, проверка остаётся в работе"
        else:
            labels = {"clear": "неисправность не обнаружена", "fixed": "неисправность устранена"}
            action = f"Проверка завершена: {labels[body.outcome]}"
        conn.execute(text('''INSERT INTO public.astra_check_history(check_id,dataset_id,sensor_id,actor_id,action)
            VALUES (:check,:dataset,:sensor,:actor,:action)'''),
            dict(check=check_id, dataset=dataset_id, sensor=row["sensor_id"], actor=employee, action=action))
        return updated
