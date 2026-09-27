"""Run the team's SQL, isolated per import, with user-selected reference tables."""
from pathlib import Path
import sys

import psycopg
from psycopg import sql

from .csv_input import CHANNELS, OBJECTS, csv_rows, iter_events
from .registry import schema_name

SQL_ROOT = Path(__file__).resolve().parents[1] / "sql"
if not SQL_ROOT.is_dir():
    SQL_ROOT = Path(sys.prefix) / "share" / "astra-pipeline" / "sql"


def run_script(conn, filename: str, schema: str) -> None:
    # These are trusted, versioned scripts, never uploaded SQL. Their DROP/TRUNCATE
    # statements are scoped to a new UUID schema, not the application's public tables.
    script = (SQL_ROOT / filename).read_text(encoding="utf-8")
    script = script.replace("public.", f"{schema}.").replace("ml.", f"{schema}.")
    script = script.replace("CREATE SCHEMA IF NOT EXISTS ml;", f"CREATE SCHEMA IF NOT EXISTS {schema};")
    with conn.cursor() as cursor:
        cursor.execute(script, prepare=False)
        while cursor.nextset():
            pass


def copy_references(conn, schema: str, table: str, path: Path, columns: list[str]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(sql.SQL("TRUNCATE {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
        query = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
            sql.Identifier(schema), sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, columns)))
        with cursor.copy(query) as copy, csv_rows(path) as rows:
            for row in rows:
                if None in row or any(row.get(c) is None for c in columns):
                    raise ValueError(f"{path.name}, строка {rows.line_num}: неверное число полей")
                copy.write_row(tuple(row[c] or None for c in columns))


def build_dataset(engine, dataset_id, files: list[dict], progress) -> dict:
    schema = schema_name(dataset_id)
    progress("Подготовка таблиц", {})
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    counts = {"source_rows": 0}
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            run_script(conn, "00_create_journal.sql", schema)
            latest = {}
            for file in files:
                if file["role"] not in {"events", "prepared_events"}:
                    continue
                stage = "Обработка " + file["name"]
                progress(stage, counts)
                query = sql.SQL("COPY {}.ext_journal_prepared FROM STDIN").format(sql.Identifier(schema))
                with conn.cursor().copy(query) as copy:
                    for row in iter_events(Path(file["path"]), file["role"]):
                        copy.write_row(row)
                        counts["source_rows"] += 1
                        old = latest.get(row[1])
                        if old is None or (row[4], row[0]) > (old[4], old[0]):
                            latest[row[1]] = row
                        if counts["source_rows"] % 100_000 == 0:
                            progress(stage, counts)
            if not counts["source_rows"]:
                raise ValueError("Выбранные журналы не содержат событий")

            progress("Загрузка справочников", counts)
            run_script(conn, "01_reference_tables.sql", schema)
            for file in files:
                if file["role"] == "channels":
                    copy_references(conn, schema, "ref_channels", Path(file["path"]), CHANNELS)
                elif file["role"] == "objects":
                    copy_references(conn, schema, "ref_objects", Path(file["path"]), OBJECTS)
            # Missing parents are allowed (the supplied district's parent is external),
            # but channel -> object must be complete; otherwise SQL would silently lose rows.
            missing = conn.execute(f'''
                SELECT count(*) FROM {schema}.ref_channels c
                LEFT JOIN {schema}.ref_objects o USING ("ид_объект")
                WHERE o."ид_объект" IS NULL
            ''').fetchone()[0]
            if missing:
                raise ValueError(f"В справочнике отсутствуют объекты для {missing} каналов")
            progress("Очистка и объединение событий", counts)
            run_script(conn, "02_build_dataset.sql", schema)
            event_rows, orphan_rows, duplicates = conn.execute(f'''
                SELECT sum("строк_загружено"), sum("строк_сирот"), sum("удалено_дублей")
                FROM {schema}.build_log
            ''').fetchone()
            counts.update(event_rows=int(event_rows), orphan_rows=int(orphan_rows),
                          duplicate_rows=int(duplicates))
            if not event_rows:
                raise ValueError("После проверки справочников в журнале не осталось событий")
            progress("Расчёт ML-признаков", counts)
            run_script(conn, "03_ml_features.sql", schema)
            counts["feature_rows"] = conn.execute(f"SELECT count(*) FROM {schema}.dataset_ml").fetchone()[0]
            if counts["feature_rows"] != counts["event_rows"]:
                raise ValueError("Число ML-строк не совпало с числом событий. Проверьте совместимость справочников с кодами модели")
            counts["channels"] = conn.execute(f"SELECT count(*) FROM {schema}.ref_channels").fetchone()[0]
            counts["objects"] = conn.execute(f"SELECT count(*) FROM {schema}.ref_objects").fetchone()[0]
            progress("Подготовка доступа приложения к данным", counts)
            conn.execute(f"CREATE TABLE {schema}.latest_sensor_events AS SELECT * FROM {schema}.ext_journal_prepared WITH NO DATA")
            with conn.cursor().copy(f"COPY {schema}.latest_sensor_events FROM STDIN") as copy:
                for row in latest.values():
                    copy.write_row(row)
            conn.execute(f'CREATE UNIQUE INDEX ON {schema}.latest_sensor_events ("ид_канала_данных")')
            conn.execute(f'CREATE INDEX ON {schema}.ext_journal_prepared ("ид_канала_данных", "дата_время_события", "ид_события")')
        except BaseException:
            # This UUID schema belongs only to the failed import. Previously ready
            # datasets and the app's public tables are never replaced or truncated.
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            raise
    return counts
