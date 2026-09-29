# ml/src — прогноз по подготовленному набору

Описаны файлы, отвечающие за расчёт прогноза по схеме `ds_<uuid>`
(`data_pipeline/astra_pipeline`). Модель — LightGBM, горизонт 168 ч
(`ml/out_final`, признаки — `ml/djkh_model/model.py`).

## inference.py

Прогноз датчика считается на момент его последнего события по окну 90 дней
(`ML_PREDICTION_HISTORY_DAYS`) и счётчикам соседей по объекту. Пакет датчиков
обрабатывается за один проход: каждый объект читается один раз на пакет.

| Функция | Что делает | Как |
|---|---|---|
| `predict_prepared_batch(dataset_id, sensor_ids)` | Прогноз 1…`ML_MAX_BATCH_SENSORS` (1024) датчиков; статусы `ready`/`skipped` | SQLAlchemy, pandas, LightGBM `Booster.predict` |
| `predict_prepared_dataset(dataset_id, sensor_id)` | Прогноз одного датчика (обёртка над пакетом) | — |
| проверка `feature_days` в `predict_prepared_batch` | Отказ, если окну прогноза нужно больше истории, чем подготовлено признаков (`counts.feature_days` набора) | `ValueError` → HTTP 409 |
| `_batch_aggregates(conn, schema, targets, cfg)` | Почасовые агрегаты датчиков пакета в их собственных окнах; счётчики объектов по объединению окон; «лишние» события соседей в последнем часе датчика | `unnest` массивов параметров, `LATERAL` по индексу `(канал, время)`, оконная `max() FILTER` для начал эпизодов |
| `_subtract_excess(features, meta, excess)` | Вычитает из признаков `nbr_*` события соседей, пришедшие в последнем часе датчика после его последнего события | целочисленная арифметика float32 (точно) |
| `_hourly_aggregates(...)` | Агрегаты одного объекта на один момент — эталон для тестов и бенчмарка | SQL |
| `_event_columns`, `_hourly_columns`, `_sql_filters` | Общие SQL-выражения события и часа (тревога, неисправность, статистики) | те же правила, что `model.aggregate_hourly` |
| `LAST_EVENT_ORDER` | Детерминированный выбор последнего события часа при равном времени: тревога, затем больший код состояния | `array_agg(... ORDER BY ...)` |
| `_load_model`, `model_info` | Загрузка `lgb_model.txt` и `artifacts.json`, версия `lightgbm-<H>h-<sha256>` | `lru_cache`, `hashlib` |
| `bounded_inference` | Ограничение одновременных расчётов (`ML_FORECAST_WORKERS`) | `threading.BoundedSemaphore` |

Результат пакетного пути совпадает с расчётом по одному датчику
(`ml/tests/test_sql_inference.py`, допуск 1e-12).

## contracts.py

Pydantic-модели API ML-сервиса. `BatchPredictionInput.sensor_ids` — до 4096 элементов
(жёсткая граница схемы); рабочий предел задаёт `ML_MAX_BATCH_SENSORS`.

## Связанные файлы вне ml/src

- `ml/djkh_model/model.py`, `Grid` — конец сетки часов задаётся отдельно для каждого
  канала (`end_h: pd.Series`), чтобы пакет с разными моментами прогноза строился за один
  вызов `build_features`.
- `ml/tools/benchmark_inference.py` — сравнение пакетного пути с эталоном
  (`reference`) по времени и вероятностям; только чтение БД.
- `ml/tests/test_sql_inference.py` — эквивалентность пакета эталону на всём фикстурном
  наборе, одинаковое время событий, один проход агрегации на пакет.
