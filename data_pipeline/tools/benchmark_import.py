"""Compare canonical and optimized imports in disposable schemas, without training.

Run with backend's Python, from the repository root:
backend/.venv/bin/python data_pipeline/tools/benchmark_import.py /path/to/archive --rows 100000
"""
import argparse
import csv
from itertools import islice
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data_pipeline"))

import psycopg
from sqlalchemy import create_engine

from astra_pipeline.build import build_dataset, copy_references, run_script
from astra_pipeline.csv_input import CHANNELS, OBJECTS, csv_rows, detect_role, iter_events
from astra_pipeline.registry import schema_name


def reference_build(engine, dataset_id, files):
    """Baseline: the original sequential SQL and physical tables, unchanged."""
    schema = schema_name(dataset_id)
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        run_script(conn, "00_create_journal.sql", schema)
        latest = {}
        for file in files:
            if file["role"] in {"events", "prepared_events"}:
                with conn.cursor().copy(f"COPY {schema}.ext_journal_prepared FROM STDIN") as copy:
                    for row in iter_events(Path(file["path"]), file["role"]):
                        copy.write_row(row)
                        old = latest.get(row[1])
                        if old is None or (row[4], row[0]) > (old[4], old[0]):
                            latest[row[1]] = row
        run_script(conn, "01_reference_tables.sql", schema)
        for file in files:
            if file["role"] in {"channels", "objects"}:
                table, columns = ("ref_channels", CHANNELS) if file["role"] == "channels" else ("ref_objects", OBJECTS)
                copy_references(conn, schema, table, Path(file["path"]), columns)
        run_script(conn, "02_build_dataset.sql", schema)
        run_script(conn, "03_ml_features.sql", schema)
        conn.execute(f"CREATE TABLE {schema}.latest_sensor_events AS SELECT * FROM {schema}.ext_journal_prepared WITH NO DATA")
        with conn.cursor().copy(f"COPY {schema}.latest_sensor_events FROM STDIN") as copy:
            for row in latest.values():
                copy.write_row(row)
        conn.execute(f'CREATE UNIQUE INDEX ON {schema}.latest_sensor_events ("ид_канала_данных")')
        conn.execute(f'CREATE INDEX ON {schema}.ext_journal_prepared ("ид_канала_данных", "дата_время_события", "ид_события")')


def assert_same(conn, old, new):
    for table in ("ext_journal_prepared", "dataset_events", "dataset_ml", "v_dataset_ml",
                  "latest_sensor_events", "build_log", "map_channel"):
        difference = conn.execute(f'''
            (SELECT * FROM {old}.{table} EXCEPT ALL SELECT * FROM {new}.{table})
            UNION ALL
            (SELECT * FROM {new}.{table} EXCEPT ALL SELECT * FROM {old}.{table})
            LIMIT 1
        ''').fetchone()
        assert difference is None, (table, difference)
        # Include schema order/types, not just a count or approximate float tolerance.
        def columns(schema):
            return conn.execute('''SELECT attname, atttypid, atttypmod
                FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped
                ORDER BY attnum''', (f"{schema}.{table}",)).fetchall()
        assert columns(old) == columns(new), table


def schema_bytes(conn, schema):
    return conn.execute('''SELECT coalesce(sum(pg_total_relation_size(c.oid)),0)::bigint
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relkind='r' ''', (schema,)).fetchone()[0]


def compare(engine, files, progress=lambda *args: None):
    ids = [uuid4(), uuid4()]
    schemas = [schema_name(id) for id in ids]
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            start = perf_counter()
            reference_build(engine, ids[0], files)
            baseline = perf_counter() - start
            start = perf_counter()
            counts = build_dataset(engine, ids[1], files, progress)
            optimized = perf_counter() - start
            assert_same(conn, *schemas)
            return {"identical": True, "counts": counts,
                    "baseline_seconds": round(baseline, 3), "optimized_seconds": round(optimized, 3),
                    "baseline_bytes": schema_bytes(conn, schemas[0]),
                    "optimized_bytes": schema_bytes(conn, schemas[1])}
        finally:
            for schema in schemas:
                conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def main():
    import os
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--rows", type=int, default=100000, help="Rows per journal (first two years)")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000 or not 1 <= args.workers <= 8:
        parser.error("rows: 1–1000000; workers: 1–8")
    load_dotenv(ROOT / "backend" / ".env")
    os.environ["DATASET_BUILD_WORKERS"] = str(args.workers)
    engine = create_engine(os.environ["DATABASE_URL"])
    with TemporaryDirectory(prefix="astra-benchmark-") as directory:
        paths = []
        for name in ("справочник_каналов_датчиков.csv", "справочник_объектов_диспетчер.csv"):
            paths.append(args.archive / name)
        journals = sorted(args.archive.glob("ext-journal-*.csv"))[:2]
        if not journals:
            parser.error("No ext-journal-*.csv files found")
        for journal in journals:
            path = Path(directory) / journal.name
            with csv_rows(journal) as rows, path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, rows.fieldnames)
                writer.writeheader()
                writer.writerows(islice(rows, args.rows))
            paths.append(path)
        files = [dict(path=str(p), name=p.name, role=detect_role(p)) for p in paths]
        result = compare(engine, files, lambda stage, _: print(stage, flush=True))
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
