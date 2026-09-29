"""Streaming CSV adapters. Value conversion belongs to lct_features."""
import csv
import math
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from lct_features.parse import parse_alarm, parse_ts, parse_value


CHANNELS = ["ид_канала_данных", "тип_инж_системы", "тип_датчика",
            "тег_инженерной_системы", "название_датчика", "ид_объект"]
OBJECTS = ["ид_объект", "иерархия_уровень", "родитель", "вид_объекта",
           "диспетчерское_название_объекта"]
RAW = ["ид_события", "ид_канала_данных", "дата", "время", "тревожное", "значение_датчика"]
PREPARED = ["ид_события", "ид_канала_данных", "тревожное_raw", "значение_датчика_raw",
            "дата_время_события", "тип_значения", "значение_число",
            "значение_дата_время", "значение_текст"]
STATES = ["тип_датчика", "ид_набор_состояний", "название_состояния", "тревожное"]


@contextmanager
def csv_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        header = file.readline(64 * 1024)
        if not header or not header.endswith(("\n", "\r")):
            raise ValueError("CSV должен содержать строку заголовков")
        try:
            dialect = csv.Sniffer().sniff(header, delimiters=",;\t")
        except csv.Error as error:
            raise ValueError("Не удалось определить разделитель CSV") from error
        file.seek(0)
        reader = csv.DictReader(file, dialect=dialect)
        reader.fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("В CSV повторяются названия столбцов")
        yield reader


def detect_role(path: Path) -> str:
    with csv_rows(path) as reader:
        columns = set(reader.fieldnames)
    for role, required in (("channels", CHANNELS), ("objects", OBJECTS),
                           ("events", RAW), ("prepared_events", PREPARED), ("states", STATES)):
        if set(required) <= columns:
            return role
    raise ValueError("Неизвестные столбцы CSV: выберите журналы и справочники организаторов")


def prepared_event(row: dict, role: str) -> tuple:
    if None in row or any(value is None for value in row.values()):
        raise ValueError("Число полей не совпадает с заголовком")
    event_id, channel_id = int(row["ид_события"]), int(row["ид_канала_данных"])
    if role == "events":
        date = row["дата"].strip()
        if "." in date:
            date = datetime.strptime(date, "%d.%m.%Y").date().isoformat()
        ts = parse_ts(date + " " + row["время"].strip())
        alarm, raw = row["тревожное"], row["значение_датчика"]
    else:
        ts = parse_ts(row["дата_время_события"])
        alarm, raw = row["тревожное_raw"], row["значение_датчика_raw"]
    if not 2019 <= ts.year <= 2026:
        raise ValueError("Алгоритм data_pipeline поддерживает события за 2019–2026 годы")
    if str(alarm).strip().lower() not in {"t", "f", "true", "false", "1", "0"}:
        raise ValueError("Неизвестное значение признака тревожности")
    value = parse_value(raw)
    if value.number is not None and not math.isfinite(value.number):
        raise ValueError("Числовое значение должно быть конечным")
    # Reuse the exact parser even when a prepared CSV was selected.
    return (event_id, channel_id, "t" if parse_alarm(str(alarm).strip()) else "f", raw, ts,
            value.value_type, value.number, value.dt, value.text)


_ALARMS = {"t", "f", "true", "false", "1", "0"}
_CACHE_LIMIT = 1_000_000


class EventParser:
    """prepared_event for one file header: the same checks in the same order with the same
    messages, but columns are taken by position (no dict per row) and the pure parts - the
    value, the alarm flag, a dotted date - are memoised per distinct string. Journals repeat
    a few thousand states and flags millions of times."""

    def __init__(self, names: list[str], role: str):
        pos = {name: index for index, name in enumerate(names)}
        if role == "events":
            self.columns = (pos["ид_события"], pos["ид_канала_данных"], pos["дата"], pos["время"],
                            pos["тревожное"], pos["значение_датчика"])
        else:
            self.columns = (pos["ид_события"], pos["ид_канала_данных"], pos["дата_время_события"], None,
                            pos["тревожное_raw"], pos["значение_датчика_raw"])
        self.values, self.alarms, self.dates = {}, {}, {}

    def __call__(self, row: list[str]) -> tuple:
        i_id, i_channel, i_date, i_time, i_alarm, i_value = self.columns
        event_id, channel_id = int(row[i_id]), int(row[i_channel])
        if i_time is not None:
            date = row[i_date].strip()
            if "." in date:
                iso = self.dates.get(date)
                if iso is None:
                    iso = datetime.strptime(date, "%d.%m.%Y").date().isoformat()
                    self._remember(self.dates, date, iso)
                date = iso
            ts = parse_ts(date + " " + row[i_time].strip())
        else:
            ts = parse_ts(row[i_date])
        if not 2019 <= ts.year <= 2026:
            raise ValueError("Алгоритм data_pipeline поддерживает события за 2019–2026 годы")
        alarm = row[i_alarm]
        flag = self.alarms.get(alarm)
        if flag is None:
            if alarm.strip().lower() not in _ALARMS:
                raise ValueError("Неизвестное значение признака тревожности")
            flag = "t" if parse_alarm(alarm.strip()) else "f"
            self._remember(self.alarms, alarm, flag)
        raw = row[i_value]
        parsed = self.values.get(raw)
        if parsed is None:
            value = parse_value(raw)
            if value.number is not None and not math.isfinite(value.number):
                raise ValueError("Числовое значение должно быть конечным")
            parsed = (value.value_type, value.number, value.dt, value.text)
            self._remember(self.values, raw, parsed)
        return (event_id, channel_id, flag, raw, ts, *parsed)

    @staticmethod
    def _remember(cache: dict, key, value) -> None:
        if len(cache) >= _CACHE_LIMIT:
            cache.clear()
        cache[key] = value


def iter_events(path: Path, role: str):
    with csv_rows(path) as reader:
        for row in reader:
            try:
                yield prepared_event(row, role)
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError(f"{path.name}, строка {reader.line_num}: {error}") from error
