"""Run the team's SQL, isolated per import, with user-selected reference tables."""
from pathlib import Path
import sys

import psycopg
from psycopg import sql

from .cache import BuildProfile, CachePlan, staging_parts
from .csv_input import CHANNELS, OBJECTS, csv_rows
from .compact import create_event_storage, create_staging_parts, finish_event_storage
from .features import fill_unlogged, finish_features, ml_index_columns, prepare_features, without_wal
from .ingest import load_events
from .parallel import BuildSettings, set_autovacuum
from .registry import schema_name
from .stream import YearPipeline

SQL_ROOT = Path(__file__).resolve().parents[1] / "sql"
if not SQL_ROOT.is_dir():
    SQL_ROOT = Path(sys.prefix) / "share" / "astra-pipeline" / "sql"


def run_script(conn, filename: str, schema: str) -> None:
    # These are trusted, versioned scripts, never uploaded SQL. Their DROP/TRUNCATE
    # statements are scoped to a new UUID schema, not the application's public tables.
    script = (SQL_ROOT / filename).read_text(encoding="utf-8")
    execute_script(conn, script, schema)


def execute_script(conn, script: str, schema: str) -> None:
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
    settings = BuildSettings.from_env()
    progress("Подготовка таблиц", {})
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    counts = {"source_rows": 0}
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            # Memory of the workers and the year pipeline follow the RAM cache (cache.py).
            plan = CachePlan.from_server(conn)
            settings = plan.size_workers(settings)
            profile = BuildProfile(conn, progress)
            progress = profile.progress
            progress(f"Подготовка таблиц ({plan.describe()})", counts)
            settings.configure(conn)
            staging = (SQL_ROOT / "00_create_journal.sql").read_text(encoding="utf-8")
            execute_script(conn, staging.replace("CREATE TABLE", "CREATE UNLOGGED TABLE"), schema)
            journal_bytes = sum(Path(f["path"]).stat().st_size for f in files
                                if f["role"] in {"events", "prepared_events"})
            parts = staging_parts(journal_bytes, settings.work_mem_mb)
            create_staging_parts(conn, schema, parts)
            set_autovacuum(conn, schema, False)
            # Journals are parsed by several processes in parallel (see ingest.py).
            latest, source_years = load_events(conn, url, schema, files, settings.workers, progress, counts)
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
            for table in ("ref_channels", "ref_objects", "ref_state_fixed"):
                conn.execute(f"ANALYZE {schema}.{table}")
            progress("Очистка и объединение событий", counts)
            create_event_storage(conn, schema)
            blocks, finish, codes = prepare_features(
                conn, schema, settings, (SQL_ROOT / "03_ml_features.sql").read_text(encoding="utf-8"),
                execute_script)
            channels = {r[0] for r in conn.execute(f'SELECT "ид_канала_данных" FROM {schema}.ref_channels')}
            unlogged = without_wal(conn)
            if unlogged:
                fill_unlogged(conn, schema, source_years)
            # Clean -> index -> features -> index, year after year, while each year is in RAM.
            inventory, feature_rows = YearPipeline(
                conn, schema, settings, plan, source_years, parts, channels, blocks, codes,
                ml_index_columns(finish), unlogged, progress, counts, profile).run(url)
            event_rows, orphan_rows, duplicates = conn.execute(f'''
                SELECT sum("строк_загружено"), sum("строк_сирот"), sum("удалено_дублей")
                FROM {schema}.build_log
            ''').fetchone()
            counts.update(event_rows=int(event_rows), orphan_rows=int(orphan_rows),
                          duplicate_rows=int(duplicates), feature_rows=feature_rows)
            if not event_rows:
                raise ValueError("После проверки справочников в журнале не осталось событий")
            progress("Индексирование истории событий", counts)
            finish_event_storage(conn, schema, settings)
            progress("Индексирование ML-признаков", counts)
            finish_features(conn, schema, settings, finish, execute_script)
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
            profile.save(conn, schema)
            set_autovacuum(conn, schema, True)
        except BaseException:
            # This UUID schema belongs only to the failed import. Previously ready
            # datasets and the app's public tables are never replaced or truncated.
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            raise
    return counts
