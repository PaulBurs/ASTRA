"""Inference of the trained alarm model directly from a prepared dataset."""
from __future__ import annotations

import hashlib
import json
import os
import logging
from time import perf_counter
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from uuid import UUID
from threading import BoundedSemaphore, Lock
from functools import wraps

from sqlalchemy import text

from astra_pipeline.registry import schema_name
from ml.src.contracts import PredictionOutput, BatchPredictionItem, BatchPredictionOutput
from ml.src.data import create_ml_engine
from ml.src.datasets import prepared_dataset


MODEL_DIR = Path(os.getenv("ML_MODEL_DIR", Path(__file__).resolve().parents[1] / "out_final"))
ARTIFACTS_PATH = MODEL_DIR / "artifacts.json"
MODEL_PATH = MODEL_DIR / "lgb_model.txt"
_feature_slots = BoundedSemaphore(max(1, min(16, int(os.getenv("ML_FORECAST_WORKERS", "4")))))
_score_lock = Lock()


def bounded_inference(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _feature_slots:
            return function(*args, **kwargs)
    return wrapped


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


def _hourly_aggregates(conn, schema: str, object_code: int, start_at, as_of, cfg: dict,
                       target_channels: list[int] | None = None):
    import pandas as pd

    years = ",".join(str(int(year)) for year in cfg.get("exclude_years", [])) or "-1"
    faults = ",".join(str(int(state)) for state in cfg.get("fault_states", [])) or "-1"
    excluded = " OR ".join(
        f'("код_типа_датчика" = {int(sensor_type)} AND "код_состояния" = {int(state)})'
        for sensor_type, state in cfg.get("exclude_alarm_states", [])
    ) or "FALSE"

    # Detailed statistics (ordered arrays, distinct states, numeric moments) are
    # needed only for the requested channels. Neighbours contribute four counts,
    # collapsed in SQL to one row per object/hour, not every neighbour/hour.
    target_filter = 'WHERE ch = ANY(:target_channels)' if target_channels is not None else ''
    counts_cte, object_union = '', ''
    if target_channels is not None:
        counts_cte = '''counts AS (
            SELECT ch,h,count(*) AS n_ev,sum(alarm) AS n_alarm,sum(tech) AS n_tech
            FROM ev GROUP BY ch,h
        ),'''
        value_columns = ('n_alarm_raw', 'n_alarm_ref', 'n_serv', 'n_lowhist', 'n_states',
                         'v_mean', 'v_max', 'v_min', 'v_last', 'vz_absmax', 'vz_mean',
                         'v_std', 'n_v', 'n_vz3', 'n_v_hi', 'n_v_pos',
                         'ldtz_min', 'ldtz_max', 'ldt_mean', 'state_last', 'alarm_last')
        unused = ','.join('NULL::double precision AS ' + col for col in value_columns)
        object_union = f'''UNION ALL
            SELECT NULL::bigint AS ch,h,sum(n_ev::real::double precision),
                sum(n_alarm::real::double precision),sum(n_tech::real::double precision),
                {unused},sum(coalesce(n_start,0)::real::double precision)
            FROM counts LEFT JOIN starts USING(ch,h) GROUP BY h'''

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
        ), {counts_cte} hourly AS (
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
            {target_filter}
            GROUP BY ch, h
        )
        SELECT hourly.*, coalesce(starts.n_start, 0) AS n_start
        FROM hourly
        LEFT JOIN starts USING (ch, h)
        {object_union}
        ORDER BY ch, h
    ''')
    aggregate = pd.read_sql(sql, conn, params={
        "object_code": object_code,
        "start_at": start_at,
        "as_of": as_of,
        "target_channels": target_channels,
    })
    for column in aggregate.columns:
        if column in {"ch", "h"}:
            aggregate[column] = aggregate[column].astype("Int64" if aggregate[column].isna().any() else "int64")
        elif pd.api.types.is_numeric_dtype(aggregate[column]):
            aggregate[column] = aggregate[column].astype("float32")
    return aggregate


@lru_cache(maxsize=1)
def _prediction_engine():
    # Keep the connection pool alive between requests (datasets are immutable).
    return create_ml_engine()


@bounded_inference
def predict_prepared_batch(
    dataset_id: UUID, sensor_ids: list[int], *, engine=None,
    history_days: int | None = None,
) -> BatchPredictionOutput:
    """Bounded batch; preserve each sensor's exact last-event timestamp/window."""
    import pandas as pd
    from ml.djkh_model.model import build_features

    if not 1 <= len(sensor_ids) <= 64 or len(set(sensor_ids)) != len(sensor_ids):
        raise ValueError("Expected 1..64 distinct sensor IDs")
    engine = engine or _prediction_engine()
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

    results, groups = {}, defaultdict(list)
    # ORDER BY + LIMIT uses the existing (channel, timestamp) index and partition
    # pruning. It avoids aggregating a channel's entire 12-year event history.
    with engine.connect() as conn:
        targets = conn.execute(text(f'''
            SELECT m."ид_канала_данных" AS sensor_id, m."код_объекта" AS object_code,
                   latest.as_of
            FROM {schema}.map_channel m
            LEFT JOIN LATERAL (
                SELECT d."дата_время_события" AS as_of FROM {schema}.dataset_ml d
                WHERE d."ид_канала_данных" = m."ид_канала_данных"
                ORDER BY d."дата_время_события" DESC LIMIT 1
            ) latest ON TRUE
            WHERE m."ид_канала_данных" = ANY(:sensor_ids)
        '''), {"sensor_ids": sensor_ids}).mappings().all()
        found = {int(row["sensor_id"]) for row in targets}
        for sensor in sensor_ids:
            if sensor not in found:
                results[sensor] = BatchPredictionItem(sensor_id=sensor, status="skipped",
                    error="Датчик не найден в выбранном наборе данных")
        for row in targets:
            sensor = int(row["sensor_id"])
            if row["as_of"] is None:
                results[sensor] = BatchPredictionItem(sensor_id=sensor, status="skipped",
                    error="Для датчика нет истории событий")
            else:
                groups[(int(row["object_code"]), row["as_of"])].append(sensor)
        objects = sorted({key[0] for key in groups})
        static_all = pd.read_sql(text(f'''
            SELECT "ид_канала_данных"::bigint AS ch,
                "код_типа_датчика", "код_объекта", "код_комплекса", "объект_охранный", "пикет"
            FROM {schema}.map_channel WHERE "код_объекта" = ANY(:objects)
        '''), conn, params={"objects": objects}) if objects else None
    if static_all is not None:
        for column in static_all.columns:
            static_all[column] = pd.to_numeric(static_all[column], errors="coerce")

    for (object_code, as_of), sensors in groups.items():
        started = perf_counter()
        start_at = as_of - pd.Timedelta(days=history_days) - pd.Timedelta(hours=int(cfg["episode_gap_h"]))
        with engine.connect() as conn:
            combined = _hourly_aggregates(conn, schema, object_code, start_at, as_of, cfg, sensors)
        object_hourly = combined.loc[combined['ch'].isna(), ['h', 'n_ev', 'n_alarm', 'n_tech', 'n_start']].copy()
        object_hourly['код_объекта'] = object_code
        aggregate = combined.loc[combined['ch'].notna()].copy()
        aggregate['ch'] = aggregate['ch'].astype('int64')
        queried = perf_counter()
        present = set(aggregate["ch"]) if not aggregate.empty else set()
        usable = [sensor for sensor in sensors if sensor in present]
        for sensor in sensors:
            if sensor not in present:
                results[sensor] = BatchPredictionItem(sensor_id=sensor, status="skipped",
                    error="История датчика не попала в допустимый период модели")
        if not usable:
            continue
        static = static_all[static_all["код_объекта"] == object_code]
        end_h = int(pd.Timestamp(as_of).floor("h").timestamp() // 3600)
        features, meta, _ = build_features(aggregate, static, cfg, end_h=end_h,
                                          only_last=True, target_channels=usable, object_hourly=object_hourly)
        built = perf_counter()
        with _score_lock:
            probabilities = booster.predict(features[artifacts["feat_cols"]], num_threads=1)
        for sensor, probability in zip(meta["ch"], probabilities):
            sensor = int(sensor)
            results[sensor] = BatchPredictionItem(sensor_id=sensor, status="ready",
                result=PredictionOutput(sensor_id=sensor, probability=float(probability),
                    horizon_hours=int(cfg["horizon_h"]), model_version=version))
        logging.getLogger(__name__).info(
            "forecast dataset=%s object=%s sensors=%d sql=%.3fs features=%.3fs score=%.3fs",
            dataset_id, object_code, len(usable), queried-started, built-queried, perf_counter()-built,
        )
    return BatchPredictionOutput(predictions=[results[sensor] for sensor in sensor_ids])


def predict_prepared_dataset(
    dataset_id: UUID, sensor_id: int, *, engine=None, history_days: int | None = None,
) -> PredictionOutput:
    item = predict_prepared_batch(dataset_id, [sensor_id], engine=engine,
                                  history_days=history_days).predictions[0]
    if item.status != "ready":
        if item.error == "Датчик не найден в выбранном наборе данных":
            raise PredictionTargetNotFoundError(item.error)
        raise ValueError(item.error)
    return item.result
