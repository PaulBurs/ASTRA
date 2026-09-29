# sql

SQL-скрипты базовой схемы ASTRA для PostgreSQL 16: DDL, индексы, эталонные запросы, диагностика и тестовые данные.

Модель данных: объект → канал (датчик) → событие.

## Структура

| Путь | Что делает | Технология |
|---|---|---|
| `schema/01_core_schema.sql` | Создаёт таблицы `astra_objects`, `astra_channels`, `ext_journal_prepared` и CHECK-ограничение `chk_event_value_type` | PostgreSQL DDL, `CREATE TABLE IF NOT EXISTS` |
| `indexes/01_ext_journal_sensor_time.sql` | Индекс `idx_ext_journal_sensor_time_event (sensor_id, occurred_at, event_id)` для выборок истории канала | B-tree, `CREATE INDEX CONCURRENTLY IF NOT EXISTS` |
| `indexes/02_astra_channels_catalog.sql` | Индексы `idx_astra_channels_system_type (engineering_system, sensor_type)` и `idx_astra_channels_object (object_id)` | B-tree, `CONCURRENTLY` |
| `queries/latest_sensor_event.sql` | Последнее событие канала | SQL, именованные параметры SQLAlchemy |
| `queries/ml_inference_window.sql` | События канала в окне `[:start, :end]`, по убыванию времени, `LIMIT :limit` | SQL, SQLAlchemy |
| `queries/ml_training_events.sql` | События списка каналов `IN :sensor_ids` в `[:start, :end)`, по каналу и времени | SQL, SQLAlchemy |
| `diagnostics/01_ext_journal_info.sql` | Наличие, колонки и индексы `ext_journal_prepared` | `information_schema`, `pg_indexes`; только чтение |
| `diagnostics/02_database_inventory.sql` | Текущая БД/пользователь, схемы, таблицы, представления, размеры таблиц | `information_schema`, `pg_stat_user_tables`; только чтение |
| `seed/01_dev_seed.sql` | 1 объект, 2 газовых канала, 3 события для локальной разработки | Транзакция, `INSERT … ON CONFLICT DO NOTHING` |
| `init-dev.sh` | Поднимает `postgres`, ждёт готовности, применяет schema + indexes; с `--seed` — ещё seed; проверяет наличие таблиц | Bash, Docker Compose, `psql -v ON_ERROR_STOP=1` |

## Схема

| Таблица | Ключ | Основные колонки |
|---|---|---|
| `astra_objects` | `object_id` | `parent_id`, `hierarchy_level`, `object_type`, `display_name` |
| `astra_channels` | `sensor_id` | `engineering_system`, `sensor_type` (NOT NULL), `engineering_system_tag`, `sensor_name`, `object_id` → FK `astra_objects` |
| `ext_journal_prepared` | `event_id` | `sensor_id`, `occurred_at`, `value_type` ∈ {`numeric`,`binary`,`datetime`,`text`}, `numeric_value`, `datetime_value`, `text_value`, `alarm_raw`, `sensor_value_raw` |

Все скрипты идемпотентны (`IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`, `ON CONFLICT`).
Индексы создаются с `CONCURRENTLY`, поэтому их нельзя выполнять внутри транзакции.

## Использование

| Где | Что применяется |
|---|---|
| `compose.yaml`, сервис `db-init` (образ `postgres:16`) | Монтирует `./sql` в `/sql:ro`, ждёт PostgreSQL и выполняет `schema/01_core_schema.sql`, `indexes/01…`, `indexes/02…`. Seed при старте не применяется. `backend` стартует после успешного завершения `db-init`. |
| `sql/init-dev.sh` | Ручная инициализация: `./sql/init-dev.sh` или `./sql/init-dev.sh --seed`. Использует `scripts/docker-compose.sh`. |
| `diagnostics/` | Запускаются вручную через `psql`. |

Ручной запуск:

```bash
./sql/init-dev.sh --seed
docker compose exec -T postgres psql -U astra -d astra < sql/diagnostics/02_database_inventory.sql
```

## Ограничения

- `queries/*.sql` в коде не загружаются (ссылок из `backend/` и `ml/` нет); это справочные запросы.
- `queries/*.sql` используют русские имена колонок (`ид_события`, `ид_канала_данных`, `дата_время_события`, …), а `schema/01_core_schema.sql` — английские (`event_id`, `sensor_id`, `occurred_at`, …). На схеме из этой папки запросы не выполнятся; они соответствуют журналу, который строит [`../data_pipeline/sql/`](../data_pipeline/sql/).
- Полная сборка БД из исходных CSV — в [`../data_pipeline/`](../data_pipeline/).
