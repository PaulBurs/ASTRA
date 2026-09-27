"""Проверки lct_features. Запуск из папки data_pipeline:  python -m unittest -v

test_parity: 41 319 сырых событий 55 каналов (18 типов датчиков, 20 дней мая 2024, с дублями
и каналами не из справочника) прогоняются через OnlineFeaturizer и сравниваются с тем, что
для тех же событий лежит в ml.dataset_ml (выгрузка из БД, собранной скриптами sql/).
"""
import csv
import gzip
import math
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from lct_features import ALL_COLUMNS, OnlineFeaturizer, parse_value

FIX = Path(__file__).with_name('fixtures')


def _num(x):
    if x is None or x == '':
        return None
    if isinstance(x, datetime):
        return x
    return float(x)


class TestParse(unittest.TestCase):
    def test_types(self):
        self.assertEqual(parse_value('01.01.1970 03:00:01').value_type, 'binary')
        self.assertEqual(parse_value('01.01.1970 03:00:00').number, 0.0)
        p = parse_value('05.03.2026 09:11:35')
        self.assertEqual((p.value_type, p.dt), ('datetime', datetime(2026, 3, 5, 9, 11, 35)))
        self.assertEqual(parse_value('0.07').number, 0.07)
        self.assertEqual(parse_value('-3276').value_type, 'numeric')
        self.assertEqual(parse_value('Обнаружено движение').text, 'Обнаружено движение')


class TestParity(unittest.TestCase):
    def test_parity_with_dataset(self):
        fz = OnlineFeaturizer(on_late='raise')
        got = defaultdict(list)
        with gzip.open(FIX / 'parity_raw.csv.gz', 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                row = fz.process_raw(r['ид_канала_данных'], r['дата_время_события'],
                                     r['тревожное_raw'], r['значение_датчика_raw'])
                if row is not None:
                    got[(row['ид_канала_данных'], row['дата_время_события'])].append(row)
        exp = defaultdict(list)
        with gzip.open(FIX / 'parity_expected.csv.gz', 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                exp[(int(r['ид_канала_данных']), datetime.fromisoformat(r['дата_время_события']))].append(r)

        self.assertEqual(sum(map(len, exp.values())), 41074)
        self.assertEqual(sum(map(len, got.values())), 41074)
        self.assertGreater(fz.stats['orphan'], 0)
        self.assertGreater(fz.stats['duplicate'], 0)
        self.assertEqual(set(got), set(exp))

        cols = [c for c in ALL_COLUMNS if c not in ('дата_время_события', 'ид_канала_данных')]
        def canon(rows):
            out = []
            for r in rows:
                t = []
                for c in cols:
                    v = _num(r[c])
                    t.append(-1e9 if v is None else round(v, 3))
                out.append(tuple(t))
            return sorted(out)
        bad = 0
        for k in exp:
            a, b = canon(got[k]), canon(exp[k])
            for ra, rb in zip(a, b):
                for c, x, y in zip(cols, ra, rb):
                    if not math.isclose(x, y, rel_tol=2e-3, abs_tol=2e-3):
                        bad += 1
                        if bad <= 5:
                            print('расхождение', k, c, x, y)
        self.assertEqual(bad, 0)


if __name__ == '__main__':
    unittest.main()
