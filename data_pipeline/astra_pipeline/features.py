"""Execute the canonical ML SQL in independent, bounded channel/year tasks.

Do not reimplement the formulas: extract the INSERTs from the team's versioned
script. Splitting by entire channels preserves window history and timestamp peers.
"""
from dataclasses import dataclass
import re

from .parallel import run_jobs

MIN_TASK_ROWS = 100_000


@dataclass(frozen=True)
class FeatureBlock:
    year: int
    codes: tuple
    query: str


def feature_plan(script):
    setup, rest = script.split("-- ===== 2019 ", 1)
    inserts, finish = rest.split("-- 4. Индекс, статистика, представление", 1)
    # Fail closed if the canonical format changes; never silently omit a block.
    matches = list(re.finditer(
        r'DELETE FROM ml.dataset_ml_(\d{4}) WHERE "код_типа_датчика" IN \(([\d, ]+)\);'
        r'\s*(INSERT INTO ml.dataset_ml_\d{4}\nWITH src AS \(.*?'
        r"WHERE c.t >= TIMESTAMP '\d{4}-01-01';)", inserts, re.S))
    expected = [(year, codes) for year in range(2019, 2027) for codes in
                [(2, 3, 13), (9, 11, 14, 15, 16, 17), (6, 8, 18, 19), (1, 4, 5, 7, 10, 12)]]
    blocks = [FeatureBlock(int(m[1]), tuple(map(int, m[2].split(","))), m[3]) for m in matches]
    if ([(b.year, b.codes) for b in blocks] != expected
            or inserts.count("INSERT INTO ml.dataset_ml_") != len(blocks)
            or any(not b.query.startswith(f"INSERT INTO ml.dataset_ml_{b.year}\n")
                   or not b.query.endswith(f"WHERE c.t >= TIMESTAMP '{b.year}-01-01';")
                   for b in blocks)):
        raise ValueError("Изменился формат 03_ml_features.sql: обновите план параллельного расчёта")
    # Worker memory is configured explicitly, not multiplied by the script defaults.
    setup = re.sub(r"^SET .*?;\s*$", "", setup, flags=re.M)
    # Keep indexes and v_dataset_ml; omit interactive reports discarded by the app.
    finish = finish.split("-- 5. Контроль", 1)[0]
    finish = finish[finish.index("CREATE INDEX"):]
    return setup, blocks, finish


def channel_batches(channel_counts, workers):
    count = min(workers, max(1, sum(channel_counts.values()) // MIN_TASK_ROWS))
    batches, weights = [[] for _ in range(count)], [0] * count
    for channel, rows in sorted(channel_counts.items(), key=lambda item: (-item[1], item[0])):
        target = min(range(count), key=lambda i: weights[i])
        batches[target].append(channel)
        weights[target] += rows
    return [batch for batch in batches if batch]


def build_features(conn, url, schema, settings, inventory, script, execute, progress, counts):
    setup, blocks, finish = feature_plan(script)
    execute(conn, setup, schema)
    settings.configure(conn)
    conn.execute(f"ANALYZE {schema}.map_channel")
    codes = dict(conn.execute(f'SELECT "ид_канала_данных", "код_типа_датчика" FROM {schema}.map_channel'))
    jobs = []
    for block in blocks:
        channels = {ch: n for ch, n in inventory.get(block.year, {}).items() if codes.get(ch) in block.codes}
        for batch in channel_batches(channels, settings.workers):
            jobs.append((block, batch))
    done, total_rows = 0, 0

    def calculate(worker, job):
        block, batch = job
        # Both src and lookback use the same complete channels. Retain the original
        # L-day buffer, last event before the buffer, microsecond bounds and math.
        query = block.query.replace('WHERE e."тип_датчика" IN',
                                    'WHERE e."ид_канала_данных" = ANY(%s) AND e."тип_датчика" IN')
        query = query.replace('WHERE mc."код_типа_датчика" IN',
                              'WHERE mc."ид_канала_данных" = ANY(%s) AND mc."код_типа_датчика" IN')
        # The same kept rows, without label joins in the scalar MAX lookup. This
        # lets PostgreSQL find the previous event through a backward index scan.
        query = query.replace("FROM ml.dataset_events z", "FROM ml.event_storage z")
        query = query.replace('WHERE z."ид_канала_данных"', 'WHERE z.is_clean AND z."ид_канала_данных"')
        query = query.replace("ml.", f"{schema}.")
        return worker.execute(query, (batch, batch)).rowcount

    def finished(rows):
        nonlocal done, total_rows
        done += 1
        total_rows += rows
        progress(f"Расчёт ML-признаков: {done} из {len(jobs)} блоков", counts)

    progress(f"Расчёт ML-признаков: 0 из {len(jobs)} блоков", counts)
    run_jobs(url, settings, jobs, calculate, finished)
    progress("Индексирование ML-признаков", counts)
    execute(conn, finish, schema)
    return total_rows
