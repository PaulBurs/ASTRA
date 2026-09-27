"""
checks.py - проверка корректности нормировки датасета и скользящих признаков модели.

    python djkh_model/checks.py --data sample_30.parquet

1. НОРМИРОВКА ДАТАСЕТА: значение_z и лог_dt_z пересчитываются независимо (SQL-окна duckdb
   по сырым значениям) и сравниваются с колонками файла. Окно [t - L, t), текущая секунда
   не входит, var_pop, eps по типу, n < 5 -> NULL. Первые 91 день каждого датчика пропускаются:
   их лог_dt и окна опираются на события до начала файла (2019-2021), которых в срезе нет.
2. ФУНКЦИИ СЕТКИ (roll_sum, roll_sum_lag, roll_max, hours_since, future_sum, hours_to_next)
   сравниваются с наивными циклами на случайных данных с несколькими каналами.
3. СКОЛЬЗЯЩИЕ СРЕДНИЕ ЗНАЧЕНИЙ (v_mean_6h/24h/168h) сравниваются с прямым средним по сырым
   событиям.
4. УТЕЧКА БУДУЩЕГО: признаки строятся на полных данных и на данных, обрезанных в момент T.
   Для часов <= T все признаки обязаны совпасть - иначе признак видит будущее.
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

OK, FAIL = 'OK  ', 'FAIL'
failures = []


def report(name, ok, detail=''):
    print(f'[{OK if ok else FAIL}] {name}' + (f'  - {detail}' if detail else ''))
    if not ok:
        failures.append(name)


# ------------------------------------------------------------------------------------------------
def check_normalization(src: str, dicts: str):
    print('\n=== 1. Нормировка значение_z / лог_dt_z (пересчёт с нуля) ===')
    win = pd.read_csv(os.path.join(dicts, 'window_params.csv'))
    eps = pd.read_csv(os.path.join(dicts, 'norm_params.csv'))[['код_типа_датчика', 'eps']]
    con = duckdb.connect()
    con.register('win', win)
    con.register('eps', eps)
    rd = (f"read_parquet('{src}')" if src.endswith('.parquet')
          else f"read_csv('{src}', header = true, types = {M.COL_TYPES})")
    # RANGE по секундам: окно [t - L, t - 1 c] = [t - L, t) для целых секунд
    res = con.sql(f"""
    WITH e AS (
        SELECT d.*, w.окно_дней AS L, coalesce(p.eps, 0) AS eps_v,
               epoch(дата_время_события)::BIGINT AS sec,
               min(epoch(дата_время_события)::BIGINT) OVER (PARTITION BY ид_канала_данных) AS first_sec
        FROM {rd} d JOIN win w USING (код_типа_датчика) LEFT JOIN eps p USING (код_типа_датчика)
    ), dt AS (
        -- лог_dt: ln(1 + секунд до последнего события строго раньше этой секунды)
        SELECT *, max(sec) OVER (PARTITION BY ид_канала_данных ORDER BY sec
                                 RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_sec
        FROM e
    ), f AS (
        SELECT *, round(ln(1 + (sec - prev_sec)), 6) AS ldt_re FROM dt
    ), w AS (
        SELECT *,
          count(значение) OVER wv AS n_v, avg(значение) OVER wv AS mu_v, var_pop(значение) OVER wv AS var_v,
          count(ldt_re)   OVER wv AS n_d, avg(ldt_re)   OVER wv AS mu_d, var_pop(ldt_re)   OVER wv AS var_d
        FROM f
        WINDOW wv AS (PARTITION BY ид_канала_данных ORDER BY sec
                      RANGE BETWEEN L * 86400 PRECEDING AND 1 PRECEDING)
    ), z AS (
        SELECT *,
          CASE WHEN значение IS NULL THEN NULL WHEN n_v < 5 THEN NULL
               ELSE (значение - mu_v) / sqrt(var_v + eps_v) END AS vz_re,
          CASE WHEN ldt_re IS NULL THEN NULL WHEN n_d < 5 THEN NULL
               ELSE (ldt_re - mu_d) / sqrt(var_d + 0.01) END AS ldtz_re
        FROM w
    )
    SELECT код_типа_датчика AS тип, count(*) AS событий,
      count(значение_z) AS z_в_файле, count(vz_re) AS z_пересчёт,
      sum(CASE WHEN (значение_z IS NULL) <> (vz_re IS NULL) THEN 1 ELSE 0 END) AS z_разн_null,
      max(abs(значение_z - vz_re)) AS z_макс_разн,
      sum(CASE WHEN (лог_dt IS NULL) <> (ldt_re IS NULL) THEN 1 ELSE 0 END) AS ldt_разн_null,
      max(abs(лог_dt - ldt_re)) AS ldt_макс_разн,
      sum(CASE WHEN (лог_dt_z IS NULL) <> (ldtz_re IS NULL) THEN 1 ELSE 0 END) AS ldtz_разн_null,
      max(abs(лог_dt_z - ldtz_re)) AS ldtz_макс_разн,
      sum(CASE WHEN мало_истории_значение <> (значение IS NOT NULL AND n_v < 5)::INT THEN 1 ELSE 0 END)
          AS флаг_v_разн
    FROM z
    WHERE sec >= first_sec + 91 * 86400      -- окно и лог_dt не опираются на историю до файла
    GROUP BY 1 ORDER BY 1
    """).df()
    con.close()
    print(res.to_string(index=False, float_format=lambda x: f'{x:.2e}'))
    tol = 1e-3
    report('значение_z совпадает с пересчётом',
           res['z_разн_null'].sum() == 0 and (res['z_макс_разн'].fillna(0) < tol).all(),
           f"расхождений NULL {int(res['z_разн_null'].sum())}, макс |Δz| {res['z_макс_разн'].max():.2e}")
    report('лог_dt совпадает с пересчётом',
           res['ldt_разн_null'].sum() == 0 and (res['ldt_макс_разн'].fillna(0) < 1e-5).all(),
           f"расхождений NULL {int(res['ldt_разн_null'].sum())}, макс |Δ| {res['ldt_макс_разн'].max():.2e}")
    report('лог_dt_z совпадает с пересчётом',
           res['ldtz_разн_null'].sum() == 0 and (res['ldtz_макс_разн'].fillna(0) < tol).all(),
           f"расхождений NULL {int(res['ldtz_разн_null'].sum())}, макс |Δ| {res['ldtz_макс_разн'].max():.2e}")
    report('флаг мало_истории_значение совпадает', res['флаг_v_разн'].sum() == 0,
           f"расхождений {int(res['флаг_v_разн'].sum())}")


# ------------------------------------------------------------------------------------------------
def naive_groups(G):
    ends = np.append(G.gstart_pos[1:], G.n)
    return list(zip(G.gstart_pos, ends))


def check_grid():
    print('\n=== 2. Функции сетки против наивных циклов ===')
    rng = np.random.default_rng(0)
    rows = []
    for ch in range(6):
        hs = np.sort(rng.choice(np.arange(1000, 1600), size=rng.integers(5, 80), replace=False))
        rows.append(pd.DataFrame({'ch': ch, 'h': hs}))
    agg = pd.concat(rows, ignore_index=True)
    cfg = dict(M.CFG, extend_after_last_h=50)
    G = M.Grid(agg, cfg)
    x = G.dense(rng.poisson(1.0, len(agg)).astype('float32'))
    x[rng.random(G.n) < 0.5] = 0
    flag = (x > 1).astype('float32')
    groups = naive_groups(G)

    def per_pos(fn):
        out = np.empty(G.n)
        for a, b in groups:
            for i in range(a, b):
                out[i] = fn(a, b, i)
        return out

    for w in (1, 6, 24, 168):
        ref = per_pos(lambda a, b, i: x[max(a, i - w + 1):i + 1].sum())
        report(f'roll_sum w={w}', np.allclose(G.roll_sum(x, w), ref))
        ref = per_pos(lambda a, b, i: x[max(a, i - w + 1):i + 1].max())
        report(f'roll_max w={w}', np.allclose(G.roll_max(x, w), ref))
    for w, lag in ((24, 0), (24, 144), (6, 18), (168, 0)):
        ref = per_pos(lambda a, b, i: x[max(a, i - lag - w + 1):i - lag + 1].sum() if i - lag >= a else 0)
        report(f'roll_sum_lag w={w} lag={lag}', np.allclose(G.roll_sum_lag(x, w, lag), ref))

    def since(a, b, i):
        prev = [j for j in range(a, i + 1) if flag[j] > 0]
        return i - prev[-1] if prev else 24 * 365
    report('hours_since', np.allclose(G.hours_since(flag), per_pos(since)))

    for H in (24, 168):
        s, known = G.future_sum(x, H)
        ref = per_pos(lambda a, b, i: x[i + 1:min(b, i + H + 1)].sum())
        refk = per_pos(lambda a, b, i: i + H <= b - 1)
        report(f'future_sum H={H} (цель: строго после t)', np.allclose(s, ref) and (known == refk.astype(bool)).all())

    def to_next(a, b, i):
        nxt = [j for j in range(i + 1, b) if flag[j] > 0]
        return nxt[0] - i if nxt else np.inf
    report('hours_to_next', np.array_equal(G.hours_to_next(flag), per_pos(to_next)))


# ------------------------------------------------------------------------------------------------
def load_subset(src: str, frac: float):
    cfg = dict(M.CFG, channel_frac=frac)
    agg, _ = M.aggregate_hourly([src], cfg)
    return cfg, agg


def check_value_means(src: str, cfg: dict, agg: pd.DataFrame, X: pd.DataFrame, meta: pd.DataFrame):
    print('\n=== 3. Скользящие средние значений против прямого расчёта ===')
    chs = agg.loc[agg['n_v'] > 0, 'ch'].unique()[:3]
    rd = (f"read_parquet('{src}')" if src.endswith('.parquet')
          else f"read_csv('{src}', header = true, types = {M.COL_TYPES})")
    ev = duckdb.sql(f"""SELECT ид_канала_данных AS ch,
            date_diff('hour', TIMESTAMP '1970-01-01', date_trunc('hour', дата_время_события)) AS h, значение AS v
        FROM {rd} WHERE значение IS NOT NULL AND ид_канала_данных IN ({','.join(map(str, chs))})""").df()
    rng = np.random.default_rng(1)
    for w in (6, 24, 168):
        bad = 0
        idx = rng.choice(np.flatnonzero(meta['ch'].isin(chs).to_numpy()), 300, replace=False)
        for i in idx:
            ch, h = meta['ch'].iat[i], meta['h'].iat[i]
            vv = ev.loc[(ev['ch'] == ch) & (ev['h'] > h - w) & (ev['h'] <= h), 'v']
            ref = vv.mean() if len(vv) else np.nan
            got = X[f'v_mean_{w}h'].iat[i]
            if not ((np.isnan(ref) and np.isnan(got)) or abs(ref - got) < 1e-3 * max(1, abs(ref))):
                bad += 1
        report(f'v_mean_{w}h (300 случайных часов)', bad == 0, f'расхождений {bad}')


def check_leakage(cfg: dict, agg: pd.DataFrame, static: pd.DataFrame):
    print('\n=== 4. Утечка будущего: признаки на данных до T == признаки на полных данных ===')
    T = int(agg['h'].quantile(0.6))
    X1, m1, _ = M.build_features(agg, static, cfg, keep_all=True)
    X2, m2, _ = M.build_features(agg[agg['h'] <= T].reset_index(drop=True), static, cfg,
                                 end_h=T, keep_all=True)
    k1 = pd.MultiIndex.from_arrays([m1['ch'], m1['h']])
    k2 = pd.MultiIndex.from_arrays([m2['ch'], m2['h']])
    pos = k1.get_indexer(k2)
    ok_rows = pos >= 0
    a = X1.iloc[pos[ok_rows]].reset_index(drop=True)
    b = X2[ok_rows].reset_index(drop=True)
    leaks = []
    for c in X2.columns:
        u, v = a[c].to_numpy('float64'), b[c].to_numpy('float64')
        diff = ~((np.isnan(u) & np.isnan(v)) | np.isclose(u, v, rtol=1e-4, atol=1e-4))
        if diff.any():
            leaks.append((c, int(diff.sum())))
    report(f'{X2.shape[1]} признаков, {ok_rows.sum():,} строк до T', not leaks,
           'зависят от будущего: ' + ', '.join(f'{c} ({n})' for c, n in leaks) if leaks else 'совпали все')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default='sample_30.parquet')
    ap.add_argument('--dicts', default=os.path.join(M.HERE, 'dicts'))
    ap.add_argument('--channel-frac', type=float, default=0.1, help='доля датчиков для проверок 3-4')
    args = ap.parse_args()

    check_normalization(args.data, args.dicts)
    check_grid()
    cfg, agg = load_subset(args.data, args.channel_frac)
    static = M.load_static(args.dicts)
    X, meta, _ = M.build_features(agg, static, cfg, keep_all=True)
    check_value_means(args.data, cfg, agg, X, meta)
    del X, meta
    check_leakage(cfg, agg, static)
    print('\nИТОГ:', 'всё сошлось' if not failures else f'ошибки: {failures}')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
