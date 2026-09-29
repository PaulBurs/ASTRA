"""Store raw and clean events together, exposing the original read interfaces.

Only `is_clean` is new: it marks the same winner as 02_build_dataset.sql's
DISTINCT ON. Raw history still includes duplicates and orphan channels.
Reference fields are joined on read instead of copied into millions of rows.

The work is split into per-year steps that stream.py runs as a pipeline: the staging
journal of a year is cleaned in independent channel parts (duplicates are always within
one channel), then the year is sealed: counted, indexed and analyzed while it is in RAM.
"""
from psycopg import sql

from .csv_input import PREPARED

YEARS = range(2019, 2027)
EVENT_INDEX = '("ид_канала_данных", "дата_время_события", "ид_события")'


def create_staging_parts(conn, schema, parts):
    """Split every year of the staging journal into hash partitions by channel: a cleaning
    task then reads only its part, once, and sorts it in memory. Called after
    00_create_journal.sql, before loading; the loader keeps writing to the parent table."""
    if parts <= 1:
        return
    for year in YEARS:
        conn.execute(f"DROP TABLE {schema}.ext_journal_prepared_{year}")
        conn.execute(f'''CREATE TABLE {schema}.ext_journal_prepared_{year}
            PARTITION OF {schema}.ext_journal_prepared
            FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
            PARTITION BY HASH ("ид_канала_данных")''')
        for part in range(parts):
            conn.execute(f'''CREATE UNLOGGED TABLE {schema}.ext_journal_prepared_{year}_p{part}
                PARTITION OF {schema}.ext_journal_prepared_{year}
                FOR VALUES WITH (MODULUS {parts}, REMAINDER {part})''')


def staging_bytes(conn, schema, year) -> int:
    return int(conn.execute(f'''SELECT coalesce(sum(pg_relation_size(relid)), 0)
        FROM pg_partition_tree('{schema}.ext_journal_prepared_{year}') WHERE isleaf''').fetchone()[0])


def create_event_storage(conn, schema):
    # The source journal is disposable staging; event_storage and dataset_ml are
    # ordinary WAL-logged tables and survive PostgreSQL restarts.
    conn.execute(f'''CREATE TABLE {schema}.event_storage
        (LIKE {schema}.ext_journal_prepared, is_clean boolean NOT NULL)
        PARTITION BY RANGE ("дата_время_события")''')
    conn.execute(f'''CREATE TABLE {schema}.build_log (
        "год" int PRIMARY KEY, "строк_в_источнике" bigint, "строк_сирот" bigint,
        "строк_загружено" bigint, "удалено_дублей" bigint)''')
    for year in YEARS:
        conn.execute(f'''CREATE TABLE {schema}.event_storage_{year}
            PARTITION OF {schema}.event_storage
            FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')''')
        conn.execute(f"INSERT INTO {schema}.build_log VALUES (%s, 0, 0, 0, 0)", (year,))
    # The features of a year read these views while later years are still being cleaned.
    for suffix in ("", *(f"_{year}" for year in YEARS)):
        conn.execute(f'''CREATE VIEW {schema}.dataset_events{suffix} AS
            SELECT j."дата_время_события", j."ид_канала_данных",
                c."тип_датчика", c."название_датчика", c."ид_объект",
                o."вид_объекта", o."родитель" AS "ид_комплекса",
                j."тип_значения", j."значение_число", j."значение_текст",
                (j."тревожное_raw" = 't') AS "тревожное_событие",
                s."тревожное" AS "тревожное_по_справочнику"
            FROM {schema}.event_storage{suffix} j
            JOIN {schema}.ref_channels c USING ("ид_канала_данных")
            JOIN {schema}.ref_objects o USING ("ид_объект")
            LEFT JOIN {schema}.ref_state_fixed s
                ON j."тип_значения" = 'text' AND s."тип_датчика" = c."тип_датчика"
                   AND s."название_состояния" = j."значение_текст"
            WHERE j.is_clean''')


def clean_query(schema, year, parts, part, groups, group) -> str:
    """One cleaning task: a channel part of the year, same statement as the canonical build."""
    source = f"{schema}.ext_journal_prepared_{year}" + (f"_p{part}" if parts > 1 else "")
    only = (f'AND ((j."ид_канала_данных" % {groups}) + {groups}) % {groups} = {group}'
            if groups > 1 else '')
    return f'''INSERT INTO {schema}.event_storage_{year}
        SELECT j.*, row_number() OVER (
            PARTITION BY j."ид_канала_данных", j."дата_время_события",
                         j."тревожное_raw", j."значение_датчика_raw"
            ORDER BY j."ид_события") = 1
        FROM {source} j
        JOIN {schema}.ref_channels c USING ("ид_канала_данных")
        WHERE TRUE {only}
        UNION ALL
        SELECT j.*, false FROM {source} j
        WHERE NOT EXISTS (SELECT 1 FROM {schema}.ref_channels c
                          WHERE c."ид_канала_данных" = j."ид_канала_данных") {only}'''


def seal_year(worker, schema, year, channels, settings, spare_workers=0) -> dict:
    """After all cleaning tasks of the year: counts, staging reclaimed, index and statistics
    built while the year is in RAM (with spare_workers parallel helpers when the pool has
    nothing else to do). -> clean events per channel."""
    rows = worker.execute(f'''SELECT "ид_канала_данных", count(*),
                count(*) FILTER (WHERE is_clean)
            FROM {schema}.event_storage_{year} GROUP BY 1''').fetchall()
    source = sum(r[1] for r in rows)
    orphan = sum(r[1] for r in rows if r[0] not in channels)
    loaded = sum(r[2] for r in rows)
    worker.execute(f'''UPDATE {schema}.build_log SET
        "строк_в_источнике"=%s, "строк_сирот"=%s,
        "строк_загружено"=%s, "удалено_дублей"=%s WHERE "год"=%s''',
        (source, orphan, loaded, source - orphan - loaded, year))
    # Reclaim one year's staging as soon as it is cleaned, bounding peak disk use.
    worker.execute(f"TRUNCATE {schema}.ext_journal_prepared_{year}")
    worker.execute(f"SET maintenance_work_mem = '{settings.maintenance_mem_mb}MB'")
    worker.execute(f"SET max_parallel_maintenance_workers = {spare_workers}")
    # Attached to the index of the parent table in finish_event_storage.
    worker.execute(f"CREATE INDEX ON {schema}.event_storage_{year} {EVENT_INDEX}")
    worker.execute(f"ANALYZE {schema}.event_storage_{year}")
    return {r[0]: r[2] for r in rows if r[2]}


def finish_event_storage(conn, schema, settings):
    settings.configure_indexing(conn)
    # Yearly indexes already exist: this only attaches them (and indexes empty years).
    conn.execute(f"CREATE INDEX ON {schema}.event_storage {EVENT_INDEX}")
    conn.execute(f"ANALYZE {schema}.event_storage")
    conn.execute(f"DROP TABLE {schema}.ext_journal_prepared")
    raw_columns = sql.SQL(", ").join(map(sql.Identifier, PREPARED)).as_string(conn)
    # Preserve both parent and yearly SQL interfaces, including column order/types.
    for suffix in ("", *(f"_{year}" for year in YEARS)):
        conn.execute(f'''CREATE VIEW {schema}.ext_journal_prepared{suffix} AS
            SELECT {raw_columns} FROM {schema}.event_storage{suffix}''')
