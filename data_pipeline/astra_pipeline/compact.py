"""Store raw and clean events together, exposing the original read interfaces.

Only `is_clean` is new: it marks the same winner as 02_build_dataset.sql's
DISTINCT ON. Raw history still includes duplicates and orphan channels.
Reference fields are joined on read instead of copied into millions of rows.
"""
from psycopg import sql

from .csv_input import PREPARED
from .parallel import run_jobs, set_autovacuum

YEARS = range(2019, 2027)


def compact_events(conn, url, schema, settings, source_years, progress, counts):
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
    set_autovacuum(conn, schema, False)

    channels = {r[0] for r in conn.execute(f'SELECT "ид_канала_данных" FROM {schema}.ref_channels')}
    inventory = {}
    # Duplicates are always within one channel, so a year splits into independent channel
    # groups: a few years still keep every worker busy.
    years = sorted(source_years)
    groups = max(1, settings.workers // max(1, len(years)))
    remaining = {year: groups for year in years}

    def compact(worker, job):
        year, group = job
        part = (f'AND ((j."ид_канала_данных" % {groups}) + {groups}) % {groups} = {group}'
                if groups > 1 else '')
        worker.execute(f'''INSERT INTO {schema}.event_storage_{year}
            SELECT j.*, row_number() OVER (
                PARTITION BY j."ид_канала_данных", j."дата_время_события",
                             j."тревожное_raw", j."значение_датчика_raw"
                ORDER BY j."ид_события") = 1
            FROM {schema}.ext_journal_prepared_{year} j
            JOIN {schema}.ref_channels c USING ("ид_канала_данных")
            WHERE TRUE {part}
            UNION ALL
            SELECT j.*, false FROM {schema}.ext_journal_prepared_{year} j
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.ref_channels c
                              WHERE c."ид_канала_данных" = j."ид_канала_данных") {part}''')
        return year

    def finished(year):
        remaining[year] -= 1
        if remaining[year]:
            return
        rows = conn.execute(f'''SELECT "ид_канала_данных", count(*),
                    count(*) FILTER (WHERE is_clean)
                FROM {schema}.event_storage_{year} GROUP BY 1''').fetchall()
        source = sum(r[1] for r in rows)
        orphan = sum(r[1] for r in rows if r[0] not in channels)
        loaded = sum(r[2] for r in rows)
        conn.execute(f'''UPDATE {schema}.build_log SET
            "строк_в_источнике"=%s, "строк_сирот"=%s,
            "строк_загружено"=%s, "удалено_дублей"=%s WHERE "год"=%s''',
            (source, orphan, loaded, source - orphan - loaded, year))
        # Reclaim one year's staging as soon as it is compacted, bounding peak disk use.
        conn.execute(f"TRUNCATE {schema}.ext_journal_prepared_{year}")
        inventory[year] = {r[0]: r[2] for r in rows if r[2]}
        progress(f"Очистка событий: {len(inventory)} из {len(years)} лет", counts)

    run_jobs(url, settings, [(year, group) for year in years for group in range(groups)], compact, finished)
    progress("Индексирование истории событий", counts)
    settings.configure_indexing(conn)
    conn.execute(f'''CREATE INDEX ON {schema}.event_storage
        ("ид_канала_данных", "дата_время_события", "ид_события")''')
    conn.execute(f"ANALYZE {schema}.event_storage")
    conn.execute(f"DROP TABLE {schema}.ext_journal_prepared")
    raw_columns = sql.SQL(", ").join(map(sql.Identifier, PREPARED)).as_string(conn)
    # Preserve both parent and yearly SQL interfaces, including column order/types.
    for suffix in ("", *(f"_{year}" for year in YEARS)):
        conn.execute(f'''CREATE VIEW {schema}.ext_journal_prepared{suffix} AS
            SELECT {raw_columns} FROM {schema}.event_storage{suffix}''')
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
    return inventory
