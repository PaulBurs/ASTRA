"""Bounded SQL workers. A failed import must finish/cancel workers before cleanup."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from threading import Event, Lock

import psycopg


def default_workers() -> int:
    # Half of the hardware threads: SQL workers and PostgreSQL share one machine.
    return max(2, min(8, (os.cpu_count() or 4) // 2))


@dataclass(frozen=True)
class BuildSettings:
    workers: int = 2
    work_mem_mb: int = 64
    maintenance_mem_mb: int = 1024

    @classmethod
    def from_env(cls):
        workers = int(os.getenv("DATASET_BUILD_WORKERS") or default_workers())
        memory = int(os.getenv("DATASET_WORK_MEM_MB", "128"))
        maintenance = int(os.getenv("DATASET_MAINTENANCE_MEM_MB", "1024"))
        if not 1 <= workers <= 32 or not 16 <= memory <= 1024 or not 64 <= maintenance <= 16384:
            raise ValueError("DATASET_BUILD_WORKERS: 1–32; DATASET_WORK_MEM_MB: 16–1024; "
                             "DATASET_MAINTENANCE_MEM_MB: 64–16384")
        return cls(workers, memory, maintenance)

    def configure(self, conn):
        conn.execute(f"SET work_mem = '{self.work_mem_mb}MB'")
        conn.execute("SET maintenance_work_mem = '128MB'")
        # Parallelize independent channels/years, not each sort inside every worker.
        conn.execute("SET max_parallel_workers_per_gather = 0")
        conn.execute("SET max_parallel_maintenance_workers = 0")
        conn.execute("SET jit = off")

    def configure_indexing(self, conn):
        """Index builds run alone on the main connection: give them memory and parallel workers."""
        conn.execute(f"SET maintenance_work_mem = '{self.maintenance_mem_mb}MB'")
        conn.execute(f"SET max_parallel_maintenance_workers = {min(4, self.workers)}")


def set_autovacuum(conn, schema: str, enabled: bool) -> None:
    """Autovacuum of tables that the import is still filling only competes for the disk:
    the import runs ANALYZE itself. It is switched off while building and on at the end."""
    tables = conn.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = %s AND c.relkind = 'r'""", (schema,)).fetchall()
    for (table,) in tables:
        conn.execute(f'ALTER TABLE {schema}."{table}" SET (autovacuum_enabled = {str(enabled).lower()})')


def run_jobs(url, settings, jobs, work, completed):
    """`completed` runs on the caller, so progress and counters have one writer."""
    stopped, lock, connections = Event(), Lock(), set()

    def run(job):
        with psycopg.connect(url, autocommit=True, application_name="astra-import") as conn:
            with lock:
                if stopped.is_set():
                    return None
                connections.add(conn)
            try:
                settings.configure(conn)
                if stopped.is_set():
                    return None
                return work(conn, job)
            finally:
                with lock:
                    connections.remove(conn)

    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        try:
            for future in as_completed(futures):
                completed(future.result())
        except BaseException:
            stopped.set()
            for future in futures:
                future.cancel()
            with lock:
                for conn in connections:
                    try:
                        conn.cancel()
                    except psycopg.Error:
                        # Preserve the original error if the failed connection
                        # also became unavailable while cancelling its siblings.
                        pass
            # Executor waits for all SQL sessions to close before schema cleanup.
            raise
