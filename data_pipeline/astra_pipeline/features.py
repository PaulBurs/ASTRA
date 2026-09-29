"""Execute the canonical ML SQL in independent, bounded channel/year tasks.

Do not reimplement the formulas: extract the INSERTs from the team's versioned
script. Splitting by entire channels preserves window history and timestamp peers.
The tasks of a year run as soon as that year and every earlier one are cleaned (stream.py).
"""
from dataclasses import dataclass
import os
import re

from .parallel import set_autovacuum

MIN_TASK_ROWS = 100_000
# ~1M rows per task: its sort fits in work_mem instead of spilling to disk, and many
# similar tasks keep all workers busy until the end.
TASK_ROWS = int(os.getenv("DATASET_FEATURE_TASK_ROWS", "1000000"))


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
    rows = sum(channel_counts.values())
    count = max(min(workers, max(1, rows // MIN_TASK_ROWS)), -(-rows // TASK_ROWS))
    batches, weights = [[] for _ in range(count)], [0] * count
    for channel, rows in sorted(channel_counts.items(), key=lambda item: (-item[1], item[0])):
        target = min(range(count), key=lambda i: weights[i])
        batches[target].append(channel)
        weights[target] += rows
    return [batch for batch in batches if batch]


def prepare_features(conn, schema, settings, script, execute):
    """Code tables and the empty dataset_ml: they depend only on the reference tables."""
    setup, blocks, finish = feature_plan(script)
    execute(conn, setup, schema)
    set_autovacuum(conn, schema, False)
    settings.configure(conn)
    conn.execute(f"ANALYZE {schema}.map_channel")
    codes = dict(conn.execute(f'SELECT "ид_канала_данных", "код_типа_датчика" FROM {schema}.map_channel'))
    return blocks, finish, codes


def year_tasks(blocks, year, inventory, codes, workers):
    """Feature tasks of one year: (rows, block, channel batch), largest first, so that small
    tasks fill the gaps instead of big ones finishing last."""
    tasks = []
    for block in blocks:
        if block.year != year:
            continue
        channels = {ch: n for ch, n in inventory.items() if codes.get(ch) in block.codes}
        for batch in channel_batches(channels, workers):
            tasks.append((sum(channels[ch] for ch in batch), block, batch))
    return sorted(tasks, key=lambda task: -task[0])


def calculate(worker, schema, block, batch) -> int:
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


def ml_index_columns(finish):
    """Columns of the canonical index on dataset_ml, e.g. '("ид_канала_данных", ...)'.
    A plain index with the same columns built on a partition beforehand is attached by
    the canonical CREATE INDEX instead of being built again."""
    match = re.search(r'CREATE INDEX "[^"]+" ON ml\.dataset_ml (\([^()]+\));', finish)
    return match[1] if match else None


def without_wal(conn) -> bool:
    """With wal_level = minimal (the ASTRA container) a table made durable in one transaction
    is written once and fsynced, instead of being written twice: to WAL and to the table."""
    return conn.execute("SELECT current_setting('wal_level') = 'minimal'").fetchone()[0]


def fill_unlogged(conn, schema, years) -> None:
    """The features of a year are written without WAL; finish_year makes them durable."""
    for year in years:
        conn.execute(f"ALTER TABLE {schema}.dataset_ml_{year} SET UNLOGGED")


def finish_year(worker, schema, year, columns, unlogged, settings, spare_workers=0) -> None:
    """The year's features are complete: made durable (if filled without WAL) and indexed
    while in RAM. In one transaction, so with wal_level = minimal neither is WAL-logged."""
    worker.execute(f"SET maintenance_work_mem = '{settings.maintenance_mem_mb}MB'")
    worker.execute(f"SET max_parallel_maintenance_workers = {spare_workers}")
    with worker.transaction():
        if unlogged:
            worker.execute(f"ALTER TABLE {schema}.dataset_ml_{year} SET LOGGED")
        if columns:
            worker.execute(f"CREATE INDEX ON {schema}.dataset_ml_{year} {columns}")


def finish_features(conn, schema, settings, finish, execute):
    settings.configure_indexing(conn)
    execute(conn, finish, schema)
