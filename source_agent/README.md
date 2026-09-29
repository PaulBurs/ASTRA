# source_agent

Source Agent — HTTP-сервис (FastAPI, Uvicorn, порт 9100), который подключает каталог с исходными CSV и отдаёт из него каналы и события. Backend обращается к нему по `SOURCE_AGENT_URL`.

## Файлы

| Файл | Назначение |
|---|---|
| `main.py` | Приложение FastAPI: подключение каталога, определение ролей CSV, фоновая подготовка кэша, чтение данных через `FileSensorRepository` / `FileMLDataRepository` из [`../backend/app/repositories/`](../backend/app/repositories/) |
| `paths.py` | `resolve_source_path()`: переводит путь хоста в путь внутри read-only монтирования и запрещает выход за его пределы |

## Как работает

1. `POST /source/connect` принимает `{"path": "..."}`, проверяет, что это каталог.
2. Роли CSV определяются по заголовку (`csv.Sniffer`, разделители `, ; \t |`, UTF-8 с BOM):
   - `channels`: `ид_канала_данных`, `тип_инж_системы`, `тип_датчика`, `ид_объект`;
   - `events`: `ид_события`, `ид_канала_данных`, `дата_время_события`, `тип_значения`;
   - `objects`: `ид_объект`, `иерархия_уровень`, `родитель`, `вид_объекта`, `диспетчерское_название_объекта`.
3. Подготовка кэша идёт в фоновом потоке. Состояния: `disconnected` → `preparing` → `connected` | `error`. Пока идёт подготовка, прежний источник скрыт.

## Эндпоинты

| Метод и путь | Ответ |
|---|---|
| `GET /health` | `status`, `source_state`, `source_connected` |
| `GET /source/status` | Состояние, путь, файлы по ролям, ошибка, число каналов |
| `POST /source/connect` | 200 — уже подключён; 202 — подготовка начата/идёт; 400 — путь недоступен или нет нужных CSV; 409 — готовится другой источник |
| `GET /data/sensors`, `GET /data/sensors/{sensor_id}` | Каналы; 404, если канал не найден |
| `GET /data/ml/{sensor_id}/latest` | Время последнего события канала |
| `GET /data/ml/{sensor_id}/events?start&end&limit=5000` | События канала в окне |

Эндпоинты `/data/*` возвращают 409, пока источник не в состоянии `connected`.

## Переменные окружения

| Переменная | Значение в `compose.yaml` | Назначение |
|---|---|---|
| `SOURCE_CACHE_PATH` | `/data/cache` (volume `source_cache`) | Каталог кэша; по умолчанию `~/.cache/astra/source-agent` |
| `SOURCE_MOUNT_ROOT` | `/data/source` | Корень read-only монтирования; если не задан, путь используется как есть |
| `SOURCE_HOST_ROOT` | `${ASTRA_SOURCE_DIR}` или `./DJKH_transport` | Путь хоста, заменяемый на `SOURCE_MOUNT_ROOT` |

## Запуск и использование

- Docker Compose: сервис `source-agent`, образ из `backend/Dockerfile`, команда `python -m source_agent.main`, healthcheck `GET /health`.
- Backend: [`../backend/app/api/data_source.py`](../backend/app/api/data_source.py) проксирует `/api/data-source/status` и `/api/data-source/connect`; `AgentSensorRepository` и `AgentMLDataRepository` используют `/data/*` при `DATA_SOURCE=agent` / `ML_DATA_SOURCE=agent` (в compose по умолчанию `postgres`).
- Тест `paths.py`: [`../backend/tests/test_source_paths.py`](../backend/tests/test_source_paths.py).
