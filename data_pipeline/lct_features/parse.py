"""Разбор сырого значения датчика СМВУ (строка) на типизированные поля.

Правила восстановлены по подготовленному журналу организаторов и совпадают с ним
на всех 313 545 997 строках (единственное отличие: '-0.00' -> 0.0, значение то же).

    '01.01.1970 03:00:00' / '...:01'  -> binary,   число 0 / 1  (по QA: сбитая дата, трактовать как неисправность)
    'ДД.ММ.ГГГГ чч:мм:сс'             -> datetime, дата-время
    число ('0.07', '-3276', '21')     -> numeric,  число
    всё остальное                     -> text,     строка как есть ('Обнаружено движение')
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

_BINARY = {'01.01.1970 03:00:00': 0.0, '01.01.1970 03:00:01': 1.0}
_DT = re.compile(r'^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2})$')


@dataclass(frozen=True)
class ParsedValue:
    value_type: str                  # 'binary' | 'datetime' | 'numeric' | 'text'
    number: Optional[float] = None   # для numeric и binary
    dt: Optional[datetime] = None    # для datetime
    text: Optional[str] = None       # для text


def parse_value(raw: str) -> ParsedValue:
    if raw in _BINARY:
        return ParsedValue('binary', number=_BINARY[raw])
    m = _DT.match(raw)
    if m:
        d, mo, y, h, mi, s = map(int, m.groups())
        return ParsedValue('datetime', dt=datetime(y, mo, d, h, mi, s))
    try:
        return ParsedValue('numeric', number=float(raw))
    except ValueError:
        return ParsedValue('text', text=raw)


def parse_alarm(raw_flag) -> bool:
    """тревожное_raw: 't' / 'f' (также принимает bool, 'true'/'false', 1/0)."""
    if isinstance(raw_flag, bool):
        return raw_flag
    return str(raw_flag).strip().lower() in ('t', 'true', '1')


def parse_ts(ts) -> datetime:
    """'ГГГГ-ММ-ДД чч:мм:сс' или datetime -> datetime без часового пояса (время СМВУ как есть)."""
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    return datetime.fromisoformat(str(ts).strip())
