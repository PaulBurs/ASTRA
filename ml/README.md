# ASTRA — ML

ML-сервис ASTRA: HTTP API прогноза тревог датчиков по подготовленным наборам данных в PostgreSQL
и код обучения модели. Сервис читает признаки из схемы набора, построенной
[data_pipeline](../data_pipeline/README.md), строит почасовые агрегаты и скользящие признаки,
скорит обученный LightGBM-бустер из `out_final/`. Обучение выполняется отдельно, CLI-скриптами
`djkh_model/`.

## Стек

- Python 3.13, FastAPI, Uvicorn, Pydantic — HTTP API и контракты.
- SQLAlchemy + psycopg (PostgreSQL) — чтение наборов данных, агрегация в SQL.
- pandas, NumPy — сборка признаков.
- LightGBM — модель прогноза; scikit-learn (IsolationForest, метрики) — детектор аномалий и оценка.
- DuckDB — агрегация исходных CSV/Parquet при обучении; Optuna — подбор гиперпараметров; matplotlib — графики.
- `concurrent.futures.ProcessPoolExecutor` (контекст `spawn`) — изоляция CPU-инференса.
- Зависимости от `data_pipeline`: `astra_pipeline.registry` (реестр наборов, имя схемы) и `lct_features` (контракт колонок).

## Структура

| Путь | Назначение |
|---|---|
| `src/` | ML-сервис (FastAPI) и инференс |
| `djkh_model/` | Обучение, проверки, улучшение и графики модели (CLI); справочники `dicts/*.csv` |
| `out_final/` | Итоговые артефакты модели, загружаемые сервисом, плюс отчёты и `plots/*.png` |
| `tools/` | Утилиты разработчика |
| `tests/` | Тесты инференса (`unittest`) |
| `artifacts/`, `notebooks/` | Пустые каталоги (`.gitkeep`) |
| `Dockerfile`, `requirements.txt` | Образ сервиса и зависимости |
| `setup.sh`, `check_env.py` | Создание `ml/.venv` и проверка установленных пакетов |
| `make_sample.py` | DuckDB: вырезает срез `sample_30.parquet` (N датчиков на тип, 2022–2026) из `data/dataset_ml_*.csv.gz` |
| `example.py` | Пример вызова заглушки `runtime.predict` |
| `.env.example` | Пример `ML_DATABASE_URL` (read-only пользователь) |

### `src/`

| Модуль | Роль и реализация |
|---|---|
| `api.py` | Приложение FastAPI `app` («ASTRA ML Service»); маппинг ошибок в HTTP 404/409/503; в `lifespan` останавливает пул воркеров. |
| `contracts.py` | Pydantic-модели: `PredictionInput`/`MLEvent`, `PredictionOutput` (`sensor_id`, `probability`, `horizon_hours`, `model_version`), `BatchPredictionInput` (1–4096 id), `BatchPredictionItem` (`ready`/`skipped`/`error`), `BatchPredictionOutput`, `HealthOutput`, `TrainOutput`. |
| `data.py` | SQLAlchemy-доступ к БД. `create_ml_engine()` — engine по `ML_DATABASE_URL` (`pool_pre_ping`); `get_sensor_ids()` — id из `astra_channels`; `iter_training_events()` — потоковое чтение `ext_journal_prepared` батчами (`stream_results`). |
| `datasets.py` | Работа с подготовленным набором. `prepared_dataset()` — проверка статуса `prepared`/`ready` в реестре; `iter_feature_batches()` — потоковое чтение `<schema>.v_dataset_ml`; `validate_dataset()` — сверка колонок с `lct_features.ALL_COLUMNS`, 5 строк примера. |
| `inference.py` | Инференс. `_load_model()` — загрузка `lgb.Booster` и `artifacts.json` (`lru_cache`), версия `lightgbm-<horizon>h-<sha256[:10]>`; `model_info()` — доступность модели; `predict_prepared_batch()` — для каждого датчика берёт последнее событие как `as_of`, окно `ML_PREDICTION_HISTORY_DAYS` + `episode_gap_h`, одним SQL-проходом (`_batch_aggregates`, `CROSS JOIN LATERAL` по индексу канал/время) считает почасовые агрегаты датчика и счётчики объекта, строит признаки `djkh_model.model.build_features`, вычитает события соседей после `as_of` (`_subtract_excess`), скорит бустером; `predict_prepared_dataset()` — вариант для одного датчика; `PredictionTargetNotFoundError`. Параллелизм ограничен `BoundedSemaphore`, скоринг — `Lock`. |
| `prediction_workers.py` | `run_prediction()` — выполнение инференса в `ProcessPoolExecutor` (`spawn`, `OMP_NUM_THREADS=1`), пересоздание пула после `BrokenProcessPool`; `shutdown_workers()`. |
| `runtime.py` | `health()`, `train()` (возвращает `not_started`: обучение вне сервиса), `predict()` — заглушка с фиксированной вероятностью 0.42 и версией `legacy-dummy-v1`. |

### `djkh_model/`

| Файл | Роль и реализация |
|---|---|
| `model.py` | Модель: DuckDB-агрегация событий в «датчик × час» (`aggregate_hourly`), плотная сетка часов (`Grid`), скользящие признаки и признаки объекта (`build_features`), цель — начало нового эпизода тревоги в горизонте; LightGBM (`train_lgb`), подбор порога, IsolationForest для аномалий. CLI `train` / `predict`. Сервис импортирует из него `build_features`. |
| `improve.py` | Сравнение наборов признаков, подбор гиперпараметров LightGBM (Optuna), модели-специалисты по группам типов; сохраняет результат в формате `model.py train`. |
| `checks.py` | Проверки: пересчёт нормировки (`значение_z`, `лог_dt_z`) в DuckDB, функции сетки против наивных циклов, скользящие средние, отсутствие утечки будущего. |
| `plots.py` | PNG-графики качества по папке результатов (PR-кривые, по типам, бюджет предупреждений, lead time, калибровка, по месяцам, важность). |
| `dicts/` | Справочники: `map_channel`, `map_object`, `map_complex`, `map_sensor_type`, `map_state`, `map_value_type`, `norm_params`, `window_params`. |
| `requirements.txt` | Зависимости для автономного запуска обучения. |

### `tools/`

| Файл | Назначение |
|---|---|
| `benchmark_inference.py` | Read-only сравнение батчевого инференса с эталонным путём «весь объект» (`reference()`): время и максимальная ошибка вероятности. `python -m ml.tools.benchmark_inference <DATASET_UUID> --limit 16` |

## HTTP API ML-сервиса

Порт 9000. Все методы — из `src/api.py`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Доступность модели и `model_version` (`unavailable`, если артефакты не загружаются) |
| POST | `/train` | Заглушка: `status=not_started`, обучение запускается отдельным конвейером |
| POST | `/predict` | Устаревшая заглушка по `PredictionInput` (вероятность 0.42, `legacy-dummy-v1`) |
| POST | `/datasets/{dataset_id}/validate` | Проверка подготовленного набора: статус, контракт колонок `v_dataset_ml`, пример строк |
| POST | `/datasets/{dataset_id}/predict/{sensor_id}` | Прогноз для одного датчика → `PredictionOutput` |
| POST | `/datasets/{dataset_id}/predict-batch` | Прогноз для списка `sensor_ids` → `BatchPredictionOutput`; отсутствующие датчики и датчики без истории — `skipped` |

Коды ошибок прогноза: 404 — набор/датчик не найден; 409 — набор не подготовлен, некорректный батч,
недостаточно истории признаков; 503 — БД, артефакты модели или пул воркеров недоступны.

## Модель

- Прогноз: вероятность того, что в ближайшие `horizon_h` часов (в `out_final` — 168 ч) у датчика
  начнётся новый эпизод тревоги (эпизоды разделяются паузой `episode_gap_h` = 6 ч).
- Вход при инференсе: таблицы `<schema>.dataset_ml` и `<schema>.map_channel` набора (схема —
  `astra_pipeline.registry.schema_name(dataset_id)`), история 90 дней до последнего события датчика;
  признаки датчика и соседей по объекту строит `djkh_model.model.build_features`.
- Артефакты загружаются из `ML_MODEL_DIR` (по умолчанию `ml/out_final/`):
  `lgb_model.txt` (LightGBM Booster), `artifacts.json` (`cfg`, `feat_cols`, порог, специалисты, пороги по типам).
  Сервис использует только общий бустер, `cfg` и `feat_cols`; порог и специалисты не применяются.
- Остальные файлы `out_final/` (`metrics.json`, `metrics_by_type.csv`, `feature_importance.csv`,
  `anomalies.csv`, `silence.csv`, `alarm_states.csv`, `plots/`) — отчёты обучения, сервисом не читаются.
- Метрики, устройство признаков и обучение: [README_MODEL.md](README_MODEL.md),
  [djkh_model/README.md](djkh_model/README.md).

## Конфигурация

| Переменная | По умолчанию | Где читается | Назначение |
|---|---|---|---|
| `ML_DATABASE_URL` | — (обязательна) | `data.py` | URL SQLAlchemy для PostgreSQL |
| `ML_MODEL_DIR` | `ml/out_final` | `inference.py` | Каталог с `lgb_model.txt` и `artifacts.json` |
| `ML_FORECAST_WORKERS` | 4 (1–16) | `prediction_workers.py`, `inference.py` | Число процессов инференса и параллельных запросов |
| `ML_MAX_BATCH_SENSORS` | 1024 | `inference.py` | Максимум датчиков в батче |
| `ML_PREDICTION_HISTORY_DAYS` | 90 (не меньше 90) | `inference.py`, `tools/benchmark_inference.py` | Глубина истории для признаков; должна помещаться в `feature_days` набора |
| `ML_INFERENCE_TEST_API` | — | `tests/test_sql_inference.py` | Базовый URL запущенного сервиса для HTTP-теста |

`PYTHONPATH` должен включать `data_pipeline` (в образе — `/opt/data_pipeline`).

## Запуск и тесты

```bash
# окружение
bash ml/setup.sh && source ml/.venv/bin/activate && python ml/check_env.py

# сервис (из корня репозитория)
export ML_DATABASE_URL=postgresql+psycopg://...  PYTHONPATH=data_pipeline
python -m uvicorn ml.src.api:app --host 0.0.0.0 --port 9000

# в составе стека: сервис ml в compose.yaml (образ ml/Dockerfile, python:3.13-slim + libgomp1)
docker compose up ml

# обучение (из ml/): см. README_MODEL.md
python djkh_model/model.py train --data sample_30.parquet --out out

# тесты
python -m unittest discover -s ml/tests -v
```

## Тесты

| Файл | Что проверяет |
|---|---|
| `tests/test_inference.py` | `build_features` с `target_channels` совпадает с построением по всему объекту, прогнозы бустера `out_final` идентичны; сетка строится только по целевым каналам, признаки соседей сохраняются. |
| `tests/test_sql_inference.py` | На PostgreSQL (пропускается без `ML_DATABASE_URL`): батчевый SQL-путь совпадает с эталоном, детерминизм при одновременных событиях, отказ при нехватке `feature_days`, воркеры single/batch, сохранение всех признаков в компактном SQL, параллельные HTTP-батчи (при `ML_INFERENCE_TEST_API`). |
| `tests/sql_fixture.py` | Контекстный менеджер `inference_dataset()`: временный детерминированный набор в реестре и схеме PostgreSQL, удаляется после теста. |
