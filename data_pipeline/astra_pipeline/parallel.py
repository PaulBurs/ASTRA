"""Bounded SQL workers. A failed import must finish/cancel workers before cleanup."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from threading import Event, Lock

import psycopg


@dataclass(frozen=True)
class BuildSettings:
    workers: int = 2
    work_mem_mb: int = 64

    @classmethod
    def from_env(cls):
        value = os.getenv("DATASET_BUILD_WORKERS", "auto").strip().lower()
        workers = auto_workers() if value in {"", "auto"} else int(value)
        memory = int(os.getenv("DATASET_WORK_MEM_MB", "64"))
        if not 1 <= workers <= 8 or not 16 <= memory <= 256:
            raise ValueError("DATASET_BUILD_WORKERS: 1–8; DATASET_WORK_MEM_MB: 16–256")
        return cls(workers, memory)

    def configure(self, conn):
        conn.execute(f"SET work_mem = '{self.work_mem_mb}MB'")
        conn.execute("SET maintenance_work_mem = '128MB'")
        # Parallelize independent channels/years, not each sort inside every worker.
        conn.execute("SET max_parallel_workers_per_gather = 0")
        conn.execute("SET max_parallel_maintenance_workers = 0")
        conn.execute("SET jit = off")


def auto_workers() -> int:
    """Default parallelism: every worker is one busy PostgreSQL backend. Use half of the
    logical CPUs (the rest stays for the app, ML service and PostgreSQL itself), at most
    6, and keep about 3 GB of RAM per worker for sorts and window buffers."""
    cpus = os.cpu_count() or 2
    try:
        memory_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        memory_gb = 8
    return max(1, min(6, cpus // 2, int(memory_gb // 3)))


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
