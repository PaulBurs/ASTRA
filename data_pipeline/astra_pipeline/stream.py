"""Year-by-year preparation: filtered events are used while they are still in RAM.

The former order made passes over the whole archive: clean every year, index all of
event_storage, then compute the features of every year. On the full archive (~100 GB of
tables, indexes and WAL) each later pass read back from the SSD what the previous one had
written, because the archive does not fit in memory.

Here every year goes clean -> seal (count, index, analyze) -> features -> index of the
features while its filtered events are in the database cache. Years overlap: the next year
is cleaned while the features of the current one are calculated. A year is admitted only
while the years in flight fit in the cache (CachePlan.admits), so the cache holds the years
being worked on instead of whatever was touched last.

The statements are those of the canonical build, on the same rows; only their order changes.
The features of a year look back into earlier years (the L-day buffer and the last event
before it), so they start only when that year and every earlier one are sealed.
"""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
import heapq
import itertools
import time

from .compact import clean_query, seal_year, staging_bytes
from .features import calculate, finish_year, year_tasks
from .parallel import WorkerPool
from .cache import HOT_PER_STAGING_BYTE, cleaning_groups

# When a worker is free: sealing unblocks the features of its year, the index of a finished
# year frees its place in the cache, cleaning keeps the next year ready, features fill the rest.
SEAL, ML_INDEX, CLEAN, FEATURES = range(4)
KINDS = {SEAL: "индекс и статистика событий", ML_INDEX: "запись и индекс ML-признаков",
         CLEAN: "очистка", FEATURES: "ML-признаки"}


class YearPipeline:
    def __init__(self, conn, schema, settings, plan, years, parts, channels, blocks, codes,
                 ml_index, unlogged, progress, counts, profile=None):
        self.schema, self.settings, self.plan = schema, settings, plan
        self.years, self.parts, self.channels = sorted(years), parts, channels
        self.blocks, self.codes = blocks, codes
        # Index columns of dataset_ml and whether its partitions are filled without WAL.
        self.ml_index, self.unlogged = ml_index, unlogged
        self.progress, self.counts, self.profile = progress, counts, profile
        staged = {year: staging_bytes(conn, schema, year) for year in self.years}
        # Bytes a year keeps in the cache while in flight, and its cleaning tasks per part.
        self.hot = {year: int(staged[year] * HOT_PER_STAGING_BYTE) for year in self.years}
        self.groups = {year: cleaning_groups(staged[year], parts, len(self.years), settings)
                       for year in self.years}
        self.waiting = deque(self.years)
        self.in_flight = {}                 # year -> hot bytes, from admission until done
        self.left = {}                      # (kind, year) -> tasks still to finish
        self.sealed, self.released, self.done = set(), set(), set()
        self.inventory, self.feature_rows = {}, 0
        self.ready, self.order = [], itertools.count()

    # ---- scheduling (runs on the caller's thread only) ------------------------------------
    def _add(self, kind, year, task, rank=0):
        heapq.heappush(self.ready, (kind, year, rank, next(self.order), task))
        self.left[kind, year] = self.left.get((kind, year), 0) + 1

    def _admit(self):
        while self.waiting and self.plan.admits(sum(self.in_flight.values()), self.hot[self.waiting[0]],
                                                len(self.in_flight)):
            year = self.waiting.popleft()
            self.in_flight[year] = self.hot[year]
            groups = self.groups[year]
            for part in range(self.parts):
                for group in range(groups):
                    self._add(CLEAN, year, (year, part, group, groups))

    def _release_features(self):
        for year in self.years:
            if year in self.released:
                continue
            if any(y not in self.sealed for y in self.years if y <= year):
                break                        # later years wait for this one too
            self.released.add(year)
            tasks = year_tasks(self.blocks, year, self.inventory[year], self.codes, self.settings.workers)
            for rows, block, batch in tasks:
                self._add(FEATURES, year, (block, batch), -rows)
            if not tasks:
                self._finish_year(year)

    def _finish_year(self, year):
        if self.unlogged or (self.ml_index and self.inventory.get(year)):
            self._add(ML_INDEX, year, year)
        else:
            self._year_done(year)

    def _year_done(self, year):
        self.done.add(year)
        del self.in_flight[year]

    def _completed(self, kind, year, result):
        self.left[kind, year] -= 1
        if kind == FEATURES:
            self.feature_rows += result
        elif kind == SEAL:
            self.inventory[year] = result
            self.sealed.add(year)
            self._release_features()
        if self.left[kind, year]:
            return
        if kind == CLEAN:
            self._add(SEAL, year, year)
        elif kind == FEATURES:
            self._finish_year(year)
        elif kind == ML_INDEX:
            self._year_done(year)
        self._admit()

    def _report(self):
        cleaned = len(self.sealed)
        self.progress(f"Очистка и ML-признаки по годам ({self.plan.describe()}): очищено {cleaned} из "
                      f"{len(self.years)} лет, признаки готовы за {len(self.done)} из {len(self.years)} лет",
                      self.counts)

    # ---- tasks (run on worker sessions) ----------------------------------------------------
    def _work(self, conn, item):
        kind, task, spare = item
        started = time.perf_counter()
        if kind == CLEAN:
            year, part, group, groups = task
            result = conn.execute(clean_query(self.schema, year, self.parts, part, groups, group)).rowcount
        elif kind == SEAL:
            result = seal_year(conn, self.schema, task, self.channels, self.settings, spare)
        elif kind == FEATURES:
            result = calculate(conn, self.schema, *task)
        else:
            result = finish_year(conn, self.schema, task, self.ml_index, self.unlogged, self.settings, spare)
        return result, time.perf_counter() - started

    def run(self, url):
        """-> (clean events per year and channel, feature rows)."""
        self._admit()
        self._report()
        with WorkerPool(url, self.settings) as pool:
            running = {}
            while self.ready or running:
                while self.ready and len(running) < self.settings.workers:
                    kind, year, _, _, task = heapq.heappop(self.ready)
                    # An index build borrows the workers nobody needs (the last year, one year).
                    spare = 0 if self.ready else min(4, self.settings.workers - len(running) - 1)
                    running[pool.submit(self._work, (kind, task, spare))] = (kind, year)
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    kind, year = running.pop(future)
                    result, seconds = future.result()
                    if self.profile:
                        self.profile.task(KINDS[kind], seconds)
                    self._completed(kind, year, result)
                self._report()
        if len(self.done) != len(self.years):
            raise RuntimeError("Подготовка по годам завершилась не для всех лет")
        return self.inventory, self.feature_rows
