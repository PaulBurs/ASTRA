"""Execute the canonical ML SQL in independent, bounded channel/year tasks.

Do not reimplement the formulas: extract the INSERTs from the team's versioned
script. Splitting by entire channels preserves window history and timestamp peers.
"""
from dataclasses import dataclass
import os
import re

from .parallel import run_jobs, set_autovacuum

MIN_TASK_ROWS = 100_000
# ~1M rows per task: its sort fits in work_mem instead of spilling to disk, and many
# similar tasks keep all workers busy until the end.
TASK_ROWS = int(os.getenv("DATASET_FEATURE_TASK_ROWS", "1000000"))


NEIGHBOUR_DAYS = 32


def feature_days() -> int | None:
    """Days of ML features kept per channel, counted back from its last event.
    The application forecasts from the last 90 days (ML_PREDICTION_HISTORY_DAYS) only;
    `all` computes the whole history (e.g. to export a training set)."""
    value = os.getenv("DATASET_FEATURE_DAYS", "120").strip().lower()
    if value == "all":
        return None
    days = int(value)
    if days < 91:
        raise ValueError("DATASET_FEATURE_DAYS: не меньше 91 дня (прогноз берёт 90 дней) или all")
    return days


_RECENT = (
    # src: events from the channel's cutoff minus the window length (was: year start minus it)
    (re.compile(r"""AND e\."дата_время_события" >= TIMESTAMP '(\d{4})-01-01' - INTERVAL '(\d+) days'"""),
     r"""AND e."дата_время_события" >= GREATEST(TIMESTAMP '\1-01-01', fc.cutoff) - INTERVAL '\2 days'"""),
    # lb: the last event before that buffer, for the exact dt of the first event
    (re.compile(r"""AND z\."дата_время_события" < TIMESTAMP '(\d{4})-01-01' - INTERVAL '(\d+) days'"""),
     r"""AND z."дата_время_события" < GREATEST(TIMESTAMP '\1-01-01', (SELECT f.cutoff FROM ml.feature_cutoff f """
     r"""WHERE f.ch = mc."ид_канала_данных")) - INTERVAL '\2 days'"""),
    # output: only rows from the cutoff on
    (re.compile(r"""WHERE c\.t >= TIMESTAMP '(\d{4})-01-01';"""),
     r"""WHERE c.t >= GREATEST(TIMESTAMP '\1-01-01', c.feature_cutoff);"""),
    (re.compile(r"""p\."eps"\n    FROM ml\.dataset_events e\n"""),
     'p."eps", fc.cutoff AS feature_cutoff\n    FROM ml.dataset_events e\n'
     '    JOIN ml.feature_cutoff fc ON fc.ch = e."ид_канала_данных"\n'),
)


def recent_only(query: str) -> str:
    """Restrict a canonical block to rows at or after each channel's cutoff. Rows kept are
    computed from the same events (window buffer and previous event), so they equal the full run."""
    for pattern, replacement in _RECENT:
        query, found = pattern.subn(replacement, query)
        if found != 1:
            raise ValueError("Изменился формат 03_ml_features.sql: обновите расчёт недавних признаков")
    return query


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


def build_features(conn, url, schema, settings, inventory, script, execute, progress, counts):
    setup, blocks, finish = feature_plan(script)
    execute(conn, setup, schema)
    set_autovacuum(conn, schema, False)
    settings.configure(conn)
    conn.execute(f"ANALYZE {schema}.map_channel")
    codes = dict(conn.execute(f'SELECT "ид_канала_данных", "код_типа_датчика" FROM {schema}.map_channel'))
    days = feature_days()
    cutoff = {}
    if days is not None:
        # Per channel: its last clean event minus `days`. A forecast of a channel also counts the
        # events of its object's other channels over the 30 days (720 h) before its own last event,
        # so every channel also keeps rows from the object's earliest last event minus 32 days
        # (720 h + the 6 h episode gap + a day). Last events are found by backward index scans.
        conn.execute(f'''CREATE TABLE {schema}.feature_cutoff AS
            WITH last AS (
                SELECT m."ид_канала_данных" AS ch, m."код_объекта" AS object,
                       (SELECT max(z."дата_время_события") FROM {schema}.event_storage z
                         WHERE z.is_clean AND z."ид_канала_данных" = m."ид_канала_данных") AS last_event
                FROM {schema}.map_channel m)
            SELECT ch, LEAST(last_event - INTERVAL '{days} days',
                             min(last_event) OVER (PARTITION BY object) - INTERVAL '{NEIGHBOUR_DAYS} days') AS cutoff
            FROM last''')
        conn.execute(f"DELETE FROM {schema}.feature_cutoff WHERE cutoff IS NULL")
        conn.execute(f"ALTER TABLE {schema}.feature_cutoff ADD PRIMARY KEY (ch)")
        conn.execute(f"ANALYZE {schema}.feature_cutoff")
        cutoff = {ch: year for ch, year in conn.execute(
            f"SELECT ch, extract(year FROM cutoff)::int FROM {schema}.feature_cutoff")}
        counts["feature_days"] = days
        counts["feature_expected"] = conn.execute(f'''SELECT count(*) FROM {schema}.event_storage e
            JOIN {schema}.feature_cutoff f ON f.ch = e."ид_канала_данных"
            WHERE e.is_clean AND e."дата_время_события" >= f.cutoff''').fetchone()[0]
    jobs = []
    for block in blocks:
        # a channel contributes to a year only if its cutoff is not after that year
        channels = {ch: n for ch, n in inventory.get(block.year, {}).items() if codes.get(ch) in block.codes
                    and (days is None or cutoff.get(ch, 10**4) <= block.year)}
        for batch in channel_batches(channels, settings.workers):
            jobs.append((sum(channels[ch] for ch in batch), block, batch))
    # Largest jobs first: small ones fill the gaps instead of big ones finishing last.
    jobs = [(block, batch) for _, block, batch in sorted(jobs, key=lambda job: -job[0])]
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
        if days is not None:
            query = recent_only(query)
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
    settings.configure_indexing(conn)
    execute(conn, finish, schema)
    return total_rows
