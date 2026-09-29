"""Fast journal loading: PostgreSQL parses the CSV, SQL applies lct_features.parse rules.

The previous loader parsed every row in Python (csv.DictReader + parse_value +
COPY write_row), about 150 thousand rows per second on a single core - the
largest stage of an import. Here the file bytes are streamed to PostgreSQL
COPY unchanged, and the typed columns are computed by SQL in parallel chunks.

The SQL reproduces lct_features.parse / csv_input.prepared_event exactly for
the organizers' journals (checked by tests against the Python parser). Files
with CSV features where PostgreSQL and Python's csv module could disagree -
quote characters, blank lines, an unusual dialect - go through the original
Python loader instead, so the result never depends on the chosen path.
Known deliberate difference: Python's int()/float() also accept non-ASCII digits
and underscores inside event/channel ids; SQL rejects such ids with an error
instead of loading them (the organizers' files contain none).
"""
from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql

from .csv_input import PREPARED, RAW, csv_rows
from .parallel import run_jobs

CHUNK_BYTES = 1 << 20
MIN_CHUNK_PAGES = 2048          # ~16 MB of staging per parallel transform task

# float(): optional sign, digits with single underscores, fraction, exponent.
_DIGITS = r"[0-9](_?[0-9])*"
NUMERIC_RE = (r"^[[:space:]]*[+-]?(" + _DIGITS + r"(\." + "(" + _DIGITS + r")?)?|\." + _DIGITS + ")"
              r"([eE][+-]?" + _DIGITS + r")?[[:space:]]*$")
NONFINITE_RE = r"^[[:space:]]*[+-]?(inf|infinity|nan)[[:space:]]*$"
DATETIME_RE = r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2}$"


class NeedsPythonLoader(Exception):
    """The file uses CSV features that only the Python reader interprets reliably."""


def _dialect_ok(dialect) -> bool:
    return (dialect.delimiter in ",;\t" and dialect.quotechar == '"'
            and not dialect.escapechar and not dialect.skipinitialspace)


def copy_file_to_staging(conn, schema: str, table: str, path: Path, progress, counts, stage) -> list[str]:
    """COPY the file into an UNLOGGED text table; returns the stripped header names."""
    with csv_rows(path) as reader:
        names, dialect = list(reader.fieldnames), reader.dialect
    if not _dialect_ok(dialect):
        raise NeedsPythonLoader
    cols = [f"c{i}" for i in range(len(names))]
    ident = sql.Identifier(schema, table)
    conn.execute(sql.SQL("CREATE UNLOGGED TABLE {} ({})").format(
        ident, sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in cols)))
    copy_sql = sql.SQL(
        "COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, DELIMITER {}, QUOTE '\"', "
        "ENCODING 'UTF8', FORCE_NOT_NULL ({}))").format(
        ident, sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Literal(dialect.delimiter),
        sql.SQL(", ").join(map(sql.Identifier, cols)))
    try:
        _stream(conn, copy_sql, path, max(1, path.stat().st_size), progress, counts, stage)
    except psycopg.errors.DataError as error:
        # Wrong number of fields, bad encoding: report like the Python reader did.
        where = (error.diag.context or "").replace(f"COPY {table}, ", "")
        raise ValueError(f"{path.name}: {error.diag.message_primary}. {where}".strip()) from None
    return names


def _stream(conn, copy_sql, path, size, progress, counts, stage):
    sent, tail = 0, b""
    with conn.cursor() as cursor, path.open("rb") as file:
        with cursor.copy(copy_sql) as copy:
            while chunk := file.read(CHUNK_BYTES):
                probe = tail + chunk
                # Quotes and empty lines are the only places where Python's csv
                # (as configured by csv_rows) and PostgreSQL COPY can differ.
                if b'"' in chunk or b"\n\n" in probe or b"\n\r\n" in probe:
                    raise NeedsPythonLoader
                tail = chunk[-2:]
                copy.write(chunk)
                sent += len(chunk)
                if sent % (64 * CHUNK_BYTES) < CHUNK_BYTES:
                    progress(f"{stage}: {100 * sent // size}%", counts)


def _column(names, name, path):
    try:
        return sql.Identifier(f"c{names.index(name)}")
    except ValueError:
        raise ValueError(f"{path.name}: нет столбца «{name}»") from None


def transform_sql(schema: str, table: str, names: list[str], role: str, path: Path):
    """SELECT producing ext_journal_prepared rows from one staging chunk (ctid range)."""
    col = lambda name: _column(names, name, path)
    if role == "events":
        d, t = col("дата"), col("время")
        ts = sql.SQL(
            "(CASE WHEN position('.' IN btrim({d})) > 0 THEN to_char(to_date(btrim({d}), 'FMDD.FMMM.YYYY'), 'YYYY-MM-DD')"
            " ELSE btrim({d}) END || ' ' || btrim({t}))::timestamp").format(d=d, t=t)
        alarm, raw = col("тревожное"), col("значение_датчика")
    else:
        ts = sql.SQL("btrim({})::timestamp").format(col("дата_время_события"))
        alarm, raw = col("тревожное_raw"), col("значение_датчика_raw")
    fail = sql.Identifier(schema, "_import_fail")
    # OFFSET 0 keeps each derived column computed once per row: without the fence
    # PostgreSQL inlines the subqueries and re-evaluates the regexes and the
    # timestamp parsing for every reference (measured: 2x slower).
    return sql.SQL("""
        SELECT eid, ch,
               CASE WHEN a IN ('t', 'true', '1') THEN 't' WHEN a IN ('f', 'false', '0') THEN 'f'
                    ELSE {fail}('Неизвестное значение признака тревожности', eid) END,
               r,
               CASE WHEN ts >= '2019-01-01' AND ts < '2027-01-01' THEN ts
                    ELSE {fail}('Алгоритм data_pipeline поддерживает события за 2019–2026 годы', eid)::timestamp END,
               CASE WHEN vt = 'nonfinite' THEN {fail}('Числовое значение должно быть конечным', eid) ELSE vt END,
               CASE vt WHEN 'numeric' THEN replace(r, '_', '')::float8::text::numeric
                       WHEN 'binary' THEN right(r, 1)::numeric END,
               CASE WHEN vt = 'datetime' THEN (substr(r, 7, 4) || '-' || substr(r, 4, 2) || '-' || substr(r, 1, 2)
                                              || ' ' || substr(r, 12))::timestamp END,
               CASE WHEN vt = 'text' THEN r END
        FROM (
            SELECT s.*,
                   CASE WHEN r IN ('01.01.1970 03:00:00', '01.01.1970 03:00:01') THEN 'binary'
                        WHEN r ~ {dt_re} THEN 'datetime'
                        WHEN r ~ {num_re} THEN 'numeric'
                        WHEN r ~* {nonfinite_re} THEN 'nonfinite'
                        ELSE 'text' END AS vt
            FROM (
                SELECT btrim({id})::bigint AS eid, btrim({ch})::bigint AS ch,
                       lower(btrim({alarm})) AS a, {raw} AS r, {ts} AS ts
                FROM {staging} WHERE ctid >= %s::tid AND ctid < %s::tid
                OFFSET 0
            ) s
            OFFSET 0
        ) v
    """).format(id=col("ид_события"), ch=col("ид_канала_данных"), alarm=alarm, raw=raw, ts=ts,
                staging=sql.Identifier(schema, table), fail=fail,
                dt_re=sql.Literal(DATETIME_RE), num_re=sql.Literal(NUMERIC_RE),
                nonfinite_re=sql.Literal(NONFINITE_RE))


def create_helpers(conn, schema: str) -> None:
    conn.execute(sql.SQL("""
        CREATE FUNCTION {}(message text, event_id bigint) RETURNS text
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION USING ERRCODE = 'data_exception',
                MESSAGE = format('%s (ид_события %s)', message, event_id);
        END $$""").format(sql.Identifier(schema, "_import_fail")))


def drop_helpers(conn, schema: str) -> None:
    conn.execute(sql.SQL("DROP FUNCTION IF EXISTS {}(text, bigint)").format(
        sql.Identifier(schema, "_import_fail")))


def transform_file(conn, url, schema, settings, table, names, role, path, progress, counts, stage):
    """Parse one staging table into ext_journal_prepared in parallel ctid ranges."""
    insert = (sql.SQL("INSERT INTO {} ").format(sql.Identifier(schema, "ext_journal_prepared"))
              + transform_sql(schema, table, names, role, path))
    pages = conn.execute(sql.SQL("SELECT pg_relation_size({}) / current_setting('block_size')::int").format(
        sql.Literal(f'"{schema}"."{table}"'))).fetchone()[0]
    step = max(MIN_CHUNK_PAGES, -(-pages // (settings.workers * 4)))
    ranges = [(f"({lo},0)", f"({lo + step},0)") for lo in range(0, pages + 1, step)]

    def work(worker, bounds):
        try:
            return worker.execute(insert, bounds).rowcount
        except psycopg.errors.DataException as error:
            raise ValueError(f"{path.name}: {error.diag.message_primary or error}") from None

    loaded = []

    def finished(rows):
        loaded.append(rows)
        progress(f"{stage}: разбор значений {len(loaded)} из {len(ranges)}", counts)

    run_jobs(url, settings, ranges, work, finished)
    return sum(loaded)


def load_events_fast(conn, url, schema, settings, path: Path, role: str, index: int, progress, counts, stage) -> int:
    """Returns loaded rows; raises NeedsPythonLoader before loading anything durable."""
    table = f"_staging_{index}"
    try:
        names = copy_file_to_staging(conn, schema, table, path, progress, counts, stage)
        required = RAW if role == "events" else PREPARED
        for name in required:
            _column(names, name, path)
        return transform_file(conn, url, schema, settings, table, names, role, path, progress, counts, stage)
    finally:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(schema, table)))
