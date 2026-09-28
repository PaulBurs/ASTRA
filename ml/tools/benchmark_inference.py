"""Read-only comparison against the old full-object inference path.

python -m ml.tools.benchmark_inference DATASET_UUID --limit 16
No predictions, imports or training results are written to the database.
"""
import argparse
import contextlib
import io
import json
import os
from time import perf_counter
from uuid import UUID

import numpy as np
import pandas as pd
from sqlalchemy import text

from astra_pipeline.registry import schema_name
from ml.djkh_model.model import build_features
from ml.src.data import create_ml_engine
from ml.src.inference import _load_model, _hourly_aggregates, predict_prepared_batch


def reference(engine, dataset_id, sensor):
    schema = schema_name(dataset_id)
    booster, artifacts, _ = _load_model()
    cfg = artifacts['cfg']
    with engine.connect() as conn:
        obj = conn.execute(text(f'SELECT "код_объекта" FROM {schema}.map_channel WHERE "ид_канала_данных"=:id'), {'id': sensor}).scalar_one()
        end = conn.execute(text(f'SELECT max("дата_время_события") FROM {schema}.dataset_ml WHERE "ид_канала_данных"=:id'), {'id': sensor}).scalar_one()
        if end is None:
            return None
        start = end - pd.Timedelta(days=int(os.getenv('ML_PREDICTION_HISTORY_DAYS', '90'))) - pd.Timedelta(hours=cfg['episode_gap_h'])
        agg = _hourly_aggregates(conn, schema, obj, start, end, cfg)
        static = pd.read_sql(text(f'''SELECT "ид_канала_данных"::bigint AS ch,
            "код_типа_датчика", "код_объекта", "код_комплекса", "объект_охранный", "пикет"
            FROM {schema}.map_channel WHERE "код_объекта"=:obj'''), conn, params={'obj': obj})
    for column in static:
        static[column] = pd.to_numeric(static[column], errors='coerce')
    if agg.empty or sensor not in set(agg.ch):
        return None
    features, meta, _ = build_features(agg, static, cfg,
        end_h=int(pd.Timestamp(end).floor('h').timestamp() // 3600), only_last=True)
    row = int(meta.index[meta.ch == sensor][-1])
    return float(booster.predict(features.loc[[row], artifacts['feat_cols']], num_threads=1)[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=UUID)
    parser.add_argument('--limit', type=int, default=16)
    parser.add_argument('--sensor-ids', type=int, nargs='+')
    args = parser.parse_args()
    if not 1 <= args.limit <= 64:
        parser.error('--limit must be 1..64')
    engine = create_ml_engine()
    try:
        ids = args.sensor_ids
        if ids is None:
            with engine.connect() as conn:
                # Spread the sample over objects; use only channels with history.
                ids = list(conn.execute(text(f'''SELECT ch FROM (
                    SELECT "ид_канала_данных" AS ch,
                        row_number() OVER (PARTITION BY "код_объекта" ORDER BY "ид_канала_данных") AS n
                    FROM {schema_name(args.dataset)}.map_channel
                    WHERE "ид_канала_данных" IN (
                        SELECT "ид_канала_данных" FROM {schema_name(args.dataset)}.latest_sensor_events)
                    ) s ORDER BY n,ch LIMIT :limit'''), {'limit': args.limit}).scalars())
        if not ids or len(ids) > 64:
            raise ValueError('Expected 1..64 sensors with history')
        _load_model()
        with contextlib.redirect_stdout(io.StringIO()):
            # Warm both paths before measuring; use the same pooled DB connection
            # even for the reference, so connection setup cannot inflate speedup.
            reference(engine, args.dataset, ids[0])
            predict_prepared_batch(args.dataset, [ids[0]], engine=engine)
            started = perf_counter()
            old = [reference(engine, args.dataset, sensor) for sensor in ids]
            old_seconds = perf_counter() - started
            started = perf_counter()
            items = predict_prepared_batch(args.dataset, ids, engine=engine).predictions
            new_seconds = perf_counter() - started
        new = [item.result.probability if item.status == 'ready' else None for item in items]
        assert [p is None for p in old] == [p is None for p in new]
        np.testing.assert_allclose([p for p in old if p is not None],
                                   [p for p in new if p is not None], rtol=0, atol=1e-12)
        print(json.dumps({'sensors': ids, 'reference_seconds': old_seconds,
            'optimized_seconds': new_seconds, 'speedup': old_seconds / new_seconds,
            'max_probability_error': max((abs(a-b) for a,b in zip(old,new) if a is not None), default=0),
            'note': 'Sequential paths, warm model, no persistence; not a full-dataset timing'}, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
