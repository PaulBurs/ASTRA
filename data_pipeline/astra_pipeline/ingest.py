"""Parallel loading of event journals into the staging table.

Parsing a row in Python (`prepared_event`) is the bottleneck of the import: one process
handles ~100k rows/s. A journal is split into byte ranges at line boundaries; independent
processes parse their range with the same parser and COPY it over their own connection.
Row order does not matter downstream: duplicates are resolved by event id, the latest event
of a channel by (time, event id).

Line boundaries are record boundaries only if no quoted field contains a line break.
Files without quotes are checked in seconds; other files are verified by a C-level CSV pass,
and a file with multi-line records is loaded sequentially as before.
"""
from __future__ import annotations

import csv
import io
import os
from collections import Counter
from concurrent.futures import FIRST_EXCEPTION, ProcessPoolExecutor, wait
from multiprocessing import get_context
from pathlib import Path

import psycopg
from psycopg import sql

from .csv_input import EventParser, iter_events

CHUNK_BYTES = int(os.getenv("DATASET_IMPORT_CHUNK_MB", "64")) * 1024 * 1024
BLOCK = 16 * 1024 * 1024


def _header(path: Path) -> tuple[int, str]:
    """-> (offset of the first data byte, header line as text)."""
    with path.open("rb") as file:
        raw = file.readline(64 * 1024)
    return len(raw), raw.decode("utf-8-sig")


def _dialect(header: str):
    # The same detection as csv_input.csv_rows.
    return csv.Sniffer().sniff(header, delimiters=",;\t")


def _has_quotes(path: Path) -> bool:
    with path.open("rb") as file:
        while block := file.read(BLOCK):
            if b'"' in block:
                return True
    return False


def single_line_records(path: str, header: str, start: int, end: int) -> bool:
    """True if every record of the byte range fits on one line. Strict parsing also fails on a
    range that ends inside quotes. Applied to consecutive ranges from the header on, this proves
    that every range starts at a record boundary."""
    with open(path, "rb") as file:
        file.seek(start)
        text = file.read(end - start).decode("utf-8")
    reader = csv.reader(io.StringIO(text, newline=""), dialect=_dialect(header), strict=True)
    previous = 0
    try:
        for _ in reader:                               # empty lines come back as [] - one line each
            if reader.line_num - previous != 1:
                return False
            previous = reader.line_num
    except csv.Error:
        return False
    return True


def splittable(path: Path) -> bool:
    """True if every line break ends a record (no quoted field spans lines)."""
    if not _has_quotes(path):
        return True
    start, header = _header(path)
    return all(single_line_records(str(path), header, a, b) for a, b in _ranges(path, start))


def _ranges(path: Path, start: int, chunk: int = 0) -> list[tuple[int, int]]:
    chunk = chunk or CHUNK_BYTES
    size, ranges = path.stat().st_size, []
    with path.open("rb") as file:
        while start < size:
            end = min(start + chunk, size)
            if end < size:
                file.seek(end)
                end += len(file.readline())            # move to the start of the next line
            ranges.append((start, end))
            start = end
    return ranges


def _line_number(path: Path, offset: int, line_in_chunk: int) -> int:
    lines = 0
    with path.open("rb") as file:
        while offset > 0:
            block = file.read(min(BLOCK, offset))
            lines += block.count(b"\n")
            offset -= len(block)
    return lines + line_in_chunk


def parse_chunk(path: Path, role: str, header: str, start: int, end: int):
    """Rows of one byte range, parsed exactly like csv_input.iter_events."""
    dialect = _dialect(header)
    names = [name.strip() for name in next(csv.reader([header], dialect=dialect))]
    with path.open("rb") as file:
        file.seek(start)
        text = file.read(end - start).decode("utf-8")
    reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect)
    parse = EventParser(names, role)
    for values in reader:
        if not values:                                 # DictReader skips empty lines too
            continue
        try:
            if len(values) != len(names):
                raise ValueError("Число полей не совпадает с заголовком")
            yield parse(values)
        except (ValueError, TypeError, OverflowError) as error:
            line = _line_number(path, start, reader.line_num)       # header included in the offset
            raise ValueError(f"{path.name}, строка {line}: {error}") from error


def load_chunk(url: str, schema: str, path: str, role: str, header: str, start: int, end: int):
    """Parse and COPY one byte range. -> (rows, years, latest event per channel)."""
    rows, years, latest = 0, set(), {}
    query = sql.SQL("COPY {}.ext_journal_prepared FROM STDIN").format(sql.Identifier(schema))
    with psycopg.connect(url, autocommit=True, application_name="astra-import") as conn:
        with conn.cursor().copy(query) as copy:
            for row in parse_chunk(Path(path), role, header, start, end):
                copy.write_row(row)
                rows += 1
                years.add(row[4].year)
                old = latest.get(row[1])
                if old is None or (row[4], row[0]) > (old[4], old[0]):
                    latest[row[1]] = row
    return rows, years, latest


def _merge(latest: dict, part: dict) -> None:
    for channel, row in part.items():
        old = latest.get(channel)
        if old is None or (row[4], row[0]) > (old[4], old[0]):
            latest[channel] = row


def load_events(conn, url: str, schema: str, files: list[dict], workers: int, progress, counts,
                consumed=lambda file: None):
    """Load all event journals. -> (latest event per channel, set of years).

    `consumed(file)` is called once a journal is fully loaded, so its upload can be
    removed before the others finish: CSV and staging never coexist in full."""
    latest, years = {}, set()
    events = [file for file in files if file["role"] in {"events", "prepared_events"}]
    parallel, sequential = [], []
    if workers > 1:
        progress("Проверка журналов", counts)
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            for file in events:
                path = Path(file["path"])
                start, header = _header(path)
                ranges = [(str(path), file["role"], header, a, b) for a, b in _ranges(path, start)]
                # Without quotes a line break always ends a record; otherwise check every range.
                ok = not _has_quotes(path) or all(pool.map(
                    single_line_records, *zip(*[(p, h, a, b) for p, _, h, a, b in ranges])))
                (parallel.extend(ranges) if ok else sequential.append(file))
            if parallel:
                owners = {str(Path(file["path"])): file for file in events}
                _load_parallel(pool, url, schema, parallel, progress, counts, latest, years,
                               lambda path: consumed(owners[path]))
    else:
        sequential = events
    for file in sequential:
        # Files whose quoted fields span lines, or a single worker: the original reader.
        stage = "Обработка " + file["name"]
        progress(stage, counts)
        query = sql.SQL("COPY {}.ext_journal_prepared FROM STDIN").format(sql.Identifier(schema))
        with conn.cursor().copy(query) as copy:
            for row in iter_events(Path(file["path"]), file["role"]):
                copy.write_row(row)
                counts["source_rows"] += 1
                years.add(row[4].year)
                _merge(latest, {row[1]: row})
                if counts["source_rows"] % 100_000 == 0:
                    progress(stage, counts)
        consumed(file)
    return latest, years


def _load_parallel(pool, url, schema, jobs, progress, counts, latest, years, consumed):
    done = 0
    remaining = Counter(job[0] for job in jobs)
    progress(f"Чтение журналов: 0 из {len(jobs)} частей", counts)
    owner = {pool.submit(load_chunk, url, schema, *job): job[0] for job in jobs}
    pending = set(owner)
    while pending:
        finished, pending = wait(pending, return_when=FIRST_EXCEPTION)
        for future in finished:
            if future.exception() is not None:
                for other in pending:
                    other.cancel()
                raise future.exception()
            rows, part_years, part_latest = future.result()
            counts["source_rows"] += rows
            years |= part_years
            _merge(latest, part_latest)
            done += 1
            progress(f"Чтение журналов: {done} из {len(jobs)} частей", counts)
            remaining[owner[future]] -= 1
            if not remaining[owner[future]]:
                consumed(owner[future])
