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
# One batch reads each object once; objects are large, so batches may be large too.
MAX_BATCH_SENSORS = max(1, int(os.getenv("ML_MAX_BATCH_SENSORS", "1024")))


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


def _sql_filters(cfg: dict) -> tuple[str, str, str]:
    years = ",".join(str(int(year)) for year in cfg.get("exclude_years", [])) or "-1"
    faults = ",".join(str(int(state)) for state in cfg.get("fault_states", [])) or "-1"
    excluded = " OR ".join(
        f'("код_типа_датчика" = {int(sensor_type)} AND "код_состояния" = {int(state)})'
        for sensor_type, state in cfg.get("exclude_alarm_states", [])
    ) or "FALSE"
    return years, faults, excluded


def _event_columns(cfg: dict) -> str:
    """Columns of one event row (alias d): the same definitions as model.aggregate_hourly."""
    _, faults, excluded = _sql_filters(cfg)
    return f'''
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
                THEN 1 ELSE 0 END AS tech'''


# Events of one channel often share a timestamp (second resolution). Without a tie-break
# "the last event of the hour" is arbitrary and the same forecast changes between runs.
# Deterministic rule: a simultaneous alarm wins, then the larger state code.
LAST_EVENT_ORDER = 'ts DESC, alarm DESC, "код_состояния" DESC'


def _hourly_columns(cfg: dict) -> str:
    """Hourly statistics of CTE ev per (ch, h)."""
    return f'''
                count(*) AS n_ev,
                sum(alarm) AS n_alarm,
                sum(tech) AS n_tech,
                sum("тревожное_событие") AS n_alarm_raw,
                sum("тревожное_по_справочнику") AS n_alarm_ref,
                sum("служебное_значение") AS n_serv,
                sum("мало_истории_значение" + "мало_истории_dt") AS n_lowhist,
                count(DISTINCT "код_состояния") AS n_states,
                avg(v) AS v_mean, max(v) AS v_max, min(v) AS v_min,
                (array_agg(v ORDER BY ts DESC, v DESC) FILTER (WHERE v IS NOT NULL))[1] AS v_last,
                max(abs(vz)) AS vz_absmax, avg(vz) AS vz_mean,
                stddev_pop(v) AS v_std, count(v) AS n_v,
                sum(CASE WHEN abs(vz) >= 3 THEN 1 ELSE 0 END) AS n_vz3,
                sum(CASE WHEN "код_типа_датчика" = {int(cfg['gas_type'])}
                          AND v >= {float(cfg['gas_threshold']) * 0.5}
                          AND v < {float(cfg['gas_threshold'])} THEN 1 ELSE 0 END) AS n_v_hi,
                sum(CASE WHEN "код_типа_датчика" = {int(cfg['gas_type'])}
                          AND v > 0.05 THEN 1 ELSE 0 END) AS n_v_pos,
                min(ldtz) AS ldtz_min, max(ldtz) AS ldtz_max, avg(ldt) AS ldt_mean,
                (array_agg("код_состояния" ORDER BY {LAST_EVENT_ORDER}))[1] AS state_last,
                (array_agg(alarm ORDER BY {LAST_EVENT_ORDER}))[1] AS alarm_last'''


def _hourly_aggregates(conn, schema: str, object_code: int, start_at, as_of, cfg: dict,
                       target_channels: list[int] | None = None):
    import pandas as pd

    years, _, _ = _sql_filters(cfg)

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
                {_event_columns(cfg)}
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
                {_hourly_columns(cfg)}
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


def _cast_aggregate(aggregate):
    import pandas as pd

    for column in aggregate.columns:
        if column in {"ch", "h"}:
            aggregate[column] = aggregate[column].astype("int64")
        elif column != "код_объекта" and pd.api.types.is_numeric_dtype(aggregate[column]):
            aggregate[column] = aggregate[column].astype("float32")
    return aggregate


def _batch_aggregates(conn, schema: str, targets, cfg: dict):
    """Aggregates for many sensors at once, equal to the per-(object, as_of) path.

    targets: DataFrame ch, object_code, start_at, as_of (each sensor keeps its own window).
    -> (own: hourly statistics of the target channels in their own windows,
        object_hourly: n_ev/n_alarm/n_tech/n_start per object and hour over the union of windows,
        excess: per target, object events in its last hour that came after its as_of).
    Neighbour features look back at most 720 h, far inside the >= 90-day window, so object
    counts differ from the per-sensor query only in the target's last hour; `excess` is that
    difference and is subtracted from the neighbour features afterwards.
    Every channel is read through the (channel, time) index, each object once per batch."""
    import pandas as pd

    years, _, _ = _sql_filters(cfg)
    gap = int(cfg['episode_gap_h']) * 3600
    params = dict(chs=targets['ch'].tolist(), starts=targets['start_at'].tolist(),
                  ends=targets['as_of'].tolist())
    own = pd.read_sql(text(f'''
        WITH t AS (
            SELECT * FROM unnest(CAST(:chs AS bigint[]), CAST(:starts AS timestamp[]),
                                 CAST(:ends AS timestamp[])) AS t(ch, start_at, as_of)
        ), ev AS (
            SELECT {_event_columns(cfg)}
            FROM t CROSS JOIN LATERAL (
                SELECT * FROM {schema}.dataset_ml x
                WHERE x."ид_канала_данных" = t.ch
                  AND x."дата_время_события" > t.start_at
                  AND x."дата_время_события" <= t.as_of
            ) d
            WHERE extract(year FROM d."дата_время_события") NOT IN ({years})
        ), alarm_sequence AS (
            SELECT ch, h, ts, lag(ts) OVER (PARTITION BY ch ORDER BY ts) AS previous_ts
            FROM ev WHERE alarm = 1
        ), starts AS (
            SELECT ch, h, count(*) AS n_start FROM alarm_sequence
            WHERE previous_ts IS NULL OR extract(epoch FROM ts - previous_ts) > {gap}
            GROUP BY ch, h
        ), hourly AS (
            SELECT ch, h, {_hourly_columns(cfg)} FROM ev GROUP BY ch, h
        )
        SELECT hourly.*, coalesce(starts.n_start, 0) AS n_start
        FROM hourly LEFT JOIN starts USING (ch, h)
        ORDER BY ch, h
    '''), conn, params=params)

    objects = targets.groupby('object_code').agg(start_at=('start_at', 'min'), as_of=('as_of', 'max'))
    params.update(objs=objects.index.astype('int64').tolist(), ostarts=objects['start_at'].tolist(),
                  oends=objects['as_of'].tolist(), tobjs=targets['object_code'].astype('int64').tolist())
    counts = pd.read_sql(text(f'''
        WITH o AS (
            SELECT * FROM unnest(CAST(:objs AS bigint[]), CAST(:ostarts AS timestamp[]),
                                 CAST(:oends AS timestamp[])) AS o(obj, start_at, as_of)
        ), channels AS (
            SELECT m."ид_канала_данных" AS ch, o.obj, o.start_at, o.as_of
            FROM {schema}.map_channel m JOIN o ON m."код_объекта" = o.obj
        ), ev AS (
            SELECT c.obj, {_event_columns(cfg)}
            FROM channels c CROSS JOIN LATERAL (
                SELECT * FROM {schema}.dataset_ml x
                WHERE x."ид_канала_данных" = c.ch
                  AND x."дата_время_события" > c.start_at
                  AND x."дата_время_события" <= c.as_of
            ) d
            WHERE extract(year FROM d."дата_время_события") NOT IN ({years})
        ), flagged AS (
            SELECT obj, ch, h, ts, alarm, tech,
                CASE WHEN alarm = 1 AND (previous_alarm IS NULL
                     OR extract(epoch FROM ts - previous_alarm) > {gap}) THEN 1 ELSE 0 END AS is_start
            FROM (SELECT ev.*, max(ts) FILTER (WHERE alarm = 1) OVER (
                      PARTITION BY ch ORDER BY ts ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                  ) AS previous_alarm FROM ev) e
        ), t AS (
            SELECT * FROM unnest(CAST(:chs AS bigint[]), CAST(:tobjs AS bigint[]),
                                 CAST(:ends AS timestamp[])) AS t(ch, obj, as_of)
        )
        SELECT 'object' AS kind, obj, NULL::bigint AS ch, h,
               count(*)::double precision AS n_ev, sum(alarm)::double precision AS n_alarm,
               sum(tech)::double precision AS n_tech, sum(is_start)::double precision AS n_start
        FROM flagged GROUP BY obj, h
        UNION ALL
        SELECT 'excess', t.obj, t.ch, NULL::bigint,
               count(*), sum(f.alarm), sum(f.tech), sum(f.is_start)
        FROM t JOIN flagged f ON f.obj = t.obj
            AND f.ts > t.as_of AND f.ts < date_trunc('hour', t.as_of) + interval '1 hour'
        GROUP BY t.obj, t.ch
    '''), conn, params=params)
    object_hourly = counts.loc[counts['kind'] == 'object', ['obj', 'h', 'n_ev', 'n_alarm', 'n_tech', 'n_start']]
    object_hourly = object_hourly.rename(columns={'obj': 'код_объекта'}).astype({'h': 'int64'})
    excess = counts.loc[counts['kind'] == 'excess', ['ch', 'n_ev', 'n_alarm', 'n_tech', 'n_start']]
    return _cast_aggregate(own), object_hourly, excess.astype({'ch': 'int64'}).set_index('ch')


def _subtract_excess(features, meta, excess):
    """Neighbour windows all end at the target's last hour: remove events that came later in it."""
    if excess.empty:
        return features
    rows = excess.reindex(meta['ch'].to_numpy()).fillna(0)
    for column in features.columns:
        if column.startswith('nbr_n_'):
            counter = column[len('nbr_'):].rsplit('_', 1)[0]      # n_alarm_24h -> n_alarm
            features[column] = (features[column].to_numpy('float32')
                                - rows[counter].to_numpy('float32')).astype('float32')
    return features


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

    if not 1 <= len(sensor_ids) <= MAX_BATCH_SENSORS or len(set(sensor_ids)) != len(sensor_ids):
        raise ValueError(f"Expected 1..{MAX_BATCH_SENSORS} distinct sensor IDs")
    engine = engine or _prediction_engine()
    try:
        job = prepared_dataset(engine, dataset_id)
    except LookupError as error:
        raise PredictionTargetNotFoundError(str(error)) from error
    schema = schema_name(dataset_id)
    booster, artifacts, version = _load_model()
    cfg = artifacts["cfg"]
    history_days = history_days or int(os.getenv("ML_PREDICTION_HISTORY_DAYS", "90"))
    if history_days < 90:
        raise ValueError("Для прогноза требуется минимум 90 дней истории")
    # Features may be prepared only for the last N days of every channel (DATASET_FEATURE_DAYS).
    feature_days = (job.get("counts") or {}).get("feature_days")
    if feature_days is not None and history_days * 24 + int(cfg["episode_gap_h"]) > feature_days * 24:
        raise ValueError(f"Признаки набора подготовлены за {feature_days} дн., а прогноз требует "
                         f"{history_days} дн. истории: увеличьте DATASET_FEATURE_DAYS и подготовьте набор заново")

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

    if not groups:
        return BatchPredictionOutput(predictions=[results[sensor] for sensor in sensor_ids])
    # One pass for the whole batch: own windows per sensor, each object read once.
    started = perf_counter()
    gap = pd.Timedelta(hours=int(cfg["episode_gap_h"]))
    targets = pd.DataFrame(
        [(sensor, object_code, as_of) for (object_code, as_of), sensors in groups.items() for sensor in sensors],
        columns=["ch", "object_code", "as_of"])
    targets["as_of"] = pd.to_datetime(targets["as_of"])
    targets["start_at"] = targets["as_of"] - pd.Timedelta(days=history_days) - gap
    with engine.connect() as conn:
        aggregate, object_hourly, excess = _batch_aggregates(conn, schema, targets, cfg)
    queried = perf_counter()
    present = set(aggregate["ch"]) if not aggregate.empty else set()
    for sensor in targets["ch"]:
        if sensor not in present:
            results[int(sensor)] = BatchPredictionItem(sensor_id=int(sensor), status="skipped",
                error="История датчика не попала в допустимый период модели")
    usable = [int(sensor) for sensor in targets["ch"] if sensor in present]
    if usable:
        static = static_all[static_all["код_объекта"].isin(targets["object_code"])]
        hours = (targets["as_of"].dt.floor("h") - pd.Timestamp(0)) // pd.Timedelta(hours=1)
        end_h = pd.Series(hours.to_numpy("int64"), index=targets["ch"].to_numpy())
        features, meta, _ = build_features(aggregate, static, cfg, end_h=end_h, only_last=True,
                                           target_channels=usable, object_hourly=object_hourly)
        features = _subtract_excess(features, meta, excess)
        built = perf_counter()
        with _score_lock:
            probabilities = booster.predict(features[artifacts["feat_cols"]], num_threads=1)
        for sensor, probability in zip(meta["ch"], probabilities):
            sensor = int(sensor)
            results[sensor] = BatchPredictionItem(sensor_id=sensor, status="ready",
                result=PredictionOutput(sensor_id=sensor, probability=float(probability),
                    horizon_hours=int(cfg["horizon_h"]), model_version=version))
        logging.getLogger(__name__).info(
            "forecast dataset=%s objects=%d sensors=%d sql=%.3fs features=%.3fs score=%.3fs",
            dataset_id, targets["object_code"].nunique(), len(usable), queried-started, built-queried,
            perf_counter()-built,
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
