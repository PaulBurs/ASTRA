# ASTRA Backend

REST API системы ASTRA. Принимает CSV-выгрузки, запускает их подготовку в изолированной схеме PostgreSQL (библиотека `astra_pipeline` из [../data_pipeline](../data_pipeline/README.md)), проксирует запросы прогноза в ML-сервис ([../ml](../ml/README.md)) и хранит прогнозы и проверки датчиков. Обслуживает фронтенд ([../frontend](../frontend/README.md)).

**Стек:** Python 3.13, FastAPI, Starlette, Pydantic v2, SQLAlchemy 2 (Core, `text()`), psycopg 3, PostgreSQL 16, httpx, DuckDB + Parquet, openpyxl, python-dotenv, uvicorn, pytest.

## Структура

```text
backend/
├── main.py            FastAPI-приложение, CORS (localhost:5173), подключение роутеров
├── Dockerfile         python:3.13-slim + data_pipeline, ml/src, source_agent; uvicorn :8000
├── requirements.txt
├── .env.example
├── app/
│   └── api/  core/  db/  data_sources/  ml/  repositories/  schemas/  services/
└── tests/
```

### api — HTTP-слой (FastAPI `APIRouter`)

| Файл | Назначение |
|---|---|
| `health.py` | Состояние БД и ML через `HealthService`. |
| `sensors.py` | Список и карточка датчика через `SensorService`. |
| `dashboard.py` | Сводка для панели диспетчера (`DashboardService`). |
| `ml.py` | Health/train ML; прогноз по датчику: при `dataset_id` — через ML-сервис с сохранением в `astra_predictions`, иначе — через `PredictionService`. |
| `data_source.py` | Прокси к Source Agent (httpx); 502 при его недоступности. |
| `datasets.py` | Жизненный цикл импорта: создание набора, потоковая загрузка файлов, запуск подготовки (`BackgroundTasks`), проверка ML, удаление. Валидация файлов — Pydantic `field_validator`. |
| `live_workspace.py` | Рабочее место по подготовленному набору: каталог, карточка датчика (20 последних событий, история, прогноз), пакетные прогнозы, проверки. Роль — по заголовку `X-Employee-Id` (`1001` — диспетчер, `2001`/`2002` — техспециалисты; идентификация, не аутентификация). Таблицы `astra_checks`, `astra_check_history` создаются лениво (`CREATE TABLE IF NOT EXISTS` под `pg_advisory_xact_lock`); оптимистическая блокировка по `revision`, `SELECT … FOR UPDATE`. |

### core
- `dependencies.py` — DI-фабрики (FastAPI `Depends`). Реализация репозиториев выбирается по `DATA_SOURCE` / `ML_DATA_SOURCE` (`dummy|file|agent|postgres`), ML-сервиса — по `ML_SERVICE_URL` (HTTP или заглушка). `get_sensor_repository` / `get_ml_data_repository` при query-параметре `dataset_id` возвращают `Prepared*`-репозитории; `require_prepared_dataset` — 404/409, если набора нет или он не в статусе `prepared|ready`.

### db
- `database.py` — единый SQLAlchemy `engine` из `DATABASE_URL` (обязателен, иначе `RuntimeError` при импорте); `check_database_connection()` — `SELECT 1`.

### data_sources — read-only чтение внешних файлов
- `duckdb_event_source.py` — `DuckDBEventSource`: запросы DuckDB напрямую к CSV `ext_journal_prepared`; кэш последних событий по датчикам в Parquet (перестроение под `threading.Lock`).
- `file_source.py` — `FileDataSource`: перечисление и предпросмотр CSV/XLSX (csv, openpyxl).

### ml — контракт backend ↔ ML
- `service.py` — абстрактный `MLService` (`health`, `train`, `predict`, `predict_dataset`).
- `http_service.py` — `HTTPMLService`: httpx-клиент ML-сервиса (`/health`, `/train`, `/predict`, `/datasets/{id}/predict/{sensor}`, `/datasets/{id}/predict-batch`).
- `dummy.py` — `DummyMLService`, фиксированный ответ (разработка, тесты).
- `contracts.py` — Pydantic-модели входа прогноза `MLPredictionInput`, `MLEvent`.

### repositories — доступ к данным (паттерн Repository, ABC)

| Интерфейс | Назначение | Реализации |
|---|---|---|
| `SensorRepository` | `get_all`, `get_by_id` | `Dummy`, `File` (CSV каналов + DuckDB), `Agent` (HTTP к Source Agent), `Postgres` (`astra_channels` + `ext_journal_prepared`), `PreparedSensorRepository` |
| `MLDataRepository` | история событий датчика для inference (≤ 5000) | `Dummy`, `File` (DuckDB, Parquet-кэш за 24 ч), `Agent`, `Postgres`, `PreparedMLDataRepository` |
| `SensorCatalogRepository` | фильтр каналов по инж. системе/типу, метаданные | `Dummy`, `File`, `Postgres` |
| `TrainingDataRepository` | потоковая выдача истории батчами | `Dummy`, `Postgres` (`stream_results`, `yield_per`, `fetchmany`) |

`prepared_dataset_repository.py` — адаптеры к схеме подготовленного набора (`ref_channels`, `latest_sensor_events`, `ext_journal_prepared`; имя схемы — `astra_pipeline.registry.schema_name`). `PostgresSensorRepository._to_sensor` — общее преобразование строки в формат `SensorResponse` (значение по `value_type`; `status`/`risk` пока фиксированы: `OK`/`0.0`).

### schemas — Pydantic-модели ответов
`health.py` (`HealthResponse`), `sensor.py` (`SensorResponse`), `dashboard.py` (`DashboardResponse`, `DashboardSummary`), `ml.py` (`MLHealthResponse`, `MLTrainResponse`, `MLPredictionResponse`: `probability ∈ [0,1]`, `horizon_hours ≥ 24`).

### services — бизнес-логика
- `dataset_import_service.py` — `DatasetImportService`: реестр наборов `public.astra_datasets` (статусы `uploading → preparing → prepared → ready | error`); загрузка одного файла на запрос потоком `request.stream()` в `<DATASET_UPLOAD_DIR>/<uuid>/` с контролем размера и определением роли файла (`detect_role`); проверка свободного места (`shutil.disk_usage`, 507); блокировки `fcntl.flock` (на набор и глобальная — одна подготовка за раз); сборка через `astra_pipeline.build.build_dataset`; проверка чтения ML (`POST {ML_SERVICE_URL}/datasets/{id}/validate`, сверка `row_count`); восстановление статуса после перезапуска процесса; удаление — `DROP SCHEMA … CASCADE` + каскад FK.
- `forecast_jobs.py` — очередь пакетных прогнозов: таблицы `astra_predictions`, `astra_forecast_jobs`; одна задача на ML-сервис через сессионный `pg_try_advisory_lock` (освобождается при падении процесса); фоновый `Thread` + `ThreadPoolExecutor` с ограниченным числом батчей в работе; upsert `ON CONFLICT`; кооперативная остановка (`stopping`) и возобновление с переиспользованием готовых результатов; взаимоисключение с подготовкой данных (`preparing()` / `running()`).
- `prediction_service.py` — `PredictionService`: окно истории 24 ч до последнего события → `MLPredictionInput` → `MLService.predict`.
- `dashboard_service.py`, `health_service.py`, `sensor_service.py` — сводка по статусам, состояние компонентов, тонкий слой над `SensorRepository`.
- `ml_training_data_service.py` — `MLTrainingDataService`: выбор каналов по каталогу и потоковая выдача обучающих событий (роутерами не используется).

## REST API

OpenAPI — `/docs`. `{id}` — UUID набора. `?dataset_id=` у `/api/sensors*`, `/api/dashboard`, `/api/ml/predict` переключает источник на подготовленный набор.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | Статус приложения |
| GET | `/api/health` | Состояние БД и ML |
| GET | `/api/sensors` | Список датчиков |
| GET | `/api/sensors/{sensor_id}` | Датчик по ID |
| GET | `/api/dashboard` | Сводка и датчики для панели |
| GET | `/api/ml/health` | Доступность ML |
| POST | `/api/ml/train` | Запуск обучения в ML-сервисе |
| GET | `/api/ml/predict/{sensor_id}` | Прогноз; с `dataset_id` — по набору с сохранением |
| GET | `/api/data-source/status` | Статус Source Agent (прокси) |
| POST | `/api/data-source/connect` | Подключение пути к исходным данным (прокси) |
| POST | `/api/datasets` | Создание набора: 3–32 CSV (имя, размер) |
| GET | `/api/datasets/{id}` | Статус импорта |
| PUT | `/api/datasets/{id}/files/{index}` | Загрузка файла телом запроса |
| POST | `/api/datasets/{id}/prepare` | Запуск подготовки (202) |
| POST | `/api/datasets/{id}/validate-ml` | Повторная проверка чтения ML |
| DELETE | `/api/datasets/{id}` | Удаление; `?confirm_delete=true` — подготовленного (только `1001`) |
| GET | `/api/datasets/{id}/workspace` | Датчики, объекты, проверки (фильтр по роли) |
| GET | `/api/datasets/{id}/sensors/{sensor_id}` | Карточка: события, проверки, история, прогноз |
| GET | `/api/datasets/{id}/forecasts` | Последняя задача и все прогнозы |
| GET | `/api/datasets/{id}/forecasts/job` | Только состояние задачи (для опроса) |
| POST | `/api/datasets/{id}/forecasts` | Пакетный прогноз по всем датчикам (202) |
| POST | `/api/datasets/{id}/forecasts/stop` | Остановка расчёта (диспетчер) |
| POST | `/api/datasets/{id}/checks` | Назначение проверки (диспетчер) |
| PATCH | `/api/datasets/{id}/checks/{check_id}` | `start` / `complete` проверки (исполнитель) |

## Конфигурация

Переменные окружения; `.env` подгружается `python-dotenv` (шаблон — `.env.example`).

- `DATABASE_URL` — строка подключения SQLAlchemy (`postgresql+psycopg://…`), обязательна.
- `DATA_SOURCE` — источник датчиков: `dummy` (по умолчанию) | `file` | `agent` | `postgres`.
- `ML_DATA_SOURCE` — источник истории для ML и каталога каналов: те же значения (`agent` — только для истории).
- `ML_SERVICE_URL` — базовый URL ML-сервиса; пусто — `DummyMLService`, проверка ML после импорта не проходит.
- `SOURCE_AGENT_URL` — URL Source Agent (по умолчанию `http://host.docker.internal:9100`).
- `SOURCE_DATA_PATH` — каталог исходных CSV/XLSX для режима `file` (по умолчанию `/data/source`).
- `SOURCE_CACHE_PATH` — каталог Parquet-кэшей DuckDB (по умолчанию `/data/cache`).
- `DATASET_UPLOAD_DIR` — каталог загружаемых файлов (по умолчанию `<repo>/data/uploads`).
- `DATASET_MAX_UPLOAD_BYTES` — лимит суммарного размера набора (по умолчанию 64 ГиБ).
- `DATASET_STORAGE_EXPANSION_FACTOR` — множитель оценки пикового объёма на диске (≥ 2, по умолчанию 8).
- `DATASET_STORAGE_RESERVE_BYTES` — резерв свободного места (по умолчанию 2 ГиБ).
- `FORECAST_WORKERS` — параллельных батчей прогноза (1–16, по умолчанию 4).
- `FORECAST_BATCH_SIZE` — датчиков в батче (1–1024, по умолчанию 256).

Параметры сборки (`DATASET_BUILD_WORKERS`, `DATASET_WORK_MEM_MB`, `DATASET_MAINTENANCE_MEM_MB`, `DATASET_FEATURE_DAYS` и др.) читает `astra_pipeline` в том же процессе — см. [../data_pipeline/README.md](../data_pipeline/README.md).

## Запуск и тесты

```bash
docker compose up --build backend        # из корня репозитория; поднимает postgres, ml, source-agent
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
cd backend && pytest -v                  # нужен PostgreSQL по DATABASE_URL
```

## Тесты

- `conftest.py` — добавляет корень репозитория и `data_pipeline` в `sys.path`.
- `test_health.py` — `GET /api/health` при доступных БД и ML.
- `test_sensors.py` — список, структура, диапазон `risk`, датчик по ID, 404.
- `test_dashboard.py` — сводка и структура датчиков панели.
- `test_ml.py` — ML health/train/predict и деградация health при недоступном ML (`dependency_overrides`).
- `test_prediction_service.py` — передача окна истории в ML; ошибки «нет датчика» / «нет истории».
- `test_sensor_service.py` — делегирование `SensorService` репозиторию.
- `test_sensor_repository.py` — `DummySensorRepository`.
- `test_sensor_value_mapping.py` — `_to_sensor` для numeric/binary/text/datetime и датчика без событий.
- `test_sensor_catalog_repository.py` — фильтры и метаданные каталога каналов.
- `test_training_data_repository.py` — батчи и структура событий обучающего репозитория.
- `test_ml_training_data_service.py` — выбор каналов и потоковая выдача обучающих событий.
- `test_dataset_import.py` — интеграция: загрузка → реальный SQL пайплайна → реальный ML-ридер; валидация, повтор проверки ML, прерывание, удаление.
- `test_pipeline_equivalence.py` — точная эквивалентность SQL-признаков (окна, границы годов, дубликаты, NULL), параллельные воркеры, fail-closed при изменении плана.
- `test_live_workspace.py` — рабочее место и проверки; пакетные прогнозы: параллелизм, частичные ошибки, остановка/возобновление, восстановление после рестарта, отказ от некорректного батча.
- `test_forecast_preparation_exclusion.py` — взаимоисключение прогноза и подготовки данных.
- `test_source_paths.py` — разрешение путей Source Agent (монтирование, выход за корень, symlink).
