"""SQL -> real feature vectors -> trained model -> spawned CPU worker."""
import os
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from unittest.mock import patch
from time import perf_counter
import numpy as np
import pandas as pd
from sqlalchemy import text
from astra_pipeline.registry import schema_name
from ml.djkh_model.model import build_features
from ml.src.inference import _hourly_aggregates, _load_model

from ml.src.data import create_ml_engine
from ml.src.inference import predict_prepared_batch, predict_prepared_dataset
from ml.src.prediction_workers import run_prediction, shutdown_workers
from ml.tests.sql_fixture import inference_dataset
from ml.tools.benchmark_inference import reference


@unittest.skipUnless(os.getenv('ML_DATABASE_URL'), 'requires PostgreSQL')
class SQLInferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_ml_engine()
        cls.fixture = inference_dataset(cls.engine)
        cls.dataset = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls):
        shutdown_workers()
        cls.fixture.__exit__(None, None, None)
        cls.engine.dispose()

    def test_sql_batch_matches_old_path_with_exact_timestamp_boundaries(self):
        ids = list(range(1, 13)) + [9000, 9001]
        # 12 sensors have six (object, timestamp) groups; no rounding of time.
        reference(self.engine, self.dataset, 1)
        started = perf_counter()
        old = [reference(self.engine, self.dataset, sensor) for sensor in ids]
        old_seconds = perf_counter() - started
        from ml.src.inference import _hourly_aggregates
        with patch('ml.src.inference._hourly_aggregates', wraps=_hourly_aggregates) as aggregate:
            started = perf_counter()
            batch = predict_prepared_batch(self.dataset, ids, engine=self.engine)
            new_seconds = perf_counter() - started
        # One extra group is the excluded year 2021.
        self.assertEqual(aggregate.call_count, 7)
        new = [item.result.probability if item.status == 'ready' else None for item in batch.predictions]
        self.assertEqual([p is None for p in old], [p is None for p in new])
        np.testing.assert_allclose(old[:12], new[:12], rtol=0, atol=1e-12)
        print(f'\nSQL benchmark: old={old_seconds:.3f}s batch={new_seconds:.3f}s speedup={old_seconds/new_seconds:.2f}x max_error={max(abs(a-b) for a,b in zip(old[:12],new[:12]))}', flush=True)

    def test_worker_single_and_batch_share_results_and_skip_missing_history(self):
        single = run_prediction(self.dataset, [1], single=True)
        batch = run_prediction(self.dataset, [1, 9000, 9001, 9999])
        self.assertEqual(batch.predictions[0].result, single)
        self.assertEqual([p.status for p in batch.predictions], ['ready', 'skipped', 'skipped', 'skipped'])
        with self.assertRaises(ValueError):
            predict_prepared_batch(self.dataset, [1, 1], engine=self.engine)
        with self.assertRaises(LookupError):
            predict_prepared_dataset(self.dataset, 9999, engine=self.engine)

    def test_compact_sql_preserves_all_feature_columns(self):
        schema = schema_name(self.dataset)
        _, artifacts, _ = _load_model()
        cfg = artifacts['cfg']
        with self.engine.connect() as conn:
            end = conn.execute(text(f'SELECT max("дата_время_события") FROM {schema}.dataset_ml WHERE "ид_канала_данных"=1')).scalar_one()
            start = end - pd.Timedelta(days=90, hours=cfg['episode_gap_h'])
            static = pd.read_sql(text(f'SELECT "ид_канала_данных" AS ch, "код_типа_датчика", "код_объекта", "код_комплекса", "объект_охранный", "пикет" FROM {schema}.map_channel WHERE "код_объекта"=43'), conn)
            full = _hourly_aggregates(conn, schema, 43, start, end, cfg)
            compact = _hourly_aggregates(conn, schema, 43, start, end, cfg, [1, 3])
        hourly = compact.loc[compact.ch.isna(), ['h', 'n_ev', 'n_alarm', 'n_tech', 'n_start']].copy()
        hourly['код_объекта'] = 43
        own = compact.loc[compact.ch.notna()].copy()
        own['ch'] = own.ch.astype('int64')
        end_h = int(pd.Timestamp(end).floor('h').timestamp() // 3600)
        old, meta, _ = build_features(full, static, cfg, end_h=end_h, only_last=True)
        new, _, _ = build_features(own, static, cfg, end_h=end_h, only_last=True, object_hourly=hourly)
        expected = old.loc[meta.ch.isin([1, 3])].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, new, check_exact=False, rtol=1e-6, atol=1e-5)

    @unittest.skipUnless(os.getenv('ML_INFERENCE_TEST_API'), 'requires running ML HTTP service')
    def test_parallel_http_batches_use_real_model(self):
        base = os.environ['ML_INFERENCE_TEST_API'] + f'/datasets/{self.dataset}'
        def request(sensor):
            req = Request(base + '/predict-batch',
                          data=json.dumps({'sensor_ids': [sensor, 9001]}).encode(),
                          headers={'Content-Type': 'application/json'})
            with urlopen(req, timeout=60) as response:
                return json.load(response)['predictions']
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(request, [1, 2, 3, 4]))
        for sensor, items in zip([1, 2, 3, 4], results):
            self.assertEqual([p['status'] for p in items], ['ready', 'skipped'])
            expected = predict_prepared_dataset(self.dataset, sensor, engine=self.engine)
            self.assertEqual(items[0]['result'], expected.model_dump())


if __name__ == '__main__':
    unittest.main()
