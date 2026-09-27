"""
model.py - модель проекта 08.ДЖКХ: прогноз тревог датчиков + детектор аномалий.

ИДЕЯ
  Разметки «настоящий инцидент / ложное срабатывание» нет, поэтому модель решает задачу,
  которую можно честно проверить по данным:
    1) ПРОГНОЗ (LightGBM): для каждого датчика на конец каждого часа - вероятность, что в
       следующие HORIZON часов начнётся НОВЫЙ эпизод тревоги (а не продолжится текущий).
    2) АНОМАЛИИ (IsolationForest + правила): необычное поведение датчика -
       «дребезг» (слишком много событий), долгое молчание, всплески значений и ритма.

КОНВЕЙЕР
  события (csv.gz) --duckdb--> агрегаты «датчик × час» --> плотная сетка часов
  --> скользящие признаки (только прошлое) + признаки объекта (соседи)
  --> цель: начало эпизода тревоги в (t, t+HORIZON] --> LightGBM
  Валидация только по времени: train < VALID_START <= valid < TEST_START <= test.

ЗАПУСК
  python model.py train   --data "data/dataset_ml_*.csv.gz" --out out
  python model.py predict --data "data/dataset_ml_2026.csv.gz" --out out
  Параметры - python model.py train -h.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------------------------
# КОНФИГ
# ------------------------------------------------------------------------------------------------
CFG = dict(
    horizon_h=168,             # горизонт прогноза, часов (7 суток; при 24 ч ловилось 31 % эпизодов, при 168 ч - 71 %)
    episode_gap_h=6,           # тревога через > 6 ч после прошлой тревоги канала = новый эпизод
    exclude_years=[2021],      # по рекомендации организаторов
    gas_type=2,                # код «Газовый датчик»
    gas_threshold=1.0,         # 1% метана - порог тревоги по QA
    gas_state=19,              # «Обнаружен газ»
    # (код_типа_датчика, код_состояния) - «тревожные» состояния, которые на деле рабочий режим.
    # Заполните по отчёту alarm_states.csv после первого запуска (там видно, какие
    # пары дают тревогу в десятках % всех событий типа). Пример: [(15, 25)] -
    # «Работают все насосы в АНС» у насосов.
    exclude_alarm_states=[],
    # состояния-неисправности: Не определено, Неисправен, Неопределен, Отключено устройство.
    # Флаг состояние_техническое шире: в нём ещё «Норма» (17) и «Выключен» (6) - это рабочие
    # состояния (у дверей «Норма» = дверь закрылась, у насосов «Выключен» = штатная остановка).
    fault_states=[14, 15, 16, 22],
    extend_after_last_h=24 * 30,   # сетку канала продлеваем после последнего события (молчание)
    neg_keep_frac=0.05,        # доля пустых часов без цели, которые оставляем (с весом 1/доля)
    windows_h=[1, 6, 24, 168],
    seed=42,
)

# v2: сильнее регуляризация - на срезе train PR-AUC 0.40 против valid 0.16 (переобучение)
LGB_PARAMS = dict(
    objective='binary', learning_rate=0.03, num_leaves=31, min_child_samples=1000,
    feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=1, lambda_l2=10.0,
    cat_smooth=50, cat_l2=10, min_data_per_group=500, max_cat_threshold=16,
    verbose=-1, seed=CFG['seed'],
)

# v2: по умолчанию ид объекта/комплекса не подаём - в общей модели она запоминала объекты.
# Для газа они помогали (PR-AUC 0.256 с ними против 0.154 без) - включается флагом --object-id.
OBJECT_COLS = ['код_объекта', 'код_комплекса']
CAT_FEATURES = ['код_типа_датчика', 'state_last_ffill'] + OBJECT_COLS  # приводятся к int


def cat_features(use_object_id: bool) -> list[str]:
    return ['код_типа_датчика', 'state_last_ffill'] + (OBJECT_COLS if use_object_id else [])

# явные типы колонок csv (автоопределение duckdb может принять пустые числа за текст)
COL_TYPES = {
    'дата_время_события': 'TIMESTAMP', 'ид_канала_данных': 'BIGINT',
    'код_типа_датчика': 'INTEGER', 'код_объекта': 'INTEGER', 'код_комплекса': 'INTEGER',
    'объект_охранный': 'INTEGER', 'пикет': 'INTEGER', 'код_типа_значения': 'INTEGER',
    'код_состояния': 'INTEGER', 'состояние_техническое': 'INTEGER', 'тревожное_событие': 'INTEGER',
    'тревожное_по_справочнику': 'INTEGER', 'час': 'INTEGER', 'день_недели': 'INTEGER',
    'месяц': 'INTEGER', 'значение': 'DOUBLE', 'служебное_значение': 'INTEGER',
    'значение_z': 'DOUBLE', 'мало_истории_значение': 'INTEGER', 'лог_dt': 'DOUBLE',
    'лог_dt_z': 'DOUBLE', 'мало_истории_dt': 'INTEGER',
}


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ------------------------------------------------------------------------------------------------
# 1. АГРЕГАЦИЯ СОБЫТИЙ ДО «ДАТЧИК × ЧАС» (duckdb, не держит сырые события в памяти)
# ------------------------------------------------------------------------------------------------
def aggregate_hourly(files: list[str], cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """-> (agg: одна строка на канал-час с событиями, states: статистика тревог по типу×состоянию)."""
    if all(f.endswith('.parquet') for f in files):
        src = f"read_parquet({files}, union_by_name = true)"
    else:
        src = f"read_csv({files}, union_by_name = true, header = true, types = {COL_TYPES})"
    years = ','.join(str(y) for y in cfg['exclude_years']) or '-1'
    excl = ' OR '.join(f"(код_типа_датчика = {t} AND код_состояния = {s})"
                       for t, s in cfg['exclude_alarm_states']) or 'FALSE'
    faults = ','.join(str(s) for s in cfg.get('fault_states', CFG['fault_states'])) or '-1'

    flt = 'TRUE'
    if cfg.get('types'):
        flt += f" AND код_типа_датчика IN ({','.join(str(t) for t in cfg['types'])})"
    if cfg.get('channel_frac', 1.0) < 1.0:
        flt += f" AND (hash(ид_канала_данных) % 10000) < {int(cfg['channel_frac'] * 10000)}"

    con = duckdb.connect()
    con.sql(f"""
    CREATE TEMP VIEW ev AS
    SELECT
        CAST(ид_канала_данных AS BIGINT)                          AS ch,
        CAST(date_diff('hour', TIMESTAMP '1970-01-01', date_trunc('hour', CAST(дата_время_события AS TIMESTAMP))) AS BIGINT) AS h,
        CAST(дата_время_события AS TIMESTAMP)                     AS ts,
        код_типа_датчика, код_состояния, код_типа_значения,
        тревожное_событие, тревожное_по_справочнику, состояние_техническое, служебное_значение,
        мало_истории_значение, мало_истории_dt,
        CAST(значение AS DOUBLE) AS v, CAST(значение_z AS DOUBLE) AS vz,
        CAST(лог_dt AS DOUBLE) AS ldt, CAST(лог_dt_z AS DOUBLE) AS ldtz,
        -- настоящая тревога: флаг события без технических состояний, либо газ >= порога
        CASE WHEN (тревожное_событие = 1 AND состояние_техническое = 0 AND NOT ({excl}))
                  OR (код_типа_датчика = {cfg['gas_type']} AND
                      (значение >= {cfg['gas_threshold']} OR код_состояния = {cfg['gas_state']}))
             THEN 1 ELSE 0 END AS alarm,
        -- техническая проблема: состояние-неисправность, сбитая дата (binary), служебный код
        CASE WHEN код_состояния IN ({faults}) OR код_типа_значения = 1 OR служебное_значение = 1
             THEN 1 ELSE 0 END AS tech
    FROM {src}
    WHERE year(CAST(дата_время_события AS TIMESTAMP)) NOT IN ({years})
      AND {flt}
    """)

    states = con.sql("""
        SELECT код_типа_датчика, код_состояния, count(*) AS событий,
               sum(тревожное_событие) AS тревожных_raw, sum(alarm) AS тревог_в_цели,
               round(sum(тревожное_событие) / count(*), 4) AS доля_тревожных,
               round(count(*) / sum(count(*)) OVER (PARTITION BY код_типа_датчика), 4) AS доля_в_типе
        FROM ev GROUP BY 1, 2 ORDER BY 1, 2""").df()

    agg = con.sql(f"""
    WITH a AS (
        SELECT ch, h, ts, alarm,
               lag(ts) OVER (PARTITION BY ch ORDER BY ts) AS prev_ts
        FROM ev WHERE alarm = 1
    ), starts AS (
        SELECT ch, h, count(*) AS n_start
        FROM a
        WHERE prev_ts IS NULL OR date_diff('second', prev_ts, ts) > {cfg['episode_gap_h']} * 3600
        GROUP BY 1, 2
    ), hh AS (
        SELECT ch, h,
               count(*)                              AS n_ev,
               sum(alarm)                            AS n_alarm,
               sum(tech)                             AS n_tech,
               sum(тревожное_событие)                AS n_alarm_raw,
               sum(тревожное_по_справочнику)         AS n_alarm_ref,
               sum(служебное_значение)               AS n_serv,
               sum(мало_истории_значение + мало_истории_dt) AS n_lowhist,
               count(DISTINCT код_состояния)         AS n_states,
               avg(v) AS v_mean, max(v) AS v_max, min(v) AS v_min, arg_max(v, ts) AS v_last,
               max(abs(vz)) AS vz_absmax, avg(vz) AS vz_mean,
               stddev_pop(v) AS v_std, count(v) AS n_v,
               sum(CASE WHEN abs(vz) >= 3 THEN 1 ELSE 0 END) AS n_vz3,
               -- газ: «около порога» (0.5..1 от порога, ещё не тревога) и «метан обнаружен вообще»
               sum(CASE WHEN код_типа_датчика = {cfg['gas_type']} AND v >= {cfg['gas_threshold']} * 0.5
                             AND v < {cfg['gas_threshold']} THEN 1 ELSE 0 END) AS n_v_hi,
               sum(CASE WHEN код_типа_датчика = {cfg['gas_type']} AND v > 0.05 THEN 1 ELSE 0 END) AS n_v_pos,
               min(ldtz) AS ldtz_min, max(ldtz) AS ldtz_max, avg(ldt) AS ldt_mean,
               arg_max(код_состояния, ts)            AS state_last,
               arg_max(alarm, ts)                    AS alarm_last
        FROM ev GROUP BY 1, 2
    )
    SELECT hh.*, coalesce(s.n_start, 0) AS n_start
    FROM hh LEFT JOIN starts s USING (ch, h)
    ORDER BY ch, h
    """).df()
    con.close()

    for c in agg.columns:
        if c in ('ch', 'h'):
            agg[c] = agg[c].astype('int64')
        elif agg[c].dtype.kind in 'if':
            agg[c] = agg[c].astype('float32')
    return agg, states


# ------------------------------------------------------------------------------------------------
# 2. ПЛОТНАЯ СЕТКА ЧАСОВ И СКОЛЬЗЯЩИЕ ПРИЗНАКИ (векторно, без циклов по каналам)
# ------------------------------------------------------------------------------------------------
class Grid:
    """Плотная сетка: для каждого канала - все часы от первого события до
    min(последнее событие + extend, конец данных). Массивы выровнены по позиции."""

    def __init__(self, agg: pd.DataFrame, cfg: dict, end_h: int | None = None):
        g = agg.groupby('ch')['h'].agg(['min', 'max'])
        global_end = int(agg['h'].max()) if end_h is None else end_h
        g['end'] = np.minimum(g['max'] + cfg['extend_after_last_h'], global_end)
        lens = (g['end'] - g['min'] + 1).to_numpy()
        self.n = int(lens.sum())
        self.channels = g.index.to_numpy()
        self.gstart_pos = np.concatenate([[0], np.cumsum(lens)[:-1]])
        self.ch = np.repeat(self.channels, lens)
        self.gs = np.repeat(self.gstart_pos, lens)               # позиция начала группы
        self.ge = self.gs + np.repeat(lens, lens) - 1            # позиция конца группы
        self.pos = np.arange(self.n)
        self.h = np.repeat(g['min'].to_numpy(), lens) + (self.pos - self.gs)

        start_map = pd.Series(self.gstart_pos, index=self.channels)
        min_map = g['min']
        self.agg_pos = (start_map.reindex(agg['ch']).to_numpy()
                        + agg['h'].to_numpy() - min_map.reindex(agg['ch']).to_numpy())

    def dense(self, values: np.ndarray, fill=0.0) -> np.ndarray:
        out = np.full(self.n, fill, dtype='float32')
        out[self.agg_pos] = values
        return out

    def roll_sum(self, x: np.ndarray, w: int) -> np.ndarray:
        """Сумма за последние w часов, включая текущий."""
        c = np.concatenate([[0.0], np.cumsum(x, dtype='float64')])
        lo = np.maximum(self.pos - w + 1, self.gs)
        return (c[self.pos + 1] - c[lo]).astype('float32')

    def roll_sum_lag(self, x: np.ndarray, w: int, lag: int) -> np.ndarray:
        """Сумма за окно из w часов, заканчивающееся lag часов назад: позиции [i-lag-w+1, i-lag]."""
        c = np.concatenate([[0.0], np.cumsum(x, dtype='float64')])
        hi = self.pos - lag
        lo = np.maximum(hi - w + 1, self.gs)
        ok = hi >= self.gs
        hi_c = np.where(ok, hi, self.gs)
        return np.where(ok, c[hi_c + 1] - c[lo], 0.0).astype('float32')

    def roll_max(self, x: np.ndarray, w: int) -> np.ndarray:
        """Максимум за последние w часов, включая текущий (по каждому каналу отдельно)."""
        from scipy.ndimage import maximum_filter1d
        out = np.empty(self.n, 'float32')
        ends = np.append(self.gstart_pos[1:], self.n)
        for a, b in zip(self.gstart_pos, ends):
            out[a:b] = maximum_filter1d(x[a:b], size=w, origin=(w - 1) // 2, mode='constant', cval=-np.inf)
        return out

    def hours_since(self, flag: np.ndarray, cap: float = 24 * 365) -> np.ndarray:
        """Часов с последнего часа, где flag > 0 (0 - если в текущем часе). Нет истории -> cap."""
        last = np.where(flag > 0, self.pos, -1)
        last = np.maximum.accumulate(last)
        out = (self.pos - last).astype('float32')
        out[last < self.gs] = cap
        return np.minimum(out, cap)

    def future_sum(self, x: np.ndarray, H: int) -> tuple[np.ndarray, np.ndarray]:
        """Сумма x в часах (t, t+H]. -> (сумма, известна_ли_полностью)."""
        c = np.concatenate([[0.0], np.cumsum(x, dtype='float64')])
        hi = np.minimum(self.pos + H, self.ge)
        return (c[hi + 1] - c[self.pos + 1]).astype('float32'), (self.pos + H <= self.ge)

    def hours_to_next(self, flag: np.ndarray) -> np.ndarray:
        """Часов до следующего часа (строго после текущего), где flag > 0; нет -> inf."""
        nxt = np.where(flag > 0, self.pos, np.iinfo('int64').max)
        nxt = np.minimum.accumulate(nxt[::-1])[::-1]              # ближайший >= pos
        nxt = np.concatenate([nxt[1:], [np.iinfo('int64').max]])  # строго > pos
        out = (nxt - self.pos).astype('float64')
        out[nxt > self.ge] = np.inf
        return out


EXTRA_FEATURE_NAMES: set = set()   # заполняется в add_extra_features (для сравнения v3/v4)


def add_extra_features(G: 'Grid', base: dict, feats: dict, K: np.ndarray, H: int):
    """v4: периодичность и склонность датчика к тревогам (только прошлое)."""
    before = set(feats)
    st = base['n_start']
    # периодичность: были ли начала эпизодов в том же окне сутки/неделю/.. назад.
    # Цель смотрит на (t, t+H]; «то же окно d суток назад» = (t-24d, t-24d+H].
    lag_cnt = np.zeros(G.n, 'float32')
    for d in (1, 2, 3, 7, 14, 21, 28):
        lag = 24 * d - H                       # окно заканчивается в t-24d+H
        if lag < 0:
            continue
        v = G.roll_sum_lag(st, H, lag)
        if d in (1, 7, 14):
            feats[f'start_same_window_{d}d_ago'] = v[K]
        if d in (7, 14, 21, 28):
            lag_cnt += (v > 0)
    feats['weeks_with_start_same_window_4w'] = lag_cnt[K]
    days_cnt = np.zeros(G.n, 'float32')
    for d in range(1, 8):
        days_cnt += (G.roll_sum_lag(st, H, 24 * d - H) > 0) if 24 * d >= H else 0
    feats['days_with_start_same_window_7d'] = days_cnt[K]
    # суточный ритм: начала эпизодов в ближайшие 6 ч «по часам» вчера и неделю назад
    for d in (1, 7):
        feats[f'start_next6h_{d}d_ago'] = G.roll_sum_lag(st, 6, 24 * d - 6)[K]
    # склонность: длинные окна и вся история
    for c in ('n_start', 'n_alarm', 'n_tech', 'n_ev'):
        for w in (720, 2160):
            feats[f'{c}_{w}h'] = G.roll_sum(base[c], w)[K]
    # история считается от начала загруженных данных, поэтому ограничена 90 днями: иначе
    # «возраст» и «частота за всю историю» - это прокси календарной даты на обучении и
    # другие числа в predict на одном годовом файле
    hist = np.minimum(G.pos - G.gs + 1, 2160).astype('float32')
    feats['hist_h_90d'] = hist[K]
    feats['start_rate_90d'] = feats['n_start_2160h'] / hist[K] * 24     # эпизодов в сутки
    feats['tech_rate_90d'] = feats['n_tech_2160h'] / hist[K] * 24
    feats['start_rate_ratio_168_2160'] = (feats['n_start_168h'] / 7 + 1e-3) / (feats['n_start_2160h'] / 90 + 1e-3)
    EXTRA_FEATURE_NAMES.update(set(feats) - before)
    EXTRA_FEATURE_NAMES.update({'nbr_n_start_720h', 'nbr_n_alarm_720h'})


VALUE_FEATURE_NAMES: set = set()


def add_value_features(G: 'Grid', base: dict, nanfill: dict, feats: dict, K: np.ndarray):
    """v5: динамика значений (газ, температура, ИБП): средний уровень, дрейф, разброс, выбросы,
    показания около порога газа. Только прошлое."""
    before = set(feats)
    n_v = base['n_v']
    vsum = np.nan_to_num(nanfill['v_mean']) * n_v
    for w in (6, 24, 168):
        den = G.roll_sum(n_v, w)
        feats[f'v_mean_{w}h'] = np.where(den > 0, G.roll_sum(vsum, w) / np.maximum(den, 1), np.nan)[K]
    feats['v_drift_24_168'] = feats['v_mean_24h'] - feats['v_mean_168h']
    feats['v_drift_6_24'] = feats['v_mean_6h'] - feats['v_mean_24h']
    r = G.roll_max(np.nan_to_num(nanfill['v_max'], nan=-1e3), 6)[K]
    r[r == -1e3] = np.nan
    feats['v_max_max_6h'] = r
    r = G.roll_max(np.nan_to_num(nanfill['v_std'], nan=-1.0), 24)[K]
    r[r < 0] = np.nan
    feats['v_std_max_24h'] = r
    for c in ('n_vz3', 'n_v_hi', 'n_v_pos'):
        for w in (24, 168, 720):
            feats[f'{c}_{w}h'] = G.roll_sum(base[c], w)[K]
    feats['h_since_v_hi'] = G.hours_since(base['n_v_hi'])[K]
    feats['h_since_v_pos'] = G.hours_since(base['n_v_pos'])[K]
    vl = pd.Series(nanfill['v_last']).groupby(G.ch).ffill()
    for lag in (1, 6, 168):
        feats[f'v_slope_{lag}h'] = (vl - vl.groupby(G.ch).shift(lag)).to_numpy('float32')[K]
    VALUE_FEATURE_NAMES.update(set(feats) - before)
    VALUE_FEATURE_NAMES.add('v_std')


RECUR_FEATURE_NAMES: set = set()


def add_recurrence_features(G: 'Grid', base: dict, nanfill: dict, feats: dict, K: np.ndarray, H: int):
    """v6: регулярность эпизодов и «висящая» тревога. Только прошлое.
    Большая часть тревог повторяется (насосы, ИБП, охрана): важно не только «сколько было»,
    но и «какой обычно интервал между эпизодами и сколько прошло с последнего»."""
    before = set(feats)
    st = base['n_start']

    # интервалы между началами эпизодов: последний и сглаженный (EWM по 5 последним)
    idx = np.flatnonzero(st > 0)
    gaps = pd.Series(np.diff(idx, prepend=-1).astype('float64'))
    if len(idx):
        gaps[np.r_[True, G.ch[idx][1:] != G.ch[idx][:-1]]] = np.nan      # первый эпизод канала
        ewm = gaps.groupby(G.ch[idx]).transform(lambda s: s.ewm(span=5, ignore_na=True).mean())
    else:
        # Prediction windows without alarms are valid and common.  Pandas rejects
        # the one-item "first group" mask when there are no episode rows.
        ewm = gaps.copy()
    for name, vals in (('start_gap_last', gaps), ('start_gap_ewm', ewm)):
        d = np.full(G.n, np.nan, 'float32')
        d[idx] = vals.to_numpy('float32')
        d = pd.Series(d).groupby(G.ch).ffill().to_numpy('float32')
        feats[name] = d[K]
    hs = feats['h_since_start']
    feats['start_overdue'] = hs / np.maximum(feats['start_gap_ewm'], 1)   # >1 - эпизод «запаздывает»
    feats['start_expected_in_h'] = feats['start_gap_ewm'] - hs              # <0 - уже должен был быть

    # регулярность по неделям: в скольких из последних 4/12 недель был эпизод
    wk = np.zeros(G.n, 'float32')
    for k in range(12):
        wk += G.roll_sum_lag(st, 168, 168 * k) > 0
        if k == 3:
            feats['weeks_with_start_4w'] = wk[K].copy()
    feats['weeks_with_start_12w'] = wk[K]
    # то же окно год назад (сезонность; нужна история >= 1 года, иначе 0)
    feats['start_same_window_1y_ago'] = G.roll_sum_lag(st, H + 336, 8760 - H - 168)[K]

    # «висящая» тревога: последнее событие датчика - тревога; сколько часов она висит
    open_ = pd.Series(nanfill['alarm_last']).groupby(G.ch).ffill().fillna(0).to_numpy('float32')
    prev = np.r_[0, open_[:-1]]
    prev[G.gstart_pos] = 0
    opened = ((open_ > 0) & (prev == 0)).astype('float32')
    feats['alarm_open'] = open_[K]
    feats['alarm_open_h'] = np.where(open_ > 0, G.hours_since(opened), 0)[K].astype('float32')
    RECUR_FEATURE_NAMES.update(set(feats) - before)


def object_features(agg: pd.DataFrame, static: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    """Сумма тревог/тех.проблем/событий по объекту за окна -> для признаков «соседи»."""
    a = agg[['ch', 'h', 'n_alarm', 'n_tech', 'n_ev', 'n_start']].merge(
        static[['ch', 'код_объекта']], on='ch', how='left')
    o = a.groupby(['код_объекта', 'h'], as_index=False)[['n_alarm', 'n_tech', 'n_ev', 'n_start']].sum()
    o = o.sort_values(['код_объекта', 'h'])
    frames = []
    for obj, d in o.groupby('код_объекта'):
        idx = pd.RangeIndex(d['h'].min(), d['h'].max() + 720 + 1)
        d = d.set_index('h').reindex(idx, fill_value=0)
        res = pd.DataFrame({'код_объекта': obj, 'h': idx})
        for col in ('n_alarm', 'n_tech', 'n_start', 'n_ev'):
            v = d[col].to_numpy('float64')
            c = np.concatenate([[0.0], np.cumsum(v)])
            for w in list(windows) + ([720] if col in ('n_start', 'n_alarm') else []):
                if w == 1 and col != 'n_alarm':
                    continue
                lo = np.maximum(np.arange(len(v)) - w + 1, 0)
                res[f'obj_{col}_{w}h'] = (c[np.arange(len(v)) + 1] - c[lo]).astype('float32')
        frames.append(res)
    return pd.concat(frames, ignore_index=True)


def build_features(agg: pd.DataFrame, static: pd.DataFrame, cfg: dict,
                   end_h: int | None = None, keep_all: bool = False, only_last: bool = False):
    """-> (X: DataFrame признаков, meta: DataFrame ch/h/цель/вес/...,
           silence: DataFrame эпизодов молчания).
    keep_all=True - не прореживать пустые часы; only_last=True - только последний час каждого канала."""
    G = Grid(agg, cfg, end_h)
    log(f'сетка: {G.n:,} канал-часов, каналов {len(G.channels):,}')
    W = cfg['windows_h']

    base = {c: G.dense(agg[c].to_numpy('float32')) for c in
            ('n_ev', 'n_alarm', 'n_tech', 'n_alarm_raw', 'n_alarm_ref', 'n_serv', 'n_lowhist', 'n_start',
             'n_v', 'n_vz3', 'n_v_hi', 'n_v_pos') if c in agg}
    nanfill = {c: G.dense(agg[c].to_numpy('float32'), np.nan) for c in
               ('v_mean', 'v_max', 'v_min', 'v_last', 'vz_absmax', 'vz_mean', 'v_std',
                'ldtz_min', 'ldtz_max', 'ldt_mean', 'n_states', 'state_last', 'alarm_last')}

    # --- цель: начало нового эпизода тревоги в (t, t+H]
    H = cfg['horizon_h']
    fut, known = G.future_sum(base['n_start'], H)
    y = (fut > 0).astype('int8')
    to_next = G.hours_to_next(base['n_start'])

    # --- какие строки оставляем
    rng = np.random.default_rng(cfg['seed'])
    if only_last:
        keep = G.pos == G.ge
        weight = np.ones(G.n, 'float32')
    elif keep_all:
        keep = np.ones(G.n, bool)
        weight = np.ones(G.n, 'float32')
    else:
        # положительные - всегда; часы с событиями без цели - доля event_neg_keep_frac;
        # пустые часы без цели - доля neg_keep_frac. Вес = 1 / доля, метрики не искажаются.
        ev_frac = cfg.get('event_neg_keep_frac', 1.0)
        u = rng.random(G.n)
        pos = y > 0
        has_ev = base['n_ev'] > 0
        keep_ev = has_ev & ~pos & (u < ev_frac)
        keep_empty = ~has_ev & ~pos & (u < cfg['neg_keep_frac'])
        keep = known & (pos | keep_ev | keep_empty)
        weight = np.where(pos, 1.0, np.where(has_ev, 1.0 / ev_frac, 1.0 / cfg['neg_keep_frac'])).astype('float32')
    K = np.flatnonzero(keep)
    log(f'строк в выборке: {len(K):,}  (положительных {int(y[K].sum()):,})')

    feats: dict[str, np.ndarray] = {}
    # текущий час
    for c in ('n_ev', 'n_alarm', 'n_tech', 'n_serv', 'n_alarm_ref'):
        feats[f'{c}_1h'] = base[c][K]
    for c, v in nanfill.items():
        feats[c] = v[K]
    # скользящие суммы
    for c in ('n_ev', 'n_alarm', 'n_tech', 'n_start', 'n_alarm_raw', 'n_alarm_ref', 'n_serv', 'n_lowhist'):
        for w in W:
            if w == 1:
                continue
            feats[f'{c}_{w}h'] = G.roll_sum(base[c], w)[K]
    # активные часы за сутки/неделю (ритм)
    active = (base['n_ev'] > 0).astype('float32')
    for w in (24, 168):
        feats[f'active_hours_{w}h'] = G.roll_sum(active, w)[K]
    # экстремумы
    for c, src, fill in (('vz_absmax', 'vz_absmax', 0.0), ('v_max', 'v_max', -1e3),
                         ('ldtz_max', 'ldtz_max', -1e3)):
        x = np.nan_to_num(nanfill[src], nan=fill)
        for w in (24, 168):
            r = G.roll_max(x, w)[K]
            r[r == fill] = np.nan
            feats[f'{c}_max_{w}h'] = r
    ldtz_neg = np.nan_to_num(-nanfill['ldtz_min'], nan=-1e3)
    r = G.roll_max(ldtz_neg, 24)[K]
    r[r == -1e3] = np.nan
    feats['ldtz_min_24h'] = -r
    # время с последнего ...
    feats['h_since_event'] = G.hours_since(base['n_ev'])[K]
    feats['h_since_alarm'] = G.hours_since(base['n_alarm'])[K]
    feats['h_since_start'] = G.hours_since(base['n_start'])[K]
    feats['h_since_tech'] = G.hours_since(base['n_tech'])[K]
    # последнее известное значение (для газа/температуры/ИБП) - протягиваем вперёд
    vl = pd.Series(nanfill['v_last']).groupby(G.ch).ffill().to_numpy('float32')
    feats['v_last_ffill'] = vl[K]
    feats['v_trend_24h'] = (vl - pd.Series(vl).groupby(G.ch).shift(24).to_numpy('float32'))[K]
    sl = pd.Series(nanfill['state_last']).groupby(G.ch).ffill().to_numpy('float32')
    feats['state_last_ffill'] = sl[K]
    if cfg.get('extra_features', True):
        add_extra_features(G, base, feats, K, H)
    # без проверки base['n_v'].any(): набор колонок не должен зависеть от данных, иначе
    # predict по типам без чисел падает на KeyError
    if cfg.get('value_features', True):
        add_value_features(G, base, nanfill, feats, K)
    if cfg.get('recurrence_features', True):
        add_recurrence_features(G, base, nanfill, feats, K, H)
    # доли
    feats['alarm_share_168h'] = feats['n_alarm_168h'] / np.maximum(feats['n_ev_168h'], 1)
    feats['tech_share_168h'] = feats['n_tech_168h'] / np.maximum(feats['n_ev_168h'], 1)

    X = pd.DataFrame(feats)
    meta = pd.DataFrame({'ch': G.ch[K], 'h': G.h[K], 'y': y[K], 'w': weight[K],
                         'to_next': to_next[K]})

    # время
    ts = pd.to_datetime(meta['h'].to_numpy() * 3600, unit='s')
    X['час_sin'] = np.sin(2 * np.pi * ts.hour / 24).astype('float32')
    X['час_cos'] = np.cos(2 * np.pi * ts.hour / 24).astype('float32')
    X['дн_sin'] = np.sin(2 * np.pi * ts.dayofweek / 7).astype('float32')
    X['дн_cos'] = np.cos(2 * np.pi * ts.dayofweek / 7).astype('float32')
    X['мес_sin'] = np.sin(2 * np.pi * (ts.month - 1) / 12).astype('float32')
    X['мес_cos'] = np.cos(2 * np.pi * (ts.month - 1) / 12).astype('float32')
    meta['ts'] = ts

    # статика канала
    st = static.set_index('ch').reindex(meta['ch'])
    for c in ('код_типа_датчика', 'код_объекта', 'код_комплекса', 'объект_охранный', 'пикет'):
        X[c] = st[c].to_numpy()
    meta['код_типа_датчика'] = X['код_типа_датчика'].to_numpy()

    # соседи по объекту (объект минус сам канал)
    of = object_features(agg, static, W)
    m = pd.DataFrame({'код_объекта': X['код_объекта'].to_numpy(), 'h': meta['h'].to_numpy()})
    m = m.merge(of, on=['код_объекта', 'h'], how='left')
    for c in of.columns:
        if not c.startswith('obj_'):
            continue
        own = c.replace('obj_', '')                      # n_alarm_24h и т.п.
        v = m[c].fillna(0).to_numpy('float32')
        X[c.replace('obj_', 'nbr_')] = v - X[own].to_numpy('float32') if own in X else v

    for c in CAT_FEATURES:
        X[c] = X[c].fillna(-1).astype('int32')

    silence = silence_episodes(G, base['n_ev'], agg) if not only_last else None
    return X, meta, silence


# ------------------------------------------------------------------------------------------------
# 3. ПРАВИЛА АНОМАЛИЙ: молчание датчика
# ------------------------------------------------------------------------------------------------
def silence_episodes(G: Grid, n_ev: np.ndarray, agg: pd.DataFrame) -> pd.DataFrame:
    """Эпизод молчания: часов без событий > max(24, 5 × p95 обычного перерыва канала)."""
    a = agg[['ch', 'h']].copy()
    a['gap'] = a.groupby('ch')['h'].diff()
    thr = a.groupby('ch')['gap'].quantile(0.95).fillna(24).clip(lower=1) * 5
    thr = np.maximum(thr, 24)
    since = G.hours_since(n_ev)
    t = pd.Series(thr).reindex(G.ch).to_numpy()
    silent = since > t
    start = silent & ~np.concatenate([[False], silent[:-1]]) | (silent & (G.pos == G.gs))
    idx = np.flatnonzero(start)
    if len(idx) == 0:
        return pd.DataFrame({'ch': pd.Series(dtype='int64'),
                             'начало_молчания': pd.Series(dtype='datetime64[ns]'),
                             'обнаружено': pd.Series(dtype='datetime64[ns]'),
                             'порог_ч': pd.Series(dtype='float64')})
    return pd.DataFrame({
        'ch': G.ch[idx],
        'начало_молчания': pd.to_datetime((G.h[idx] - since[idx]) * 3600, unit='s'),
        'обнаружено': pd.to_datetime(G.h[idx] * 3600, unit='s'),
        'порог_ч': t[idx].round(1),
    })


# ------------------------------------------------------------------------------------------------
# 4. МЕТРИКИ
# ------------------------------------------------------------------------------------------------
def metrics(y, p, w) -> dict:
    if y.sum() == 0 or y.sum() == len(y):
        return dict(n=int(len(y)), pos=int(y.sum()), pr_auc=None, roc_auc=None)
    return dict(n=int(len(y)), pos=int(y.sum()),
                pos_rate=float(np.average(y, weights=w)),
                pr_auc=float(average_precision_score(y, p, sample_weight=w)),
                roc_auc=float(roc_auc_score(y, p, sample_weight=w)))


def episode_recall(meta: pd.DataFrame, score: np.ndarray, thr: float, H: int) -> dict:
    """Сколько эпизодов тревоги модель предупредила заранее и за сколько часов."""
    m = meta.assign(s=score)
    m = m[np.isfinite(m['to_next']) & (m['to_next'] <= H)]
    if m.empty:
        return dict(episodes=0)
    m = m.assign(ep_h=m['h'] + m['to_next'])
    g = m.groupby(['ch', 'ep_h'])
    caught = g.apply(lambda d: (d['s'] >= thr).any(), include_groups=False)
    lead = g.apply(lambda d: d.loc[d['s'] >= thr, 'to_next'].max(), include_groups=False)
    return dict(episodes=int(len(caught)), caught=float(caught.mean()),
                lead_median_h=float(np.nanmedian(lead)) if caught.any() else None)


def prec_rec(y, s, w, thr):
    pred = s >= thr
    tp = float(np.sum(w * (pred & (y == 1))))
    fp = float(np.sum(w * (pred & (y == 0))))
    fn = float(np.sum(w * (~pred & (y == 1))))
    return dict(threshold=float(thr), precision=tp / max(tp + fp, 1e-9), recall=tp / max(tp + fn, 1e-9))


def pick_threshold(y, s, w, meta: pd.DataFrame, H: int, target_caught: float | None,
                   min_episodes: int = 0) -> float | None:
    """Порог на valid. target_caught=None - максимум F1 по строкам; иначе - наибольший порог,
    при котором заранее (хотя бы одно предупреждение за H ч) пойман target_caught эпизодов.
    None - если эпизодов меньше min_episodes (порог по такой выборке ненадёжен)."""
    tn = meta['to_next'].to_numpy()
    m = np.isfinite(tn) & (tn <= H)
    ep = pd.Series(s[m]).groupby([meta['ch'].to_numpy()[m], meta['h'].to_numpy()[m] + tn[m]]).max()
    if len(ep) < max(min_episodes, 1) or y.sum() == 0:
        return None
    if not target_caught:
        return best_f1_threshold(y, s, w)
    return float(np.quantile(ep.to_numpy(), 1 - target_caught, method='lower'))


def best_f1_threshold(y, s, w):
    qs = np.unique(np.quantile(s, np.linspace(0.5, 0.9995, 400)))
    best = (0, qs[-1])
    for t in qs:
        r = prec_rec(y, s, w, t)
        f1 = 2 * r['precision'] * r['recall'] / max(r['precision'] + r['recall'], 1e-9)
        if f1 > best[0]:
            best = (f1, t)
    return float(best[1])


# ------------------------------------------------------------------------------------------------
# 5. ОБУЧЕНИЕ
# ------------------------------------------------------------------------------------------------
def load_static(dicts: str) -> pd.DataFrame:
    s = pd.read_csv(os.path.join(dicts, 'map_channel.csv'))
    return s.rename(columns={'ид_канала_данных': 'ch'})


def parse_types(s: str | None) -> list[int]:
    return [int(x) for x in s.split(',') if x.strip()] if s else []


def resolve_files(pattern: str) -> list[str]:
    files = sorted(sum((glob.glob(p.strip()) for p in pattern.split(',')), []))
    if not files:
        raise SystemExit(f'нет файлов по шаблону {pattern}')
    return files


def prepare(files: list[str], cfg: dict, dicts: str, valid_start: str, test_start: str) -> dict:
    """Агрегация + признаки + разбиение по времени. -> контекст для обучения."""
    agg, states = aggregate_hourly(files, cfg)
    log(f'агрегатов канал-час: {len(agg):,}; эпизодов тревоги: {int(agg["n_start"].sum()):,}')
    static = load_static(dicts)
    X, meta, silence = build_features(agg, static, cfg)
    t_valid, t_test = pd.Timestamp(valid_start), pd.Timestamp(test_start)
    H = pd.Timedelta(hours=cfg['horizon_h'])
    # эмбарго: цель смотрит на H часов вперёд, поэтому хвост каждого периода отрезаем
    tr = (meta['ts'] < t_valid - H).to_numpy()
    va = ((meta['ts'] >= t_valid) & (meta['ts'] < t_test - H)).to_numpy()
    te = (meta['ts'] >= t_test).to_numpy()
    for n, m in (('train', tr), ('valid', va), ('test', te)):
        log(f'{n}: {m.sum():,} строк, положительных {int(meta["y"][m].sum()):,}')
    if meta['y'][tr].sum() == 0 or meta['y'][va].sum() == 0:
        raise SystemExit('нет положительных примеров в train или valid - проверьте даты разбиения')
    return dict(agg=agg, states=states, X=X, meta=meta, silence=silence, tr=tr, va=va, te=te,
                cfg=cfg, files=files, split=dict(valid_start=valid_start, test_start=test_start),
                t_valid=t_valid, t_test=t_test)


def select_features(X: pd.DataFrame, object_id: bool, extra: bool = True,
                    value: bool = True, recur: bool = True) -> tuple[list, list]:
    cols = [c for c in X.columns if (object_id or c not in OBJECT_COLS)
            and (extra or c not in EXTRA_FEATURE_NAMES)
            and (value or c not in VALUE_FEATURE_NAMES)
            and (recur or c not in RECUR_FEATURE_NAMES)]
    cats = [c for c in cat_features(object_id) if c in cols]
    return cols, cats


def train_lgb(ctx: dict, cols: list, cats: list, params: dict, rows=None, threads=None,
              rounds: int = 5000, log_every: int = 0):
    """rows - доп. маска строк (например, только газ). -> обученный Booster (best_iteration)."""
    X, meta = ctx['X'], ctx['meta']
    tr, va = ctx['tr'], ctx['va']
    if rows is not None:
        tr, va = tr & rows, va & rows
    y, w = meta['y'].to_numpy(), meta['w'].to_numpy()
    dtr = lgb.Dataset(X.loc[tr, cols], y[tr], weight=w[tr], categorical_feature=cats)
    dva = lgb.Dataset(X.loc[va, cols], y[va], weight=w[va], categorical_feature=cats, reference=dtr)
    prm = dict(LGB_PARAMS, metric='average_precision', num_threads=threads or os.cpu_count())
    prm.update(params or {})
    cb = [lgb.early_stopping(150, verbose=False)]
    if log_every:
        cb.append(lgb.log_evaluation(log_every))
    return lgb.train(prm, dtr, num_boost_round=rounds, valid_sets=[dva], valid_names=['valid'], callbacks=cb)


def ap_on(ctx, p, mask) -> float | None:
    y, w = ctx['meta']['y'].to_numpy(), ctx['meta']['w'].to_numpy()
    return metrics(y[mask], p[mask], w[mask])['pr_auc']


def evaluate_and_save(ctx: dict, model, cols: list, out: str, dicts: str, threads: int,
                      specialists: list | None = None, extra_report: dict | None = None):
    """Оценка на train/valid/test, отчёты, аномалии, сохранение артефактов для predict.
    specialists: [dict(name, types, model, cols, cats)] - модели, заменяющие общую для своих типов."""
    os.makedirs(out, exist_ok=True)
    X, meta, cfg = ctx['X'], ctx['meta'], ctx['cfg']
    tr, va, te = ctx['tr'], ctx['va'], ctx['te']
    types = meta['код_типа_датчика'].to_numpy()
    y, w = meta['y'].to_numpy(), meta['w'].to_numpy()

    H, tc = cfg['horizon_h'], cfg.get('target_caught')
    p = model.predict(X[cols], num_iteration=model.best_iteration)
    thr_general = pick_threshold(y[va], p[va], w[va], meta[va], H, tc)
    thr_vec = np.full(len(p), thr_general)
    spec_art = []
    for sp in specialists or []:
        rows = np.isin(types, sp['types'])
        p[rows] = sp['model'].predict(X.loc[rows, sp['cols']], num_iteration=sp['model'].best_iteration)
        m = va & rows
        t = pick_threshold(y[m], p[m], w[m], meta[m], H, tc) or thr_general
        thr_vec[rows] = t
        fname = f"lgb_{sp['name']}.txt"
        sp['model'].save_model(os.path.join(out, fname), num_iteration=sp['model'].best_iteration)
        spec_art.append(dict(name=sp['name'], types=list(sp['types']), model_file=fname,
                             feat_cols=sp['cols'], threshold=float(t)))
    # режим F1: свой порог для каждого типа с достаточным числом эпизодов на valid (доля тревог
    # у типов различается в десятки раз). В режиме «поймать N %» порог общий: иначе каждый тип,
    # даже где модель слабая, тянется до N % и засыпает диспетчера ложными (precision 0.24 против 0.36)
    type_thr = {}
    if cfg.get('per_type_threshold', not tc):
        for t in np.unique(types[va]):
            m = va & (types == t)
            tt = pick_threshold(y[m], p[m], w[m], meta[m], H, tc, min_episodes=30)
            if tt is not None:
                type_thr[int(t)] = tt
                thr_vec[types == t] = tt
    s_norm = p / thr_vec                        # >= 1 - сработка (у каждой модели свой порог)

    base_recent = X['n_alarm_24h'].to_numpy() + 1e-3 * X['n_alarm_168h'].to_numpy()
    base_since = 1.0 / (1.0 + X['h_since_start'].to_numpy())
    report = dict(config=cfg, files=ctx['files'], best_iteration=model.best_iteration,
                  split=ctx['split'], threshold=thr_general, type_thresholds=type_thr,
                  specialists=[{k: v for k, v in a.items() if k != 'feat_cols'} for a in spec_art])
    report.update(extra_report or {})
    for name, m in (('train', tr), ('valid', va), ('test', te)):
        if m.sum() == 0:
            continue
        report[name] = dict(model=metrics(y[m], p[m], w[m]),
                            baseline_alarm_24h=metrics(y[m], base_recent[m], w[m]),
                            baseline_since_episode=metrics(y[m], base_since[m], w[m]),
                            at_threshold=prec_rec(y[m], s_norm[m], w[m], 1.0),
                            episodes=episode_recall(meta[m], s_norm[m], 1.0, cfg['horizon_h']))

    ev = te if te.sum() else va
    st_names = pd.read_csv(os.path.join(dicts, 'map_sensor_type.csv')).set_index('код')['тип_датчика']
    per_type = []
    for t, idx in meta[ev].groupby('код_типа_датчика').groups.items():
        ii = meta.index.get_indexer(idx)
        r = metrics(y[ii], p[ii], w[ii])
        rb = metrics(y[ii], base_recent[ii], w[ii])
        per_type.append(dict(код=int(t), тип=st_names.get(int(t), '?'), строк=r['n'], положит=r['pos'],
                             pr_auc_модель=r['pr_auc'], pr_auc_база=rb['pr_auc'], roc_auc_модель=r['roc_auc']))
    per_type = pd.DataFrame(per_type)
    per_type.to_csv(os.path.join(out, 'metrics_by_type.csv'), index=False)
    ctx['states'].to_csv(os.path.join(out, 'alarm_states.csv'), index=False)

    imp = pd.DataFrame({'признак': cols, 'gain': model.feature_importance('gain'),
                        'split': model.feature_importance('split')}).sort_values('gain', ascending=False)
    imp.to_csv(os.path.join(out, 'feature_importance.csv'), index=False)

    # + базовые линии и контекст - для plots.py и разбора ошибок
    meta.loc[ev, ['ch', 'ts', 'код_типа_датчика', 'y', 'w', 'to_next']].assign(
        score=p[ev], alert=s_norm[ev] >= 1, base_24h=base_recent[ev], base_dt=base_since[ev],
        h_since_start=X.loc[ev, 'h_since_start'].to_numpy(),
        n_start_720h=X.loc[ev, 'n_start_720h'].to_numpy() if 'n_start_720h' in X else np.nan,
    ).to_csv(os.path.join(out, 'predictions_test.csv.gz'), index=False)
    for name, m in (('train', tr), ('valid', va), ('test', te)):
        if m.sum():
            report[name]['pr_auc_by_type'] = {
                int(t): metrics(y[m & (types == t)], p[m & (types == t)], w[m & (types == t)])['pr_auc']
                for t in np.unique(types[m])}

    anomalies, iso = fit_anomalies(X, meta, tr, ev, threads)
    anomalies.to_csv(os.path.join(out, 'anomalies.csv'), index=False)
    silence = ctx['silence']
    silence = silence[silence['обнаружено'] >= (ctx['t_test'] if te.sum() else ctx['t_valid'])]
    silence.to_csv(os.path.join(out, 'silence.csv'), index=False)
    report['anomalies'] = dict(top=len(anomalies), silence_episodes=len(silence))

    model.save_model(os.path.join(out, 'lgb_model.txt'), num_iteration=model.best_iteration)
    # всё, что нужно predict, - в небольшой json (можно хранить в git рядом с lgb_model.txt);
    # IsolationForest весит сотни МБ и нужен только для отчёта об аномалиях - отдельно
    with open(os.path.join(out, 'artifacts.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(cfg=cfg, feat_cols=cols, threshold=thr_general, specialists=spec_art,
                       type_thresholds=type_thr), f, ensure_ascii=False, indent=1, default=str)
    joblib.dump(iso, os.path.join(out, 'iso_forest.joblib'))
    with open(os.path.join(out, 'metrics.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print_report(report, per_type, imp)
    return report, per_type


def train(args):
    cfg = dict(CFG, horizon_h=args.horizon, types=parse_types(args.types),
               channel_frac=args.channel_frac, object_id=args.object_id,
               target_caught=args.target_caught)
    files = resolve_files(args.data)
    log('файлы:', *files)
    ctx = prepare(files, cfg, args.dicts, args.valid_start, args.test_start)
    cols, cats = select_features(ctx['X'], args.object_id)
    model = train_lgb(ctx, cols, cats, {}, threads=args.threads, log_every=100)
    log('лучшая итерация:', model.best_iteration)
    evaluate_and_save(ctx, model, cols, args.out, args.dicts, args.threads)


# ------------------------------------------------------------------------------------------------
# 6. ДЕТЕКТОР АНОМАЛИЙ (без учителя)
# ------------------------------------------------------------------------------------------------
ISO_FEATS = ['n_ev_1h', 'n_ev_24h', 'active_hours_24h', 'n_tech_24h', 'n_serv_24h', 'n_states',
             'ldtz_min', 'ldtz_max', 'vz_absmax', 'n_alarm_ref_24h', 'ldt_mean']


def fit_anomalies(X, meta, tr, ev, threads=None, top=500):
    """IsolationForest отдельно на каждый тип датчика по часам с событиями."""
    has_ev = (X['n_ev_1h'] > 0).to_numpy()
    feats = X[ISO_FEATS].fillna(0).to_numpy('float32')
    types = meta['код_типа_датчика'].to_numpy()
    iso, rows = {}, []
    for t in np.unique(types):
        m_tr = tr & has_ev & (types == t)
        m_ev = ev & has_ev & (types == t)
        if m_tr.sum() < 200 or m_ev.sum() == 0:
            continue
        clf = IsolationForest(n_estimators=200, max_samples=min(50_000, int(m_tr.sum())),
                              random_state=CFG['seed'], n_jobs=threads or os.cpu_count())
        clf.fit(feats[m_tr])
        iso[int(t)] = clf
        s = -clf.score_samples(feats[m_ev])               # больше = аномальнее
        # нормируем внутри типа: доля train-часов, которые менее аномальны
        s_tr = -clf.score_samples(feats[m_tr])
        pct = np.searchsorted(np.sort(s_tr), s) / len(s_tr)
        idx = np.flatnonzero(m_ev)
        rows.append(pd.DataFrame({'ch': meta['ch'].to_numpy()[idx], 'ts': meta['ts'].to_numpy()[idx],
                                  'код_типа_датчика': t, 'аномальность': s, 'перцентиль': pct,
                                  **{c: X[c].to_numpy()[idx] for c in ISO_FEATS}}))
    if not rows:
        return pd.DataFrame(), iso
    a = pd.concat(rows, ignore_index=True)
    # правило «дребезг»: событий за час выше 99.9-го перцентиля своего типа на train
    p999 = (pd.DataFrame({'t': types[tr & has_ev], 'n': X['n_ev_1h'].to_numpy()[tr & has_ev]})
            .groupby('t')['n'].quantile(0.999))
    a['дребезг'] = a['n_ev_1h'] > a['код_типа_датчика'].map(p999).fillna(np.inf)
    a = a.sort_values(['перцентиль', 'аномальность'], ascending=False).head(top)
    return a, iso


# ------------------------------------------------------------------------------------------------
# 7. ИНФЕРЕНС: ранжирование датчиков на последний час данных
# ------------------------------------------------------------------------------------------------
def predict(args):
    with open(os.path.join(args.out, 'artifacts.json'), encoding='utf-8') as f:
        art = json.load(f)
    art['type_thresholds'] = {int(t): v for t, v in art.get('type_thresholds', {}).items()}
    model = lgb.Booster(model_file=os.path.join(args.out, 'lgb_model.txt'))
    cfg = dict(art['cfg'], types=parse_types(args.types) or art['cfg'].get('types', []),
               channel_frac=args.channel_frac)
    files = resolve_files(args.data)
    agg, _ = aggregate_hourly(files, cfg)
    static = load_static(args.dicts)
    end_h = int(agg['h'].max())
    span_d = (end_h - int(agg['h'].min())) / 24
    if span_d < 90:
        log(f'ВНИМАНИЕ: в данных {span_d:.0f} дн. истории, а окна признаков до 90 дн. - '
            f'прогноз будет занижен у редких датчиков; подайте хотя бы последние 3 месяца')
    X, meta, _ = build_features(agg, static, cfg, end_h=end_h, only_last=True)
    meta['score'] = model.predict(X[art['feat_cols']])
    meta['тревога_прогноз'] = meta['score'] >= art['threshold']
    meta['модель'] = 'общая'
    for sp in art.get('specialists', []):
        rows = meta['код_типа_датчика'].isin(sp['types']).to_numpy()
        if rows.any():
            m = lgb.Booster(model_file=os.path.join(args.out, sp['model_file']))
            meta.loc[rows, 'score'] = m.predict(X.loc[rows, sp['feat_cols']])
            meta.loc[rows, 'тревога_прогноз'] = meta.loc[rows, 'score'] >= sp['threshold']
            meta.loc[rows, 'модель'] = sp['name']
    type_thr = meta['код_типа_датчика'].map(art.get('type_thresholds', {}))
    has = type_thr.notna().to_numpy()
    meta.loc[has, 'тревога_прогноз'] = meta.loc[has, 'score'] >= type_thr[has]
    st_names = pd.read_csv(os.path.join(args.dicts, 'map_sensor_type.csv')).set_index('код')['тип_датчика']
    meta['тип'] = meta['код_типа_датчика'].map(st_names)
    meta['код_объекта'] = X['код_объекта'].to_numpy()
    meta['пикет'] = X['пикет'].to_numpy()
    meta['часов_без_событий'] = X['h_since_event'].to_numpy()
    fresh = meta['h'] == end_h
    log(f'датчиков с данными до последнего часа: {int(fresh.sum()):,}; '
        f'замолчавших раньше (в прогноз не идут, см. silence.csv после train): {int((~fresh).sum()):,}')
    res = (meta.loc[fresh, ['ch', 'тип', 'код_объекта', 'пикет', 'ts', 'часов_без_событий', 'score',
                            'тревога_прогноз', 'модель']]
           .sort_values('score', ascending=False))
    path = os.path.join(args.out, 'risk_ranking.csv')
    res.to_csv(path, index=False)
    log(f'момент прогноза: конец часа {res["ts"].max()}; датчиков: {len(res):,}; '
        f'выше порога: {int(res["тревога_прогноз"].sum())}')
    print(res.head(20).to_string(index=False))
    log('сохранено:', path)


# ------------------------------------------------------------------------------------------------
def print_report(report, per_type, imp):
    def f(x):
        return '-' if x is None else f'{x:.3f}'
    print('\n' + '=' * 90)
    print(f"ПРОГНОЗ НАЧАЛА ЭПИЗОДА ТРЕВОГИ В БЛИЖАЙШИЕ {report['config']['horizon_h']} Ч")
    print('=' * 90)
    print(f"{'выборка':8} {'строк':>10} {'полож':>7} {'PR-AUC':>7} {'база24ч':>8} {'базаΔt':>7} "
          f"{'ROC':>6} {'prec':>6} {'recall':>6} {'эпиз.':>6} {'поймано':>8} {'заранее,ч':>9}")
    for n in ('train', 'valid', 'test'):
        if n not in report:
            continue
        r = report[n]
        e = r['episodes']
        print(f"{n:8} {r['model']['n']:>10,} {r['model']['pos']:>7,} {f(r['model']['pr_auc']):>7} "
              f"{f(r['baseline_alarm_24h']['pr_auc']):>8} {f(r['baseline_since_episode']['pr_auc']):>7} "
              f"{f(r['model']['roc_auc']):>6} {r['at_threshold']['precision']:>6.3f} "
              f"{r['at_threshold']['recall']:>6.3f} {e.get('episodes', 0):>6} "
              f"{f(e.get('caught')):>8} {f(e.get('lead_median_h')):>9}")
    print('\nПо типам датчиков (test, или valid если теста нет):')
    print(per_type.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
    print('\nТоп-15 признаков:')
    print(imp.head(15).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('train', 'predict'):
        p = sub.add_parser(name)
        p.add_argument('--data', required=True, help='шаблон файлов, можно через запятую')
        p.add_argument('--dicts', default=os.path.join(HERE, 'dicts'))
        p.add_argument('--out', default=os.path.join(HERE, 'out'))
        p.add_argument('--threads', type=int, default=os.cpu_count())
        p.add_argument('--types', default=None,
                       help='только эти коды типов датчиков, через запятую (например 2,4,15)')
        p.add_argument('--channel-frac', type=float, default=1.0,
                       help='доля датчиков (0..1), случайная но воспроизводимая - для полных данных')
    t = sub.choices['train']
    t.add_argument('--valid-start', default='2025-01-01')
    t.add_argument('--test-start', default='2026-01-01')
    t.add_argument('--horizon', type=int, default=CFG['horizon_h'])
    t.add_argument('--target-caught', type=float, default=0.85,
                   help='порог срабатывания: поймать заранее эту долю эпизодов на valid; '
                        '0 - максимум F1 (меньше ложных, но и меньше пойманных)')
    t.add_argument('--object-id', action='store_true',
                   help='подавать в модель код_объекта/код_комплекса (полезно для газа)')
    args = ap.parse_args()
    train(args) if args.cmd == 'train' else predict(args)


if __name__ == '__main__':
    main()
