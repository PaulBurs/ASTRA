"""Parallel journal parsing must equal the sequential parser row for row."""
import tempfile
import unittest
from pathlib import Path

import random

from astra_pipeline.csv_input import PREPARED, RAW, EventParser, iter_events, prepared_event
from astra_pipeline.ingest import _header, _ranges, parse_chunk, single_line_records, splittable


def journal(rows, header=",".join(RAW)):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    handle.write("﻿" + header + "\r\n" + "".join(row + "\r\n" for row in rows))
    handle.close()
    return Path(handle.name)


def parallel(path, role="events", chunk=97):
    start, header = _header(path)
    return [row for a, b in _ranges(path, start, chunk) for row in parse_chunk(path, role, header, a, b)]


class ParallelIngestTest(unittest.TestCase):
    def setUp(self):
        values = ["21.5", "Обнаружено движение", "01.01.1970 03:00:01", "05.03.2024 10:00:00", "", '"В норме, 3"']
        self.rows = [f"{i},{1000 + i % 7},2024-0{1 + i % 9}-1{i % 10},1{i % 10}:0{i % 6}:3{i % 10},"
                     f"{'t' if i % 5 == 0 else 'f'},{values[i % len(values)]}" for i in range(1, 400)]
        self.rows.insert(50, "")                       # an empty line is skipped by both readers

    def test_chunks_give_the_same_rows_as_the_sequential_reader(self):
        path = journal(self.rows)
        self.addCleanup(path.unlink)
        self.assertTrue(splittable(path))              # quotes, but no multi-line records
        self.assertEqual(parallel(path), list(iter_events(path, "events")))
        self.assertGreater(len(_ranges(path, _header(path)[0], 97)), 50)

    def test_error_reports_the_same_file_line(self):
        rows = list(self.rows)
        rows[300] = "301,1001,2031-01-01,10:00:00,f,1"   # year outside 2019–2026
        path = journal(rows)
        self.addCleanup(path.unlink)
        with self.assertRaises(ValueError) as sequential:
            list(iter_events(path, "events"))
        with self.assertRaises(ValueError) as chunked:
            parallel(path)
        self.assertEqual(str(chunked.exception), str(sequential.exception))
        self.assertIn("строка 302", str(chunked.exception))

    def test_quoted_line_break_disables_splitting(self):
        rows = list(self.rows)
        rows[10] = '11,1004,2024-02-11,11:05:31,f,"две\r\nстроки"'
        path = journal(rows)
        self.addCleanup(path.unlink)
        self.assertFalse(splittable(path))
        # wherever a range boundary falls, the multi-line record is found in some range
        start, header = _header(path)
        for chunk in range(20, 400, 7):
            ranges = _ranges(path, start, chunk)
            with self.subTest(chunk=chunk):
                self.assertFalse(all(single_line_records(str(path), header, a, b) for a, b in ranges))


class EventParserTest(unittest.TestCase):
    """The memoised parser must equal prepared_event row for row, errors included."""

    def outcome(self, call):
        try:
            return ("ok", call())
        except (ValueError, TypeError, OverflowError) as error:
            return (type(error).__name__, str(error))

    def check(self, role, names, rows):
        parse = EventParser(names, role)
        for row in rows:
            self.assertEqual(self.outcome(lambda: parse(row)),
                             self.outcome(lambda: prepared_event(dict(zip(names, row)), role)), row)

    def test_same_results_and_errors_as_prepared_event(self):
        rng = random.Random(7)
        values = ["21.5", " 3 ", "1_000", "1e5", "inf", "nan", "-0.00", "", "Обнаружено движение",
                  "01.01.1970 03:00:00", "01.01.1970 03:00:01", "05.03.2024 10:00:00", "31.02.2024 10:00:00",
                  "В норме, 3", "0,5", "x"]
        alarms = ["t", "f", "T", " true ", "0", "1", "yes", "", "FALSE"]
        dates = ["2024-01-04", "04.01.2024", "4.1.2024", "2031-01-01", "2018-12-31", "31.02.2024", " 2023-06-01 "]
        times = ["11:30:31", "00:00:00", "23:59:59.123456", "25:00:00", " 07:05:00", "7:5"]
        ids = ["1", "2", " 3", "x", "4.0"]
        raw = [[rng.choice(ids), rng.choice(["10", "11", "y"]), rng.choice(dates), rng.choice(times),
                rng.choice(alarms), rng.choice(values)] for _ in range(4000)]
        self.check("events", RAW, raw)
        stamps = ["2024-01-04 11:30:31", "2024-01-04T11:30:31", "2031-01-01 00:00:00", "bad", " 2023-06-01 10:00:00 "]
        prepared = [[rng.choice(ids), "10", rng.choice(alarms), rng.choice(values), rng.choice(stamps),
                     "text", "", "", ""] for _ in range(2000)]
        self.check("prepared_events", PREPARED, prepared)


if __name__ == "__main__":
    unittest.main()
