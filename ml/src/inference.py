"""Inference of the trained alarm model directly from a prepared dataset."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from astra_pipeline.registry import schema_name
from ml.src.contracts import PredictionOutput
from ml.src.data import create_ml_engine
from ml.src.datasets import prepared_dataset


MODEL_DIR = Path(os.getenv("ML_MODEL_DIR", Path(__file__).resolve().parents[1] / "out_final"))
ARTIFACTS_PATH = MODEL_DIR / "artifacts.json"
MODEL_PATH = MODEL_DIR / "lgb_model.txt"


class PredictionTargetNotFoundError(LookupError):
    """The selected dataset or sensor cannot be used for prediction."""


@lru_cache(maxsize=1)
def _load_model():
    # These imports are deliberately lazy: the service can still return a useful
    # health response when an image was built without the model dependencies.
    import lightgbm as lgb

    if not ARTIFACTS_PATH.is_file() or not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model artifacts were not found in {MODEL_DIR}")
    artifacts = json.loads(ARTIFACTS_PATH.read_text(encoding="utf-8"))
    booster = lgb.Booster(model_file=str(MODEL_PATH))
    digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()[:10]
    version = f"lightgbm-{artifacts['cfg']['horizon_h']}h-{digest}"
    return booster, artifacts, version


def model_info() -> tuple[bool, str]:
    try:
        _, _, version = _load_model()
        return True, version
    except (FileNotFoundError, ImportError, OSError, ValueError, KeyError):
        return False, "unavailable"


def _hourly_aggregates(conn, schema: str, object_code: int, start_at, as_of, cfg: dict):
    import pandas as pd

    years = ",".join(str(int(year)) for year in cfg.get("exclude_years", [])) or "-1"
    faults = ",".join(str(int(state)) for state in cfg.get("fault_states", [])) or "-1"
    excluded = " OR ".join(
        f'("код_типа_датчика" = {int(sensor_type)} AND "код_состояния" = {int(state)})'
        for sensor_type, state in cfg.get("exclude_alarm_states", [])
    ) or "FALSE"

    sql = text(f'''
        WITH ev AS (
            SELECT
                d."ид_канала_данных"::bigint AS ch,
                floor(extract(epoch FROM date_trunc('hour', d."дата_время_события")) / 3600)::bigint AS h,
                d."дата_время_события" AS ts,
                d."код_типа_датчика", d."код_состояния", d."код_типа_значения",
                d."тревожное_событие", d."тревожное_по_справочнику",
                d."состояние_техническое", d."служебное_значение",
                d."мало_истории_значение", d."мало_истории_dt",
                d."значение"::double precision AS v,
                d."значение_z"::double precision AS vz,
                d."лог_dt"::double precision AS ldt,
                d."лог_dt_z"::double precision AS ldtz,
                CASE WHEN (
                    d."тревожное_событие" = 1
                    AND d."состояние_техническое" = 0
                    AND NOT ({excluded})
                ) OR (
                    d."код_типа_датчика" = {int(cfg['gas_type'])}
                    AND (d."значение" >= {float(cfg['gas_threshold'])}
                         OR d."код_состояния" = {int(cfg['gas_state'])})
                ) THEN 1 ELSE 0 END AS alarm,
                CASE WHEN d."код_состояния" IN ({faults})
                    OR d."код_типа_значения" = 1
                    OR d."служебное_значение" = 1
                THEN 1 ELSE 0 END AS tech
            FROM {schema}.dataset_ml d
            JOIN {schema}.map_channel m USING ("ид_канала_данных")
            WHERE m."код_объекта" = :object_code
              AND d."дата_время_события" > :start_at
              AND d."дата_время_события" <= :as_of
              AND extract(year FROM d."дата_время_события") NOT IN ({years})
        ), alarm_sequence AS (
            SELECT ch, h, ts,
                   lag(ts) OVER (PARTITION BY ch ORDER BY ts) AS previous_ts
            FROM ev
            WHERE alarm = 1
        ), starts AS (
            SELECT ch, h, count(*) AS n_start
            FROM alarm_sequence
            WHERE previous_ts IS NULL
               OR extract(epoch FROM ts - previous_ts) > {int(cfg['episode_gap_h']) * 3600}
            GROUP BY ch, h
        ), hourly AS (
            SELECT ch, h,
                count(*) AS n_ev,
                sum(alarm) AS n_alarm,
                sum(tech) AS n_tech,
                sum("тревожное_событие") AS n_alarm_raw,
                sum("тревожное_по_справочнику") AS n_alarm_ref,
                sum("служебное_значение") AS n_serv,
                sum("мало_истории_значение" + "мало_истории_dt") AS n_lowhist,
                count(DISTINCT "код_состояния") AS n_states,
                avg(v) AS v_mean, max(v) AS v_max, min(v) AS v_min,
                (array_agg(v ORDER BY ts DESC) FILTER (WHERE v IS NOT NULL))[1] AS v_last,
                max(abs(vz)) AS vz_absmax, avg(vz) AS vz_mean,
                stddev_pop(v) AS v_std, count(v) AS n_v,
                sum(CASE WHEN abs(vz) >= 3 THEN 1 ELSE 0 END) AS n_vz3,
                sum(CASE WHEN "код_типа_датчика" = {int(cfg['gas_type'])}
                          AND v >= {float(cfg['gas_threshold']) * 0.5}
                          AND v < {float(cfg['gas_threshold'])} THEN 1 ELSE 0 END) AS n_v_hi,
                sum(CASE WHEN "код_типа_датчика" = {int(cfg['gas_type'])}
                          AND v > 0.05 THEN 1 ELSE 0 END) AS n_v_pos,
                min(ldtz) AS ldtz_min, max(ldtz) AS ldtz_max, avg(ldt) AS ldt_mean,
                (array_agg("код_состояния" ORDER BY ts DESC))[1] AS state_last,
                (array_agg(alarm ORDER BY ts DESC))[1] AS alarm_last
            FROM ev
            GROUP BY ch, h
        )
        SELECT hourly.*, coalesce(starts.n_start, 0) AS n_start
        FROM hourly
        LEFT JOIN starts USING (ch, h)
        ORDER BY ch, h
    ''')
    aggregate = pd.read_sql(sql, conn, params={
        "object_code": object_code,
        "start_at": start_at,
        "as_of": as_of,
    })
    for column in aggregate.columns:
        if column in {"ch", "h"}:
            aggregate[column] = aggregate[column].astype("int64")
        elif pd.api.types.is_numeric_dtype(aggregate[column]):
            aggregate[column] = aggregate[column].astype("float32")
    return aggregate


def predict_prepared_dataset(
    dataset_id: UUID,
    sensor_id: int,
    *,
    engine=None,
    history_days: int | None = None,
) -> PredictionOutput:
    """Build the production feature vector and score one sensor."""
    import pandas as pd

    from ml.djkh_model.model import build_features

    owned_engine = engine is None
    engine = engine or create_ml_engine()
    try:
        try:
            prepared_dataset(engine, dataset_id)
        except LookupError as error:
            raise PredictionTargetNotFoundError(str(error)) from error
        schema = schema_name(dataset_id)
        booster, artifacts, version = _load_model()
        cfg = artifacts["cfg"]
        history_days = history_days or int(os.getenv("ML_PREDICTION_HISTORY_DAYS", "90"))
        if history_days < 90:
            raise ValueError("Для прогноза требуется минимум 90 дней истории")

        with engine.connect() as conn:
            target = conn.execute(text(f'''
                SELECT "код_объекта"
                FROM {schema}.map_channel
                WHERE "ид_канала_данных" = :sensor_id
            '''), {"sensor_id": sensor_id}).mappings().first()
            if target is None:
                raise PredictionTargetNotFoundError(
                    "Датчик не найден в выбранном наборе данных"
                )

            as_of = conn.execute(text(f'''
                SELECT max("дата_время_события")
                FROM {schema}.dataset_ml
                WHERE "ид_канала_данных" = :sensor_id
            '''), {"sensor_id": sensor_id}).scalar_one()
            if as_of is None:
                raise ValueError("Для датчика нет истории событий")

            # Include the gap preceding the feature window so the first alarm in
            # the 90-day history is not mistaken for a new episode.
            start_at = (
                as_of
                - pd.Timedelta(days=history_days)
                - pd.Timedelta(hours=int(cfg["episode_gap_h"]))
            )
            aggregate = _hourly_aggregates(
                conn, schema, int(target["код_объекта"]), start_at, as_of, cfg
            )
            static = pd.read_sql(text(f'''
                SELECT
                    "ид_канала_данных"::bigint AS ch,
                    "код_типа_датчика", "код_объекта", "код_комплекса",
                    "объект_охранный", "пикет"
                FROM {schema}.map_channel
                WHERE "код_объекта" = :object_code
            '''), conn, params={"object_code": int(target["код_объекта"])})

        for column in static.columns:
            static[column] = pd.to_numeric(static[column], errors="coerce")

        if aggregate.empty:
            raise ValueError("В доступном периоде нет событий для прогноза")
        if sensor_id not in set(aggregate["ch"]):
            raise ValueError("История датчика не попала в допустимый период модели")

        end_h = int(pd.Timestamp(as_of).floor("h").timestamp() // 3600)
        features, meta, _ = build_features(
            aggregate, static, cfg, end_h=end_h, only_last=True
        )
        target_rows = meta.index[meta["ch"] == sensor_id]
        if target_rows.empty:
            raise ValueError("Не удалось построить признаки датчика")
        row = int(target_rows[-1])
        probability = float(booster.predict(features.loc[[row], artifacts["feat_cols"]])[0])
        return PredictionOutput(
            sensor_id=sensor_id,
            probability=probability,
            horizon_hours=int(cfg["horizon_h"]),
            model_version=version,
        )
    finally:
        if owned_engine:
            engine.dispose()
