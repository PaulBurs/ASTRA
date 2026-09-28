"""Feature equivalence uses the actual trained Booster, including neighbour features.

Run inside the ML image: python -m unittest discover -s ml/tests -v
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.djkh_model.model import build_features, Grid
from ml.src.inference import _load_model


def fixture(channels=5, hours=2400):
    rng = np.random.default_rng(504)
    frames = []
    for ch in range(channels):
        h = np.unique(np.r_[0, rng.integers(1, hours - 1, 180), hours - 1 - ch * 30])
        n = len(h)
        rows = {'ch': np.full(n, ch + 1), 'h': h + 470000}
        for col in ('n_ev', 'n_alarm', 'n_tech', 'n_alarm_raw', 'n_alarm_ref',
                    'n_serv', 'n_lowhist', 'n_start', 'n_v', 'n_vz3', 'n_v_hi', 'n_v_pos'):
            rows[col] = rng.integers(0, 4, n).astype('float32')
        rows['n_ev'] += 1
        for col in ('v_mean', 'v_max', 'v_min', 'v_last', 'vz_absmax', 'vz_mean',
                    'v_std', 'ldtz_min', 'ldtz_max', 'ldt_mean', 'n_states', 'state_last', 'alarm_last'):
            rows[col] = rng.normal(size=n).astype('float32')
            rows[col][::7] = np.nan
        # A valid channel with no alarm episodes exercises empty recurrence groups.
        if ch == 2:
            rows['n_start'][:] = 0
            rows['n_alarm'][:] = 0
        frames.append(pd.DataFrame(rows))
    agg = pd.concat(frames, ignore_index=True)
    static = pd.DataFrame({'ch': np.arange(1, channels + 1),
                           'код_типа_датчика': np.resize([2, 3, 13], channels),
                           'код_объекта': 42, 'код_комплекса': 1,
                           'объект_охранный': 0, 'пикет': 5})
    return agg, static


class TargetFeaturesTest(unittest.TestCase):
    def test_matches_full_object_features_and_trained_predictions(self):
        booster, artifacts, _ = _load_model()
        agg, static = fixture()
        cfg = artifacts['cfg']
        for end_h in (None, int(agg.h.max()) + 240):
            original, original_meta, _ = build_features(agg, static, cfg, end_h=end_h, only_last=True)
            for targets in ([3], [1, 4], [5, 2, 3]):
                with self.subTest(end=end_h, targets=targets):
                    optimized, meta, _ = build_features(agg, static, cfg, end_h=end_h,
                                                       only_last=True, target_channels=targets)
                    expected = original.loc[original_meta.ch.isin(targets)].reset_index(drop=True)
                    pd.testing.assert_frame_equal(expected, optimized, check_exact=False, atol=1e-5, rtol=1e-6)
                    np.testing.assert_allclose(
                        booster.predict(expected[artifacts['feat_cols']], num_threads=1),
                        booster.predict(optimized[artifacts['feat_cols']], num_threads=1),
                        rtol=0, atol=1e-12,
                    )
                    self.assertEqual(meta.ch.tolist(), sorted(targets))

    def test_dense_grid_contains_only_targets_but_neighbours_are_preserved(self):
        _, artifacts, _ = _load_model()
        agg, static = fixture()
        seen = []
        def record_grid(data, *args):
            seen.append(set(data.ch))
            return Grid(data, *args)
        with patch('ml.djkh_model.model.Grid', side_effect=record_grid):
            features, _, _ = build_features(agg, static, artifacts['cfg'], only_last=True, target_channels=[1])
        self.assertEqual(seen, [{1}])
        self.assertTrue(features.filter(like='nbr_n_ev').to_numpy().sum() > 0)


if __name__ == '__main__':
    unittest.main()
