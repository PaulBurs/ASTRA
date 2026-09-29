"""RAM cache of the database: sizing, year-by-year order, identical results."""
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4

import psycopg
import pytest

from app.db.database import engine
from astra_pipeline import stream
from astra_pipeline.build import build_dataset
from astra_pipeline.cache import GB, MB, CachePlan, cleaning_groups, staging_parts
from astra_pipeline.parallel import BuildSettings
from astra_pipeline.registry import schema_name
from data_pipeline.tools.benchmark_import import assert_same, reference_build
from tests.test_pipeline_equivalence import fixtures

URL = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "postgres-ram-cache.sh"
# The backend image (./astra.sh check) contains backend/ only, not the repository's scripts/.
needs_script = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not in this image")


def test_budget_sizes_worker_memory(monkeypatch):
    monkeypatch.delenv("DATASET_WORK_MEM_MB", raising=False)
    monkeypatch.delenv("DATASET_MAINTENANCE_MEM_MB", raising=False)
    plan = CachePlan(32 * GB, 16 * GB, True)            # 64 GB computer, half for the database
    sized = plan.size_workers(BuildSettings(8, 128, 1024))
    assert (sized.workers, sized.work_mem_mb, sized.maintenance_mem_mb) == (8, 768, 2048)
    monkeypatch.setenv("DATASET_WORK_MEM_MB", "200")     # explicit values win
    assert plan.size_workers(BuildSettings(8, 200, 1024)).work_mem_mb == 200
    unknown = CachePlan(4 * GB, 128 * MB, False)         # another PostgreSQL: nothing changes
    assert unknown.size_workers(BuildSettings(8, 128, 1024)) == BuildSettings(8, 128, 1024)


def test_staging_split_and_cleaning_groups(monkeypatch):
    monkeypatch.delenv("DATASET_STAGING_PARTS", raising=False)
    # The organizers' 22.5 GB journal: 32 channel parts per year, one sort per part.
    assert staging_parts(22_524_077_063, 768) == 32
    assert staging_parts(10_000_000, 128) == 1
    settings = BuildSettings(8, 768, 2048)
    assert cleaning_groups(5_600 * MB, 32, 8, settings) == 1
    assert cleaning_groups(100 * MB, 1, 1, settings) == 8          # one small year: 8 busy workers
    assert cleaning_groups(30 * GB, 32, 1, settings) == 3          # bigger than assumed: sorts stay in RAM


def test_admission_keeps_two_years_and_the_cache_limit():
    plan = CachePlan(8 * GB, 4 * GB, True)
    assert plan.admits(0, 10 * GB, 0) and plan.admits(10 * GB, 10 * GB, 1)
    assert plan.admits(1 * GB, 2 * GB, 2)
    assert not plan.admits(3 * GB, 2 * GB, 2)


@pytest.mark.parametrize("workers,without_wal", [(1, False), (3, True)])
def test_years_in_ram_order_and_same_result(tmp_path, monkeypatch, workers, without_wal):
    monkeypatch.setenv("DATASET_BUILD_WORKERS", str(workers))
    monkeypatch.setenv("DATASET_STAGING_PARTS", "4")
    monkeypatch.setattr("astra_pipeline.features.MIN_TASK_ROWS", 1)
    # A published budget that holds nothing: only the minimal two years are in flight.
    monkeypatch.setattr(CachePlan, "from_server", classmethod(lambda cls, conn: cls(64 * MB, 1, True)))
    monkeypatch.setattr("astra_pipeline.build.without_wal", lambda conn: without_wal)
    events, lock = [], threading.Lock()
    original = stream.YearPipeline._work

    def work(self, conn, item):
        kind, task, _ = item
        year = task[0] if kind == stream.CLEAN else task[0].year if kind == stream.FEATURES else task
        started = time.monotonic()
        result = original(self, conn, item)
        with lock:
            events.append((kind, year, started, time.monotonic()))
        return result

    monkeypatch.setattr(stream.YearPipeline, "_work", work)
    files = fixtures(tmp_path)
    ids = [uuid4(), uuid4()]
    schemas = [schema_name(id) for id in ids]
    with psycopg.connect(URL, autocommit=True) as conn:
        try:
            reference_build(engine, ids[0], files)
            counts = build_dataset(engine, ids[1], files, lambda *args: None)
            assert_same(conn, *schemas)
            assert counts["event_rows"] == counts["feature_rows"]
            stages = [r[0] for r in conn.execute(f'SELECT "этап" FROM {schemas[1]}.build_profile')]
            assert any(stage.startswith("Очистка и ML-признаки по годам") for stage in stages)
            assert conn.execute('''SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relpersistence='u' ''', (schemas[1],)).fetchone()[0] == 0
            # The yearly indexes became the partitions of the canonical indexes, not extra ones.
            assert conn.execute('''SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname LIKE 'dataset_ml_20%%' ''', (schemas[1],)).fetchone()[0] == 8
        finally:
            for schema in schemas:
                conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

    years = sorted({year for kind, year, *_ in events})
    first = {kind: {} for kind in range(4)}
    last = {kind: {} for kind in range(4)}
    done_at = {}                                  # a year is done after its last task
    for kind, year, started, ended in events:
        first[kind][year] = min(started, first[kind].get(year, started))
        last[kind][year] = max(ended, last[kind].get(year, ended))
        done_at[year] = max(ended, done_at.get(year, ended))
    for year in years:
        # Features look back into earlier years: those must be cleaned, indexed and analyzed.
        if year in first[stream.FEATURES]:
            assert first[stream.FEATURES][year] >= max(last[stream.SEAL][y] for y in years if y <= year)
    for i, year in enumerate(years[2:], start=2):
        # Only two years in flight: a year starts after all but one earlier year are done.
        done = sum(1 for y in years[:i] if done_at[y] <= first[stream.CLEAN][year])
        assert done >= i - 1, year


def test_failed_task_stops_the_pipeline_and_drops_the_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASET_BUILD_WORKERS", "2")
    monkeypatch.setattr("astra_pipeline.features.MIN_TASK_ROWS", 1)
    calls = []

    def failing(*args):
        calls.append(1)
        if len(calls) == 3:
            raise ValueError("test feature failure")
        return 0

    monkeypatch.setattr(stream, "calculate", failing)
    id = uuid4()
    with pytest.raises(ValueError, match="test feature failure"):
        build_dataset(engine, id, fixtures(tmp_path), lambda *args: None)
    with psycopg.connect(URL, autocommit=True) as conn:
        assert not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema_name(id),)).fetchone()
        for _ in range(50):                  # sessions were closed; their backends exit shortly
            if not conn.execute("SELECT 1 FROM pg_stat_activity WHERE application_name='astra-import'").fetchone():
                break
            time.sleep(0.1)
        else:
            raise AssertionError("import sessions still open")


def run_script(tmp_path, mem_kb, *args, limit=None, **env):
    (tmp_path / "bin").mkdir(exist_ok=True)
    entry = tmp_path / "bin" / "docker-entrypoint.sh"
    entry.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    entry.chmod(0o755)
    (tmp_path / "meminfo").write_text(f"MemTotal:       {mem_kb} kB\nMemFree:  1 kB\n")
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir(exist_ok=True)
    (cgroup / "memory.max").write_text(f"{limit if limit is not None else 'max'}\n")
    result = subprocess.run(
        ["sh", str(SCRIPT), *args], capture_output=True, text=True,
        env={"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "ASTRA_MEMINFO": str(tmp_path / "meminfo"),
             "ASTRA_CGROUP_ROOT": str(cgroup), **env})
    return result.returncode, result.stdout.split("\n"), result.stderr


@needs_script
def test_container_takes_half_of_the_ram(tmp_path):
    code, argv, log = run_script(tmp_path, 64 * 1024 * 1024, "postgres")
    assert code == 0 and argv[0] == "postgres" and argv.count("postgres") == 1
    for setting in ("shared_buffers=16384MB", "effective_cache_size=32768MB", "astra.ram_budget_mb=32768",
                    "wal_level=minimal", "max_wal_senders=0", "track_io_timing=on"):
        assert setting in argv, setting
    assert "32768 МБ" in log


@needs_script
def test_container_limit_fixed_budget_and_replica(tmp_path):
    _, argv, _ = run_script(tmp_path, 64 * 1024 * 1024, "postgres", limit=8 * 1024**3)
    assert "astra.ram_budget_mb=4096" in argv                       # the container may use only 8 GB
    _, argv, _ = run_script(tmp_path, 64 * 1024 * 1024, "postgres", "-c", "log_min_messages=info",
                            ASTRA_DB_CACHE_MB="20000", ASTRA_DB_WAL_LEVEL="replica")
    assert "shared_buffers=10000MB" in argv and "wal_level=replica" in argv
    assert "max_wal_senders=0" not in argv and "log_min_messages=info" in argv
    _, argv, _ = run_script(tmp_path, 8 * 1024 * 1024, ASTRA_DB_CACHE_PERCENT="99")
    assert "astra.ram_budget_mb=7372" in argv                       # never more than 90%
    _, argv, _ = run_script(tmp_path, 64 * 1024 * 1024, ASTRA_DB_CACHE_PERCENT="08")
    assert "astra.ram_budget_mb=5242" in argv                       # decimal, not octal


@needs_script
def test_other_commands_are_not_given_cache_settings(tmp_path):
    for args in (["psql", "-h", "postgres"], ["postgres", "--version"], ["bash"]):
        code, argv, log = run_script(tmp_path, 8 * 1024 * 1024, *args)
        assert code == 0 and argv[:len(args)] == args and "shared_buffers" not in " ".join(argv), args
        assert not log


@needs_script
@pytest.mark.parametrize("env", [{"ASTRA_DB_CACHE_PERCENT": "5o"}, {"ASTRA_DB_CACHE_MB": "1g"},
                                 {"ASTRA_DB_WAL_LEVEL": "none"}])
def test_invalid_cache_settings_fail(tmp_path, env):
    code, _, log = run_script(tmp_path, 8 * 1024 * 1024, **env)
    assert code == 1 and "ASTRA" in log
