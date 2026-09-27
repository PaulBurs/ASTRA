"""Онлайн-признаки: сырое событие СМВУ -> строка признаков, ИДЕНТИЧНАЯ строке ml.dataset_ml
(+ sin/cos из ml.v_dataset_ml). На этом же преобразовании обучается модель.

    from lct_features import OnlineFeaturizer
    fz = OnlineFeaturizer()
    fz.warm_up_from_postgres(conn, now)          # один раз при старте (история для окон)
    row = fz.process_raw(channel_id, ts, alarm_raw, value_raw)
    if row is not None:
        X = [row[c] for c in MODEL_FEATURES]     # MODEL_FEATURES выберет ML-инженер

Порядок: события одного канала подавать по возрастанию времени. Разные каналы - в любом
порядке относительно друг друга. Состояние - в памяти процесса (один экземпляр на сервис);
save_state()/load_state() - чтобы не прогревать заново после перезапуска.
"""
from __future__ import annotations

import math
import pickle
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .parse import ParsedValue, parse_alarm, parse_ts, parse_value
from .reference import Reference

N_MIN = 5          # минимум прошлых точек в окне, иначе z = None и флаг мало_истории = 1
DT_EPS = 0.01      # eps для лог_dt

# Столбцы ml.dataset_ml в порядке таблицы + циклические из ml.v_dataset_ml
DATASET_COLUMNS = [
    'дата_время_события', 'ид_канала_данных', 'код_типа_датчика', 'код_объекта', 'код_комплекса',
    'объект_охранный', 'пикет', 'код_типа_значения', 'код_состояния', 'состояние_техническое',
    'тревожное_событие', 'тревожное_по_справочнику', 'час', 'день_недели', 'месяц',
    'значение', 'служебное_значение', 'значение_z', 'мало_истории_значение',
    'лог_dt', 'лог_dt_z', 'мало_истории_dt',
]
CYCLIC_COLUMNS = ['час_sin', 'час_cos', 'день_недели_sin', 'день_недели_cos', 'месяц_sin', 'месяц_cos']
ALL_COLUMNS = DATASET_COLUMNS + CYCLIC_COLUMNS
KEY_COLUMNS = ['дата_время_события', 'ид_канала_данных']   # не признаки модели


@dataclass
class _ChannelState:
    cur_t: Optional[datetime] = None           # текущая секунда канала
    prev_t: Optional[datetime] = None          # последний момент строго раньше cur_t
    seen: set = field(default_factory=set)     # (тревожное_raw, значение_raw) в cur_t - для дедупа
    pend_v: list = field(default_factory=list) # значения текущей секунды (в окно - со следующей)
    pend_d: list = field(default_factory=list)
    win_v: deque = field(default_factory=deque)  # (время, значение)
    win_d: deque = field(default_factory=deque)  # (время, лог_dt)


def _stats(win):
    n = len(win)
    if n == 0:
        return 0, 0.0, 0.0
    vals = [v for _, v in win]
    mu = math.fsum(vals) / n
    return n, mu, math.fsum((v - mu) ** 2 for v in vals) / n


class OnlineFeaturizer:
    def __init__(self, reference: Optional[Reference] = None, on_late: str = 'skip'):
        """on_late: что делать с событием канала, пришедшим раньше уже обработанного:
        'skip' - пропустить (stats['late']), 'raise' - ValueError."""
        self.ref = reference or Reference()
        self.on_late = on_late
        self.state: dict[int, _ChannelState] = {}
        self.stats = Counter()

    # ---- публичный API ---------------------------------------------------------------
    def process_raw(self, channel_id, ts, alarm_raw, value_raw: str) -> Optional[dict]:
        """Сырое событие СМВУ -> dict признаков (ALL_COLUMNS) или None, если событие
        отброшено так же, как при сборке датасета: канал не из справочника (stats['orphan']),
        полный дубль (stats['duplicate']), опоздавшее событие (stats['late'])."""
        channel_id = int(channel_id)
        ch = self.ref.channels.get(channel_id)
        if ch is None:
            self.stats['orphan'] += 1
            return None
        ts = parse_ts(ts)
        alarm = parse_alarm(alarm_raw)
        s = self.state.setdefault(channel_id, _ChannelState())
        if s.cur_t is not None and ts < s.cur_t:
            return self._late(channel_id, ts, s)
        key = (alarm, value_raw)
        if ts == s.cur_t and key in s.seen:
            self.stats['duplicate'] += 1
            return None
        row = self._features(ch, s, ts, alarm, parse_value(value_raw))
        s.seen.add(key)
        return row

    def process_parsed(self, channel_id, ts, alarm: bool, value_type: str,
                       number=None, text=None) -> Optional[dict]:
        """То же для уже разобранного события (например, строки ml.dataset_events). Без дедупа."""
        ch = self.ref.channels.get(int(channel_id))
        if ch is None:
            self.stats['orphan'] += 1
            return None
        ts = parse_ts(ts)
        s = self.state.setdefault(ch.channel_id, _ChannelState())
        if s.cur_t is not None and ts < s.cur_t:
            return self._late(ch.channel_id, ts, s)
        pv = ParsedValue(value_type,
                         number=None if number is None else float(number),
                         text=text if value_type == 'text' else None)
        return self._features(ch, s, ts, bool(alarm), pv)

    def seed_last_event(self, channel_id, ts) -> None:
        """Сообщить момент последнего события канала до начала прогрева (нужно для лог_dt)."""
        s = self.state.setdefault(int(channel_id), _ChannelState())
        if s.cur_t is None and ts is not None:
            s.cur_t = parse_ts(ts)

    def warm_up_from_postgres(self, conn, now=None) -> int:
        """Прогрев окон из ml.dataset_events: для каждого типа датчика - события за последние
        L дней до now (L из ml.window_params) + момент последнего события до окна.
        conn - DB-API соединение (psycopg 3 / psycopg2). Возвращает число прочитанных событий."""
        now = parse_ts(now) if now is not None else datetime.now()
        groups: dict[int, list[int]] = {}
        for code, days in self.ref.window_days.items():
            groups.setdefault(days, []).append(code)
        n = 0
        cur = conn.cursor()
        for days, codes in sorted(groups.items()):
            start = now - timedelta(days=days)
            cur.execute('''
                SELECT mc."ид_канала_данных",
                       (SELECT max(e."дата_время_события") FROM ml.dataset_events e
                         WHERE e."ид_канала_данных" = mc."ид_канала_данных"
                           AND e."дата_время_события" < %s)
                FROM ml.map_channel mc WHERE mc."код_типа_датчика" = ANY(%s)''', (start, codes))
            for cid, t_before in cur.fetchall():
                self.seed_last_event(cid, t_before)
            cur.execute('''
                SELECT e."ид_канала_данных", e."дата_время_события", e."тревожное_событие",
                       e."тип_значения", e."значение_число", e."значение_текст"
                FROM ml.dataset_events e
                JOIN ml.map_channel mc ON mc."ид_канала_данных" = e."ид_канала_данных"
                WHERE mc."код_типа_датчика" = ANY(%s)
                  AND e."дата_время_события" >= %s AND e."дата_время_события" < %s
                ORDER BY e."ид_канала_данных", e."дата_время_события"''', (codes, start, now))
            for cid, t, alarm, vt, num, txt in cur:
                self.process_parsed(cid, t, alarm, vt, num, txt)
                n += 1
        self.stats['warm_up_events'] += n
        return n

    def save_state(self, path) -> None:
        with open(path, 'wb') as f:
            pickle.dump({'state': self.state, 'stats': self.stats}, f)

    def load_state(self, path) -> None:
        with open(path, 'rb') as f:
            d = pickle.load(f)
        self.state, self.stats = d['state'], d['stats']

    # ---- внутреннее -----------------------------------------------------------------
    def _late(self, channel_id, ts, s):
        if self.on_late == 'raise':
            raise ValueError(f'канал {channel_id}: событие {ts} раньше уже обработанного {s.cur_t}')
        self.stats['late'] += 1
        return None

    def _features(self, ch, s: _ChannelState, ts: datetime, alarm: bool, pv: ParsedValue) -> dict:
        # новая секунда: события прошлой секунды уходят в окно
        if s.cur_t is None or ts > s.cur_t:
            for v in s.pend_v:
                s.win_v.append((s.cur_t, v))
            for d in s.pend_d:
                s.win_d.append((s.cur_t, d))
            s.pend_v.clear(); s.pend_d.clear(); s.seen.clear()
            s.prev_t, s.cur_t = s.cur_t, ts
        lo = ts - timedelta(days=self.ref.window_days[ch.sensor_code])
        for win in (s.win_v, s.win_d):
            while win and win[0][0] < lo:
                win.popleft()

        # очистка числа
        v, service = None, 0
        if pv.value_type == 'numeric':
            p = self.ref.norm.get(ch.sensor_code)
            x = None if pv.number is None else round(pv.number, 4)
            if p is not None and x is not None and p.min <= x <= p.max and x not in p.service:
                v = x
            else:
                service = 1

        log_dt = None
        if s.prev_t is not None:
            log_dt = round(math.log1p((ts - s.prev_t).total_seconds()), 6)

        z_v, low_v = None, 0
        if v is not None:
            n, mu, var = _stats(s.win_v)
            if n >= N_MIN:
                z_v = (v - mu) / math.sqrt(var + self.ref.norm[ch.sensor_code].eps)
            else:
                low_v = 1
            s.pend_v.append(v)
        z_d, low_d = None, 0
        if log_dt is not None:
            n, mu, var = _stats(s.win_d)
            if n >= N_MIN:
                z_d = (log_dt - mu) / math.sqrt(var + DT_EPS)
            else:
                low_d = 1
            s.pend_d.append(log_dt)

        text = pv.text if pv.value_type == 'text' else None
        st_code, st_tech = self.ref.state.get(text, (0, 0)) if text is not None else (0, 0)
        hour, dow, month = ts.hour, ts.weekday(), ts.month
        return {
            'дата_время_события': ts,
            'ид_канала_данных': ch.channel_id,
            'код_типа_датчика': ch.sensor_code,
            'код_объекта': ch.object_code,
            'код_комплекса': ch.complex_code,
            'объект_охранный': ch.guard_object,
            'пикет': ch.picket,
            'код_типа_значения': self.ref.value_type_code[pv.value_type],
            'код_состояния': st_code,
            'состояние_техническое': st_tech,
            'тревожное_событие': int(alarm),
            'тревожное_по_справочнику': int(self.ref.state_alarm.get((ch.sensor_type, text), False)),
            'час': hour, 'день_недели': dow, 'месяц': month,
            'значение': v,
            'служебное_значение': service,
            'значение_z': z_v,
            'мало_истории_значение': low_v,
            'лог_dt': log_dt,
            'лог_dt_z': z_d,
            'мало_истории_dt': low_d,
            'час_sin': math.sin(2 * math.pi * hour / 24), 'час_cos': math.cos(2 * math.pi * hour / 24),
            'день_недели_sin': math.sin(2 * math.pi * dow / 7), 'день_недели_cos': math.cos(2 * math.pi * dow / 7),
            'месяц_sin': math.sin(2 * math.pi * (month - 1) / 12), 'месяц_cos': math.cos(2 * math.pi * (month - 1) / 12),
        }


def featurize_stream(events: Iterable, featurizer: Optional[OnlineFeaturizer] = None):
    """Удобная обёртка: events - итерируемое (канал, время, тревожное_raw, значение_raw)."""
    fz = featurizer or OnlineFeaturizer()
    for ch, ts, alarm, raw in events:
        row = fz.process_raw(ch, ts, alarm, raw)
        if row is not None:
            yield row
