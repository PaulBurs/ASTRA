"""CPU inference workers: independent Python interpreters with bounded memory.

LightGBM scoring is tiny; pandas feature preparation benefits from processes.
Spawn avoids forking an initialized OpenMP runtime or SQLAlchemy connection pool.
"""
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from threading import BoundedSemaphore, Lock

WORKERS = max(1, min(16, int(os.getenv('ML_FORECAST_WORKERS', '4'))))
_slots = BoundedSemaphore(WORKERS)
_lock = Lock()
_pool = None


def _initialize():
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'


def _execute(dataset_id, sensor_ids, single):
    from ml.src.inference import predict_prepared_batch, predict_prepared_dataset
    if single:
        return predict_prepared_dataset(dataset_id, sensor_ids[0])
    return predict_prepared_batch(dataset_id, sensor_ids)


def run_prediction(dataset_id, sensor_ids, *, single=False):
    global _pool
    with _slots:
        with _lock:
            if _pool is None:
                _pool = ProcessPoolExecutor(max_workers=WORKERS, mp_context=get_context('spawn'),
                                            initializer=_initialize)
            pool = _pool
        try:
            return pool.submit(_execute, dataset_id, sensor_ids, single).result()
        except BrokenProcessPool:
            # A killed worker must not poison all future retries until restart.
            with _lock:
                if _pool is pool:
                    _pool = None
            pool.shutdown(wait=False, cancel_futures=True)
            raise


def shutdown_workers():
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
