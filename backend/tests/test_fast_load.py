"""The SQL loader must give exactly what the Python loader gives, value by value."""
import csv
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.db.database import engine
from astra_pipeline import build
from astra_pipeline.build import build_dataset
from astra_pipeline.csv_input import CHANNELS, OBJECTS, PREPARED, RAW, prepared_event
from astra_pipeline.fast_load import NeedsPythonLoader
from astra_pipeline.registry import schema_name
from data_pipeline.tools.benchmark_import import assert_same, reference_build

URL = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)

# Everything float()/parse_value treat specially, but without quote characters.
VALUES = ["0.07", "-0.00", "1_000.5", "1e3", " 42 ", ".5", "5.", "-3276", "2.55", "327.68", "+7",
          "1E-2", "0.123456789012", "01.01.1970 03:00:00", "01.01.1970 03:00:01",
          "05.03.2026 09:11:35", "5.3.2026 09:11:35", "Норма", "Обнаружено движение", "",
          "text with trailing space ", "1.2.3", "e5", "1__0", "_1", "Infinity-like", "0x10"]
ALARMS = ["t", "f", "true", "FALSE", " t ", "1", "0"]


def write(path, columns, rows, delimiter=","):
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_NONE, escapechar=None)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def fixtures(tmp_path, delimiter=","):
    kinds = ["Газовый датчик", "Датчик температуры", "ИБП", "Датчик движения"]
    channels = [[20000 + i, "Система", kind, "тег", f"Датчик ПК{i}", 5122] for i, kind in enumerate(kinds)]
    start = datetime(2023, 12, 31, 23, 50)
    raw, prepared = [], []
    for n in range(400):
        ch = 20000 + n % len(kinds)
        ts = start + timedelta(seconds=37 * n, microseconds=(n % 3) * 250_000)
        value, alarm = VALUES[n % len(VALUES)], ALARMS[n % len(ALARMS)]
        date = ts.strftime("%d.%m.%Y") if n % 4 == 0 else ts.strftime("%-d.%-m.%Y") if n % 4 == 1 else ts.date().isoformat()
        time_text = ts.time().isoformat() if n % 5 else " " + ts.time().isoformat() + " "
        raw.append([n + 1, ch, date, time_text, alarm, value])
        if n % 7 == 0:                                          # exact duplicate
            raw.append([n + 1, ch, date, time_text, alarm, value])
    raw.append([999, 999999, "2024-01-01", "00:00:00", "f", "0.5"])  # channel not in the reference
    for row in raw[:120]:
        event = prepared_event(dict(zip(RAW, map(str, row))), "events")
        prepared.append([event[0], event[1], event[2], event[3], event[4].isoformat(sep=" "),
                         event[5], "" if event[6] is None else event[6], "", "" if event[8] is None else event[8]])
    return [
        dict(path=str(write(tmp_path / "channels.csv", CHANNELS, channels)), name="channels.csv", role="channels"),
        dict(path=str(write(tmp_path / "objects.csv", OBJECTS, [[5122, 3, 5, "controlHouse", "Объект"]])),
             name="objects.csv", role="objects"),
        dict(path=str(write(tmp_path / "events.csv", RAW, raw, delimiter)), name="events.csv", role="events"),
        dict(path=str(write(tmp_path / "prepared.csv", PREPARED, prepared, delimiter)),
             name="prepared.csv", role="prepared_events"),
    ]


def run_both(files, monkeypatch, forbid_python=True):
    if forbid_python:
        def python_loader(*args, **kwargs):
            raise AssertionError("fast loader fell back to Python")
        monkeypatch.setattr(build, "load_events_python", python_loader)
    ids = [uuid4(), uuid4()]
    with psycopg.connect(URL, autocommit=True) as conn:
        try:
            reference_build(engine, ids[0], files)
            counts = build_dataset(engine, ids[1], files, lambda *args: None)
            assert_same(conn, *map(schema_name, ids))
            return counts
        finally:
            for id in ids:
                conn.execute(f"DROP SCHEMA IF EXISTS {schema_name(id)} CASCADE")


@pytest.mark.parametrize("workers,delimiter", [(1, ","), (2, ";"), (3, "\t")])
def test_fast_loader_equals_python_loader(tmp_path, monkeypatch, workers, delimiter):
    monkeypatch.setenv("DATASET_BUILD_WORKERS", str(workers))
    monkeypatch.setattr("astra_pipeline.fast_load.MIN_CHUNK_PAGES", 1)
    monkeypatch.setattr("astra_pipeline.features.MIN_TASK_ROWS", 1)
    counts = run_both(fixtures(tmp_path, delimiter), monkeypatch)
    assert counts["orphan_rows"] == 1


def test_quotes_use_python_loader(tmp_path, monkeypatch):
    files = fixtures(tmp_path)
    path = tmp_path / "events.csv"
    path.write_text(path.read_text(encoding="utf-8-sig") + '5000,20000,2024-01-02,00:00:00,f,"a, ""quoted"" value"\n',
                    encoding="utf-8")
    calls = []
    original = build.load_events_python
    monkeypatch.setattr(build, "load_events_python", lambda *a, **k: calls.append(1) or original(*a, **k))
    run_both(files, monkeypatch, forbid_python=False)
    assert calls == [1]


@pytest.mark.parametrize("row,message", [
    ([1, 20000, "2028-01-01", "00:00:00", "f", "0.1"], "2019–2026"),
    ([1, 20000, "2024-01-01", "00:00:00", "maybe", "0.1"], "тревожности"),
    ([1, 20000, "2024-01-01", "00:00:00", "f", "nan"], "конечным"),
    ([1, 20000, "2024-01-01", "00:00:00", "f", " -Infinity"], "конечным"),
    ([1, 20000, "2024-01-01", "00:00:00", "f"], "events.csv"),
])
def test_invalid_rows_fail_and_leave_no_schema(tmp_path, row, message):
    files = fixtures(tmp_path)
    path = tmp_path / "events.csv"
    path.write_text(path.read_text(encoding="utf-8-sig") + ",".join(map(str, row)) + "\n", encoding="utf-8")
    id = uuid4()
    with pytest.raises(ValueError, match=message):
        build_dataset(engine, id, files, lambda *args: None)
    with psycopg.connect(URL, autocommit=True) as conn:
        assert not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema_name(id),)).fetchone()


def test_python_parser_agrees_on_every_value():
    """Direct check of the classification rules against lct_features.parse."""
    rows = [dict(zip(RAW, ["1", "20000", "2024-01-01", "00:00:00", "f", value])) for value in VALUES]
    expected = [prepared_event(row, "events")[5:] for row in rows]
    with psycopg.connect(URL, autocommit=True) as conn:
        schema = "t_" + uuid4().hex
        conn.execute(f"CREATE SCHEMA {schema}")
        try:
            from astra_pipeline.fast_load import create_helpers, transform_sql
            from pathlib import Path
            create_helpers(conn, schema)
            conn.execute(f"CREATE TABLE {schema}.st ({', '.join(f'c{i} text' for i in range(6))})")
            with conn.cursor().copy(f"COPY {schema}.st FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(list(row.values()))
            got = conn.execute(transform_sql(schema, "st", RAW, "events", Path("x")),
                               ("(0,0)", "(1000,0)")).fetchall()
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
    for value, want, have in zip(VALUES, expected, got):
        number = None if have[6] is None else float(have[6])
        assert (have[5], number, have[7], have[8]) == want, value


def test_needs_python_loader_is_raised_for_blank_lines(tmp_path):
    files = fixtures(tmp_path)
    path = tmp_path / "events.csv"
    path.write_text(path.read_text(encoding="utf-8-sig").replace("\n", "\n\n", 1), encoding="utf-8")
    from astra_pipeline.fast_load import copy_file_to_staging
    from pathlib import Path
    with psycopg.connect(URL, autocommit=True) as conn:
        schema = "t_" + uuid4().hex
        conn.execute(f"CREATE SCHEMA {schema}")
        try:
            with pytest.raises(NeedsPythonLoader):
                copy_file_to_staging(conn, schema, "st", Path(path), lambda *a: None, {}, "x")
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
