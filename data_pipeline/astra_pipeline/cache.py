"""RAM cache of the database for dataset preparation: at most half of the RAM by default.

The PostgreSQL container sizes its memory when it starts (scripts/postgres-ram-cache.sh):
of the RAM available to Docker it takes ASTRA_DB_CACHE_PERCENT (50 by default) as the
budget, gives half of the budget to its own cache (shared_buffers) and publishes the budget
as the setting astra.ram_budget_mb. The import reads it here and
  * sizes the sort memory of its workers from the other half of the budget, so that
    cleaning, features and index builds sort in RAM instead of temporary files on the SSD;
  * splits the staging journal of every year by channel, so that each cleaning task reads
    its part once and sorts it in memory;
  * processes the archive year by year (stream.py) and admits the next year only while the
    filtered events of the years in flight fit in the cache.
Against another PostgreSQL (no published budget) the server's shared_buffers and the
DATASET_* defaults are used, and the import still runs year by year.
"""
from dataclasses import dataclass, replace
import logging
import math
import os
import time

import psycopg

log = logging.getLogger("astra_pipeline")
MB = 1024 * 1024
GB = 1024 * MB

# Staging bytes per byte of the organizers' CSV, and the part of the archive the largest
# year is assumed to hold when the staging split is chosen (before the years are known).
STAGING_PER_CSV_BYTE = 1.5
LARGEST_YEAR_SHARE = 0.25
MAX_STAGING_PARTS = 64
# Bytes kept hot per staging byte of a year in flight: its clean events with their index,
# and its ML features with their index.
HOT_PER_STAGING_BYTE = 2.7


def _clamp(value, low, high):
    return max(low, min(high, int(value)))


@dataclass(frozen=True)
class CachePlan:
    budget_bytes: int    # RAM of the database for the import: cache + sort memory
    cache_bytes: int     # PostgreSQL's own cache (shared_buffers)
    published: bool      # the budget came from the container (astra.ram_budget_mb)

    @classmethod
    def from_server(cls, conn):
        budget, shared, effective = conn.execute("""
            SELECT current_setting('astra.ram_budget_mb', true),
                   pg_size_bytes(current_setting('shared_buffers')),
                   pg_size_bytes(current_setting('effective_cache_size'))""").fetchone()
        if budget:
            return cls(int(budget) * MB, int(shared), True)
        return cls(max(int(effective), int(shared)), int(shared), False)

    def size_workers(self, settings):
        """Sort memory of the workers from the budget, unless set explicitly in DATASET_*."""
        if not self.published:
            return settings
        work_area = max(self.budget_bytes - self.cache_bytes, self.budget_bytes // 4)
        changes = {}
        if not os.getenv("DATASET_WORK_MEM_MB"):
            # 3/4 of the work area for queries, ~2 sorts per worker at a time.
            changes["work_mem_mb"] = _clamp(work_area * 3 / 4 / (settings.workers * 2) / MB, 64, 1024)
        if not os.getenv("DATASET_MAINTENANCE_MEM_MB"):
            # 1/4 for index builds, at most two of them at a time.
            changes["maintenance_mem_mb"] = _clamp(work_area / 4 / 2 / MB, 256, 4096)
        return replace(settings, **changes)

    def admits(self, hot_in_flight: int, hot_year: int, years_in_flight: int) -> bool:
        """Two years always overlap (the next year is cleaned while the features of the
        current one are calculated); more only while their filtered events fit in the cache."""
        return years_in_flight < 2 or hot_in_flight + hot_year <= self.cache_bytes

    def describe(self) -> str:
        if self.published:
            return f"кэш БД в ОЗУ {self.budget_bytes / GB:.1f} ГБ"
        return f"кэш PostgreSQL {self.cache_bytes / GB:.1f} ГБ"


def staging_parts(csv_bytes: int, work_mem_mb: int) -> int:
    """Hash partitions per year of the staging journal, so that one cleaning task (one
    partition) sorts in work_mem. Chosen before loading, from the size of the journals."""
    override = os.getenv("DATASET_STAGING_PARTS")
    if override:
        return _clamp(override, 1, MAX_STAGING_PARTS)
    largest_year = csv_bytes * STAGING_PER_CSV_BYTE * LARGEST_YEAR_SHARE
    parts = largest_year / (work_mem_mb * MB / 2)
    return min(MAX_STAGING_PARTS, 1 << max(0, math.ceil(math.log2(max(parts, 1)))))


def cleaning_groups(staging_bytes: int, parts: int, years: int, settings) -> int:
    """Channel groups per staging partition: enough tasks to keep the workers busy when
    there are few years, and small enough sorts to stay in work_mem."""
    busy = math.ceil(settings.workers / max(1, years * parts))
    memory = math.ceil(staging_bytes / parts / (settings.work_mem_mb * MB / 2))
    return _clamp(max(busy, memory, 1), 1, 32)


class BuildProfile:
    """Wall time and database I/O of every stage of an import, to see where it goes.

    Cumulative server statistics are read at every stage change: shared-buffer misses
    (pages PostgreSQL had to read from the OS: page cache or SSD), the time of those reads
    (needs track_io_timing, on in the ASTRA container), temporary files of sorts that did not
    fit in memory, and WAL. They cover the whole database, so other activity is included."""

    def __init__(self, conn, progress):
        self.conn, self._progress, self.rows, self.last = conn, progress, [], None
        self.tasks = {}
        self._snap = self._snapshot()

    def _snapshot(self):
        query = """SELECT d.blks_read, d.blks_hit, d.blk_read_time, d.temp_bytes,
                          (SELECT wal_bytes FROM pg_stat_wal), {writes}
                   FROM pg_stat_database d WHERE d.datname = current_database()"""
        try:
            row = self.conn.execute(query.format(writes="""(SELECT coalesce(sum(writes + extends), 0)
                FROM pg_stat_io WHERE object = 'relation')""")).fetchone()
        except psycopg.errors.UndefinedTable:       # PostgreSQL < 16: no pg_stat_io
            row = self.conn.execute(query.format(writes="0")).fetchone()
        return (time.perf_counter(), *map(float, row))

    def progress(self, stage, counts):
        key = stage.split(":", 1)[0]
        if key != self.last:
            self._close_stage()
            self.last = key
        self._progress(stage, counts)

    def task(self, kind, seconds):
        """Time of one pipeline task, summed per kind (tasks run in parallel)."""
        self.tasks[kind] = self.tasks.get(kind, 0.0) + seconds

    def _close_stage(self):
        if self.last is None:
            self._snap = self._snapshot()
            return
        now = self._snapshot()
        t, read, hit, read_ms, temp, wal, written = (b - a for a, b in zip(self._snap, now))
        self._snap = now
        self.rows.append((self.last, round(t, 1), round(read * 8192 / MB), round(read_ms / 1000, 1),
                          round(100 * hit / (hit + read), 1) if hit + read else None,
                          round(written * 8192 / MB), round(temp / MB), round(wal / MB)))

    def save(self, conn, schema):
        self._close_stage()
        self.last = None
        conn.execute(f'''CREATE TABLE {schema}.build_profile (
            "этап" text, "секунд" real, "чтение_мимо_кэша_мб" bigint, "время_чтения_с" real,
            "попаданий_в_кэш_проц" real, "записано_мб" bigint, "временные_файлы_мб" bigint, "wal_мб" bigint)''')
        rows = self.rows + [(f"задачи: {kind} (сумма по потокам)", round(sec, 1), None, None, None, None, None, None)
                            for kind, sec in self.tasks.items()]
        with conn.cursor().copy(f"COPY {schema}.build_profile FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        for stage, sec, read, read_s, hits, written, temp, wal in self.rows:
            log.info("%s: %.1f с; чтение мимо кэша %s МБ (%s с), попаданий в кэш %s; запись %s МБ, "
                     "временные файлы %s МБ, WAL %s МБ", stage, sec, read, read_s,
                     "—" if hits is None else f"{hits}%", written, temp, wal)
        for kind, sec in self.tasks.items():
            log.info("задачи «%s»: %.1f с (сумма по потокам)", kind, sec)
