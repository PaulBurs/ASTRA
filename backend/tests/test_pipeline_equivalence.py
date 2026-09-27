"""Exact SQL equivalence: all windows, year edges, peers, duplicates and NULLs."""
import csv
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from app.db.database import engine
from app.repositories.prepared_dataset_repository import PreparedMLDataRepository, PreparedSensorRepository
from astra_pipeline.build import SQL_ROOT, build_dataset
from astra_pipeline.csv_input import CHANNELS, OBJECTS, RAW
from astra_pipeline.features import feature_plan
from astra_pipeline.parallel import BuildSettings, run_jobs
from astra_pipeline.registry import schema_name
from data_pipeline.tools.benchmark_import import assert_same, reference_build


def fixtures(tmp_path):
    with (SQL_ROOT.parent / "lct_features/dicts/map_sensor_type.csv").open(encoding="utf-8-sig") as file:
        types = [row["тип_датчика"] for row in csv.DictReader(file)]
    channels, events = [], []
    # Several channels per type exercise disjoint channel batches, including a
    # long gap requiring the last event before the previous-year buffer.
    dates = [datetime(2019, 1, 1), datetime(2020, 1, 1), datetime(2021, 12, 31)]
    edge = datetime(2024, 1, 1)
    for days in (1, 7, 30, 90):
        dates.extend([edge - timedelta(days=days, microseconds=1), edge - timedelta(days=days),
                      edge - timedelta(days=days) + timedelta(microseconds=1)])
    dates += [edge - timedelta(seconds=1), edge, edge + timedelta(microseconds=1)]
    dates += [edge + timedelta(minutes=i) for i in range(1, 12)]
    dates += [datetime(2026, 12, 31, 23, 59, 59)]
    values = ["0.123456", "2.55", "-3276", "100", "0.5", "12.34", "Норма",
              "01.01.1970 03:00:01", "05.03.2026 09:11:35", "Неизвестное; состояние\nс кавычкой \"", ""]
    for index, kind in enumerate(types):
        for n in range(2):
            ch = 10000 + index * 2 + n
            channels.append([ch, "Система", kind, "тег", f"Датчик ПК{index}", 5122])
            for i, ts in enumerate(dates):
                events.append([len(events) + 1, ch, ts.date(), ts.time(), "t" if i % 3 == 0 else "f", values[i % len(values)]])
            # Same time, different values/alarm must survive; exact duplicates must not.
            events.extend([[len(events) + 1, ch, edge.date(), edge.time(), "f", "0.02"],
                           [len(events) + 2, ch, edge.date(), edge.time(), "t", "0.03"]])
            events.append([len(events) + 1, *events[-1][1:]])
    events.append([999999, 999999, edge.date(), edge.time(), "f", "0.5"])
    files = []
    for name, columns, rows, role in [
        ("channels", CHANNELS, channels, "channels"),
        ("objects", OBJECTS, [[5122, 3, 5, "controlHouse", "Объект"]], "objects"),
        ("events", RAW, list(reversed(events)), "events"),
    ]:
        path = tmp_path / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(columns)
            writer.writerows(rows)
        files.append(dict(path=str(path), name=path.name, role=role))
    return files


@pytest.mark.parametrize("workers", [1, 2])
def test_exact_equivalence(tmp_path, monkeypatch, workers):
    monkeypatch.setenv("DATASET_BUILD_WORKERS", str(workers))
    monkeypatch.setattr("astra_pipeline.features.MIN_TASK_ROWS", 1)
    files = fixtures(tmp_path)
    ids = [uuid4(), uuid4()]
    schemas = [schema_name(id) for id in ids]
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            reference_build(engine, ids[0], files)
            counts = build_dataset(engine, ids[1], files, lambda *args: None)
            assert_same(conn, *schemas)
            assert counts["orphan_rows"] == 1
            assert counts["duplicate_rows"] == 38
            assert counts["event_rows"] == counts["feature_rows"]
            # Exercise the existing frontend adapters against both layouts.
            assert PreparedSensorRepository(engine, ids[0]).get_all() == PreparedSensorRepository(engine, ids[1]).get_all()
            histories = [PreparedMLDataRepository(engine, id).get_events(
                10002, datetime(2019, 1, 1), datetime(2027, 1, 1)) for id in ids]
            assert histories[0] == histories[1]
            assert conn.execute('''SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relpersistence='u' ''', (schemas[1],)).fetchone()[0] == 0
        finally:
            for schema in schemas:
                conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def test_parallel_failure_closes_workers():
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    barrier, connections = Barrier(2), []

    def work(conn, fail):
        connections.append(conn)
        barrier.wait(timeout=10)
        if fail:
            raise ValueError("test worker failure")
        conn.execute("SELECT pg_sleep(0.1)")
        return 1

    with pytest.raises(ValueError, match="test worker failure"):
        run_jobs(url, BuildSettings(), [True, False], work, lambda *args: None)
    assert len(connections) == 2
    assert all(conn.closed for conn in connections)


def test_changed_sql_plan_fails_closed():
    script = (SQL_ROOT / "03_ml_features.sql").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        feature_plan(script.replace('DELETE FROM ml.dataset_ml_2019', 'DELETE FROM ml.dataset_ml_2020', 1))
