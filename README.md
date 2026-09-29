# ASTRA

ASTRA — веб-сервис для мониторинга инженерной инфраструктуры, оценки текущего состояния датчиков и интеграции прогнозной ML-модели риска аварий.

Проект собирается как единая система из нескольких независимых частей:

- **Frontend** — интерфейс диспетчера на React + TypeScript + Vite.
- **Backend** — REST API на FastAPI.
- **PostgreSQL** — база данных проекта.
- **ML** — отдельная рабочая зона для исследования данных, обучения модели и подготовки артефактов.
- **Docker Compose** — локальный запуск PostgreSQL, backend и frontend.
- **GitHub Actions** — автоматические проверки backend и frontend при push / Pull Request.

На текущем этапе ASTRA представляет собой интеграционный каркас: архитектура, API-контракты, UI, тесты, Docker и CI уже работают, но реальная база данных и реальная ML-модель подключаются отдельными разработчиками.

---

## Содержание

1. [Архитектура](#архитектура)
2. [Структура репозитория](#структура-репозитория)
3. [Технологии](#технологии)
4. [Быстрый старт](#быстрый-старт)
5. [Запуск одной командой](#запуск-одной-командой)
6. [Docker](#docker)
7. [Frontend](#frontend)
8. [Backend](#backend)
9. [ML](#ml)
10. [База данных](#база-данных)
11. [REST API](#rest-api)
12. [Импорт данных](#импорт-данных)
13. [Тесты](#тесты)
14. [GitHub Actions](#github-actions)
15. [Git workflow](#git-workflow)
16. [Правила разработки](#правила-разработки)
17. [Переменные окружения](#переменные-окружения)
18. [Что уже реализовано](#что-уже-реализовано)
19. [Что пока является заглушкой](#что-пока-является-заглушкой)
20. [Типовые сценарии разработки](#типовые-сценарии-разработки)
21. [Полезные команды](#полезные-команды)

---

# Архитектура

Общая схема приложения:

```text
┌──────────────────────────────┐
│        React Frontend        │
│   TypeScript + Vite          │
└──────────────┬───────────────┘
               │ REST / JSON
               ▼
┌──────────────────────────────┐
│          FastAPI             │
│            API               │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│        Service Layer         │
│                              │
│ SensorService                │
│ PredictionService            │
│ DashboardService             │
│ HealthService                │
│ ImportService                │
└─────────┬───────────┬────────┘
          │           │
          ▼           ▼
┌────────────────┐  ┌────────────────┐
│ SensorRepository│  │   MLService    │
└───────┬────────┘  └───────┬────────┘
        │                   │
        ▼                   ▼
┌────────────────┐  ┌────────────────┐
│ PostgreSQL     │  │ Real ML model  │
│ implementation│  │ implementation │
└────────────────┘  └────────────────┘
```

Основной принцип проекта:

```text
Frontend не знает структуру PostgreSQL.
Backend API не знает внутреннее устройство ML-модели.
ML-код не должен зависеть от HTTP/UI.
Бизнес-логика не должна находиться внутри REST endpoint-ов.
```

Это позволяет frontend-, backend-, DB- и ML-разработчикам работать параллельно.

---

# Структура репозитория

```text
ASTRA/
├── .github/
│   └── workflows/
│       └── backend-tests.yml
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── dashboard.py
│   │   │   ├── health.py
│   │   │   ├── import_data.py
│   │   │   ├── ml.py
│   │   │   └── sensors.py
│   │   │
│   │   ├── core/
│   │   │   └── dependencies.py
│   │   │
│   │   ├── db/
│   │   │   └── database.py
│   │   │
│   │   ├── ml/
│   │   │   ├── service.py
│   │   │   └── dummy.py
│   │   │
│   │   ├── repositories/
│   │   │   ├── sensor_repository.py
│   │   │   └── dummy_sensor_repository.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── dashboard.py
│   │   │   ├── health.py
│   │   │   ├── import_data.py
│   │   │   ├── ml.py
│   │   │   └── sensor.py
│   │   │
│   │   └── services/
│   │       ├── dashboard_service.py
│   │       ├── health_service.py
│   │       ├── import_service.py
│   │       ├── prediction_service.py
│   │       └── sensor_service.py
│   │
│   ├── tests/
│   ├── .env.example
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── dashboard.ts
│   │   │   ├── health.ts
│   │   │   ├── ml.ts
│   │   │   └── sensors.ts
│   │   │
│   │   ├── components/
│   │   │   ├── ImportPanel.tsx
│   │   │   ├── PredictionButton.tsx
│   │   │   └── SensorDetails.tsx
│   │   │
│   │   ├── App.tsx
│   │   ├── App.css
│   │   └── config.ts
│   │
│   ├── .env.example
│   ├── Dockerfile
│   ├── package.json
│   └── package-lock.json
│
├── ml/
│   ├── src/
│   │   └── __init__.py
│   ├── notebooks/
│   ├── artifacts/
│   │   └── .gitkeep
│   └── README.md
│
├── data/
├── docs/
│
├── compose.yaml
├── astra.sh
├── launch-astra.sh
├── README.md
└── .gitignore
```

Структура может расширяться, но границы зон ответственности желательно сохранять.

---

# Технологии

## Backend

- Python 3.13
- FastAPI
- Pydantic
- SQLAlchemy
- psycopg
- pytest

## Frontend

- Node.js 22
- React
- TypeScript
- Vite

## Infrastructure

- PostgreSQL 16
- Docker
- Docker Compose
- GitHub Actions
- Linux / Fedora как основная локальная среда разработки

> Скрипты проекта автоматически поддерживают оба варианта Docker Compose:
> современный плагин `docker compose` и старую команду `docker-compose`.
> Дополнительная shell-функция или alias не требуется.

---

# Быстрый старт

На компьютере нужен Bash. Docker Engine с Docker Compose `./astra.sh` в Linux
установит сам, если их нет (см. ниже). Локальные Node.js, npm, Python, `.venv`
и PostgreSQL для запуска не требуются.

После клонирования репозитория из его корня выполните:

```bash
./astra.sh
```

Первый запуск соберёт образы, установит зависимости внутри контейнеров, поднимет
PostgreSQL, создаст пустую схему и запустит Source Agent, ML, backend и frontend.
Нужен интернет для загрузки базовых образов и зависимостей. Последующие сборки
используют Docker-кэш. Тесты при обычном запуске не выполняются.

Если текущему пользователю недоступен системный Docker socket, скрипт выполнит
Docker-команды через `sudo` и при необходимости запросит пароль. Запускать весь
скрипт через `sudo`, менять права на `docker.sock` или вручную объявлять shell-функции
не требуется. Если служба системного Docker остановлена, скрипт попытается запустить
её через systemd. Для недоступного rootless/remote/Desktop context выводится ошибка:
скрипт не переключает его на другой Docker.

На некоторых Ubuntu с Docker из snap AppArmor запрещает Docker останавливать
контейнеры, поэтому даже `sudo docker stop` завершается сообщением
`cannot stop container: permission denied`. `./astra.sh` распознаёт этот точный
сбой, останавливает только процессы контейнеров текущего проекта и повторяет
команду один раз. PostgreSQL volume и загруженная база при этом сохраняются;
чужие контейнеры не затрагиваются. Автовосстановление можно отключить через
`ASTRA_AUTO_REPAIR_DOCKER=0`. Если восстановление невозможно, launcher выводит
ссылку на известную проблему пакета Docker для Ubuntu и завершает работу без
ложного сообщения об успешном запуске.

Если Docker ещё не установлен, `./astra.sh` в Linux установит его сам:
скачает официальный скрипт [get.docker.com](https://get.docker.com) (Ubuntu, Debian,
Fedora, RHEL, CentOS), установит Docker Engine и Docker Compose plugin через `sudo`,
включит службу `docker` и добавит пользователя в группу `docker` (без `sudo` —
после повторного входа в систему; текущий запуск продолжится через `sudo`).
Если Docker есть, а Docker Compose нет, скрипт установит официальный Compose plugin
в `/usr/local/lib/docker/cli-plugins`. Для установки нужны интернет, `curl` или
`wget` и пароль администратора.

Автоустановку можно отключить: `ASTRA_AUTO_INSTALL_DOCKER=0 ./astra.sh`. В macOS
и Windows установите [Docker Desktop](https://docs.docker.com/desktop/) вручную.

После проверки готовности сервисов откроется приложение:

- Frontend: http://127.0.0.1:5173
- API/Swagger: http://127.0.0.1:8000/docs

В режиме v1.0.1 данные появятся после загрузки CSV через вкладку «Данные».
Демонстрационные строки при запуске в PostgreSQL не добавляются.

# Запуск одной командой

```bash
./astra.sh           # обычный запуск; сборка с кэшем
./astra.sh quick     # ежедневный запуск готовых образов
./astra.sh check     # backend-тесты + frontend build/lint/test в контейнерах
./astra.sh rebuild   # пересборка образов и запуск
./astra.sh stop      # остановка с сохранением БД
./astra.sh status    # состояние сервисов
./astra.sh logs      # журнал сервисов
```

`./run.sh` вызывает тот же launcher и передаёт аргументы.
`./build.sh` выполняет `./astra.sh check`. Проверки не добавляют тестовые датчики
в пользовательскую БД и не останавливают уже работающие сервисы.

`quick` соберёт недостающие образы на новом компьютере автоматически. После
обновления зависимостей или Dockerfile используйте обычный запуск или `rebuild`.
Настройки для Compose можно поместить в необязательный корневой `.env`
(пример — `.env.example`). Объявлять `DATABASE_URL` для штатного запуска не нужно.

Для запуска без открытия браузера:

```bash
ASTRA_OPEN_BROWSER=0 ./astra.sh
```

Проверка готовности ограничена 180 секундами после запуска контейнеров; при ошибке
выводятся состояние и последние логи. Лимит можно изменить переменной
`ASTRA_WAIT_TIMEOUT`. Загрузка и сборка образов в этот лимит не входят.

## Каталог для Source Agent

Source Agent также работает в Docker и доступен backend по внутренней сети.
Загрузка CSV через браузер работает с файлами из любой доступной пользователю папки.
Для старого API подключения готовой папки по пути по умолчанию доступен каталог
`DJKH_transport/` внутри проекта, смонтированный только для чтения в `/data/source`.

Для другой папки укажите абсолютный путь в корневом `.env`:

```dotenv
ASTRA_SOURCE_DIR=/home/user/data/archive
```

После этого выполните `./astra.sh`. API принимает исходный абсолютный путь или
путь внутри `/data/source`; кэш Source Agent сохраняется в отдельном Docker volume.

Локальные команды npm/pip/venv в дальнейших разделах нужны только при разработке
вне контейнеров, а не для обычного запуска проекта.

---

# Docker

Основные сервисы описаны в:

```text
compose.yaml
```

Запускаются:

```text
postgres
backend
frontend
```

## PostgreSQL

```text
localhost:5432
```

## Backend

```text
localhost:8000
```

Backend работает с Uvicorn в режиме reload. Исходники backend подключены в контейнер через bind mount.

Поэтому обычное изменение Python-кода:

```text
изменить файл
   ↓
Ctrl+S
   ↓
Uvicorn автоматически перезапускается
```

Пересобирать Docker-образ не требуется.

## Frontend

```text
localhost:5173
```

Frontend работает через Vite dev server. `frontend/src` подключён через bind mount.

При сохранении `.ts`, `.tsx` и `.css` Vite автоматически обновляет приложение.

## Важно для Fedora / SELinux

В `compose.yaml` bind mounts могут использовать суффикс:

```text
:Z
```

Он нужен для корректной работы volume-монтирования при включённом SELinux.

---

# Frontend

Зона frontend-разработчика:

```text
frontend/
```

Frontend должен работать **только через REST API**.

Он не должен:

- знать структуру PostgreSQL;
- напрямую читать файлы ML;
- содержать SQL;
- дублировать backend-бизнес-логику.

## API-клиенты

Все обращения к backend следует размещать в:

```text
frontend/src/api/
```

Например:

```text
frontend/src/api/dashboard.ts
frontend/src/api/sensors.ts
frontend/src/api/ml.ts
```

Компоненты React не должны содержать повторяющийся `fetch()` по всему проекту.

## Компоненты

Переиспользуемый UI следует размещать в:

```text
frontend/src/components/
```

Примеры:

```text
ImportPanel.tsx
PredictionButton.tsx
SensorDetails.tsx
```

## Конфигурация API

Используется:

```text
frontend/src/config.ts
```

URL backend берётся из:

```env
VITE_API_URL=http://127.0.0.1:8000
```

Не хардкодить API URL в компонентах.

## Проверка frontend

```bash
cd frontend
npm run build
```

Pull Request не должен мержиться, если TypeScript/Vite build не проходит.

---

# Backend

Зона backend-разработчика:

```text
backend/
```

Backend разделён на слои.

## API layer

```text
backend/app/api/
```

Здесь находятся HTTP endpoints.

Задачи API layer:

- принять HTTP-запрос;
- проверить параметры через FastAPI/Pydantic;
- вызвать service layer;
- вернуть HTTP-ответ;
- преобразовать доменные ошибки в HTTP-коды.

В API не следует писать SQL или сложную бизнес-логику.

Пример правильной цепочки:

```text
GET /api/ml/predict/56682
        ↓
api/ml.py
        ↓
PredictionService
        ↓
SensorRepository + MLService
```

## Service layer

```text
backend/app/services/
```

Здесь находится бизнес-логика.

Например:

```text
SensorService
PredictionService
DashboardService
HealthService
ImportService
```

Если логика не относится непосредственно к HTTP, она должна находиться здесь или в отдельном доменном модуле.

## Schemas

```text
backend/app/schemas/
```

Pydantic-схемы определяют контракт REST API.

Изменение schema может сломать frontend, поэтому такие изменения необходимо согласовывать с frontend-разработчиком.

## Dependencies

```text
backend/app/core/dependencies.py
```

Это центральная точка подключения реализаций.

Сейчас здесь выбираются:

- `MLService`;
- `SensorRepository`.

При переходе с dummy-реализации на реальную желательно менять именно dependency wiring, а не переписывать API.

---

# ML

Основная зона ML-разработчиков:

```text
ml/
```

Подробная ML-инструкция:

```text
ml/README.md
```

## Важное различие

В проекте существуют две директории с `ml` в названии, и у них разные задачи.

### `ml/`

Рабочая зона ML-команды:

```text
ml/src/
ml/notebooks/
ml/artifacts/
```

Здесь выполняются:

- анализ данных;
- feature engineering;
- preprocessing;
- обучение;
- валидация;
- эксперименты;
- подготовка артефакта модели.

### `backend/app/ml/`

Интеграционный слой backend ↔ ML.

Содержит контракт:

```text
backend/app/ml/service.py
```

и текущую тестовую реализацию:

```text
backend/app/ml/dummy.py
```

ML-разработчик не должен переносить весь training pipeline внутрь FastAPI endpoint-а.

## MLService

Текущий интерфейс ожидает:

```python
class MLService:
    def health(self) -> bool:
        ...

    def train(self) -> dict:
        ...

    def predict(self, sensor_id: int) -> dict:
        ...
```

### `predict()`

Ожидаемый результат:

```json
{
  "sensor_id": 56682,
  "probability": 0.42,
  "horizon_hours": 24,
  "model_version": "model-v1"
}
```

Ограничения API-контракта:

```text
0.0 <= probability <= 1.0
horizon_hours >= 24
```

## Подключение реальной модели

Рекомендуемый путь:

```text
backend/app/ml/real.py
```

с реализацией `MLService`.

После этого dependency в:

```text
backend/app/core/dependencies.py
```

переключается с `DummyMLService` на реальную реализацию.

Если модель хранится в `ml/artifacts`, необходимо отдельно обеспечить backend доступ к артефакту через Docker volume, копирование в image или отдельный model-service. Не следует делать скрытую зависимость от локального пути разработчика.

---

# База данных

Backend уже подключён к PostgreSQL через SQLAlchemy.

Подключение:

```text
backend/app/db/database.py
```

Переменная:

```env
DATABASE_URL=postgresql+psycopg://astra:astra@localhost:5432/astra
```

В Docker backend использует имя сервиса PostgreSQL:

```text
postgres
```

а не `localhost`.

## Repository pattern

Backend не должен обращаться к SQL напрямую из API.

Контракт датчиков:

```text
backend/app/repositories/sensor_repository.py
```

Текущая реализация:

```text
backend/app/repositories/dummy_sensor_repository.py
```

DB-разработчику рекомендуется реализовать, например:

```text
backend/app/repositories/postgres_sensor_repository.py
```

с тем же интерфейсом:

```python
def get_all(self) -> list[dict]:
    ...


def get_by_id(self, sensor_id: int) -> dict | None:
    ...
```

После реализации необходимо переключить dependency в:

```text
backend/app/core/dependencies.py
```

API и service layer при этом менять не должны.

---

# REST API

Интерактивная документация FastAPI:

```text
http://127.0.0.1:8000/docs
```

## System

### `GET /api/health`

Проверка состояния ASTRA.

Пример:

```json
{
  "status": "ok",
  "application": "ASTRA",
  "database": "connected",
  "ml": "available"
}
```

---

## Dashboard

### `GET /api/dashboard`

Возвращает агрегированные данные для диспетчерской панели:

```json
{
  "system": {
    "status": "ok",
    "application": "ASTRA",
    "database": "connected",
    "ml": "available"
  },
  "summary": {
    "total_sensors": 3,
    "ok": 1,
    "warning": 1,
    "critical": 1,
    "max_risk": 0.91
  },
  "sensors": []
}
```

Frontend рекомендуется строить прежде всего вокруг этого endpoint-а для основной панели.

---

## Sensors

### `GET /api/sensors`

Список датчиков.

### `GET /api/sensors/{sensor_id}`

Один датчик.

Если датчик не существует:

```text
404 Sensor not found
```

Пример датчика:

```json
{
  "id": 56682,
  "name": "МК-1.1.1.1.1.1",
  "type": "temperature",
  "value": 25.0,
  "status": "OK",
  "risk": 0.12
}
```

---

## ML

### `GET /api/ml/health`

Проверяет доступность ML-компонента.

### `POST /api/ml/train`

Текущий контракт запуска обучения.

### `GET /api/ml/predict/{sensor_id}`

Возвращает ML-прогноз для существующего датчика.

Для неизвестного датчика возвращается `404`.

---

## Import

### `POST /api/import`

Принимает файл данных.

Поддерживаемые расширения:

```text
.csv
.xls
.xlsx
```

На текущем этапе endpoint проверяет формат и принимает файл, но полноценный parsing + запись в PostgreSQL ещё не реализованы.

---

# Импорт данных

Код:

```text
backend/app/services/import_service.py
```

Frontend:

```text
frontend/src/components/ImportPanel.tsx
```

Сейчас поток выглядит так:

```text
пользователь выбирает файл
        ↓
frontend
        ↓
POST /api/import
        ↓
FastAPI UploadFile
        ↓
ImportService
        ↓
проверка расширения
        ↓
успешный ответ
```

Будущая реализация должна добавить:

```text
чтение CSV/XLS/XLSX
        ↓
валидация колонок
        ↓
нормализация данных
        ↓
запись в PostgreSQL
        ↓
отчёт об ошибках / количестве записей
```

Эту логику следует добавлять в service/repository layer, а не в React.

---

# Тесты

Backend tests:

```text
backend/tests/
```

Запуск:

```bash
cd backend
source .venv/bin/activate
pytest -v
```

Или без активации окружения:

```bash
backend/.venv/bin/python -m pytest -v
```

Важно запускать pytest из `backend/`, если используется активированное virtualenv.

## PostgreSQL и health test

Тест `/api/health` проверяет реальное соединение с PostgreSQL.

Поэтому локально PostgreSQL должен быть запущен:

```bash
cd ..
docker compose up -d postgres
```

После чего:

```bash
cd backend
pytest -v
```

## Frontend check

```bash
cd frontend
npm run build
```

Это запускает TypeScript compiler и Vite build.

---

# GitHub Actions

Workflow находится в:

```text
.github/workflows/backend-tests.yml
```

При push и Pull Request запускаются CI jobs.

Backend job:

```text
PostgreSQL service
      ↓
Python 3.13
      ↓
pip install
      ↓
pytest -v
```

Frontend job:

```text
Node.js 22
      ↓
npm ci
      ↓
npm run build
```

Если branch protection настроен, merge в `main` должен быть разрешён только при зелёных checks:

```text
pytest           ✅
frontend-build   ✅
```

---

# Git workflow

Не работать напрямую в `main`.

Перед началом задачи:

```bash
git checkout main
git pull
git checkout -b feature/название-задачи
```

Примеры веток:

```text
feature/ml-model
feature/postgres-repository
feature/sensor-history
feature/dashboard-ui
fix/import-validation
```

После работы:

```bash
git status
git add .
git commit -m "Describe implemented change"
git push -u origin feature/название-задачи
```

Затем создать Pull Request:

```text
feature/... → main
```

Перед merge должны пройти CI checks.

После merge:

```bash
git checkout main
git pull
```

---

# Правила разработки

## Общие

Перед началом работы всегда обновлять `main`.

Не коммитить:

```text
.env
.venv/
node_modules/
dist/
секреты
токены
пароли
большие ML-модели
большие датасеты
```

## Frontend-разработчик

Основная зона:

```text
frontend/
```

Обычно не требуется менять:

```text
backend/app/repositories/
backend/app/db/
backend/app/ml/
```

При необходимости изменения API сначала согласовать контракт.

## Backend-разработчик

Основная зона:

```text
backend/app/api/
backend/app/services/
backend/app/repositories/
backend/app/db/
backend/app/schemas/
backend/app/core/
```

Изменение Pydantic response schema считать изменением API-контракта.

## ML-разработчик

Основная зона:

```text
ml/
```

Интеграционная зона:

```text
backend/app/ml/
```

ML-разработчик не должен переписывать frontend или структуру REST API без согласования.

## DB-разработчик

Основная зона:

```text
backend/app/db/
backend/app/repositories/
```

Нельзя заставлять API напрямую выполнять SQL.

---

# Переменные окружения

Локальные `.env` не должны попадать в Git.

В Git хранятся только `.env.example`.

## Backend

```text
backend/.env
```

```env
DATABASE_URL=postgresql+psycopg://astra:astra@localhost:5432/astra
```

## Frontend

```text
frontend/.env
```

```env
VITE_API_URL=http://127.0.0.1:8000
```

При добавлении новой обязательной переменной окружения необходимо обновить соответствующий `.env.example`.

---

# Что уже реализовано

Работает:

- FastAPI backend;
- React + TypeScript frontend;
- PostgreSQL в Docker;
- REST API;
- CORS;
- health endpoint;
- dashboard endpoint;
- список датчиков;
- получение датчика по ID;
- SensorRepository abstraction;
- service layer;
- MLService abstraction;
- dummy ML implementation;
- ML health;
- ML train contract;
- ML prediction contract;
- проверка существования датчика перед прогнозом;
- PredictionService;
- DashboardService;
- импорт CSV/XLS/XLSX на уровне приёма файла;
- Pydantic response schemas;
- backend tests;
- frontend build validation;
- GitHub Actions CI;
- Docker development environment;
- Uvicorn reload;
- Vite hot reload;
- единый `astra.sh` launcher;
- desktop launcher через `launch-astra.sh`;
- frontend dashboard;
- summary по рискам;
- status/risk indication;
- фильтрация датчиков;
- поиск датчиков;
- сортировка датчиков;
- детальная карточка датчика;
- вызов ML-прогноза из UI.

---

# Что пока является заглушкой

Следующие компоненты ещё не являются production implementation.

## Датчики

Сейчас используется:

```text
DummySensorRepository
```

Данные находятся в Python-коде.

Нужно заменить на PostgreSQL implementation.

## ML

Сейчас используется:

```text
DummyMLService
```

Например, `probability = 0.42` — тестовое значение, а не результат настоящей модели.

## Импорт

CSV/XLS/XLSX принимаются, но содержимое ещё не разбирается и не сохраняется в PostgreSQL.

## История измерений

API временных рядов и история датчиков ещё должны быть реализованы.

## Авторизация

Пользователи, роли и доступ диспетчера пока не реализованы.

## Production deployment

Текущий frontend Dockerfile запускает Vite development server. Для production deployment потребуется отдельная production-сборка, например через Nginx или другой web server.

---

# Типовые сценарии разработки

## Я меняю только Python backend

```bash
cd ~/Projects/ASTRA
./astra.sh
```

После этого редактировать `.py` и сохранять.

Uvicorn reload подхватит изменения автоматически.

Проверка:

```bash
cd backend
source .venv/bin/activate
pytest -v
```

## Я меняю только React/CSS

Запустить ASTRA один раз:

```bash
./astra.sh
```

После этого редактировать файлы в:

```text
frontend/src/
```

Vite hot reload обновит браузер автоматически.

Перед commit:

```bash
cd frontend
npm run build
```

## Я изменил Python dependency

После изменения:

```text
backend/requirements.txt
```

нужна пересборка:

```bash
./astra.sh rebuild
```

## Я изменил npm dependency

После изменения `package.json` или lock-файла:

```bash
cd frontend
npm install
cd ..
./astra.sh rebuild
```

## Я хочу посмотреть Swagger

```text
http://127.0.0.1:8000/docs
```

## Я хочу остановить всё

```bash
./astra.sh stop
```

---

# Полезные команды

Состояние Docker:

```bash
docker compose ps
```

Все контейнеры, включая остановленные:

```bash
docker compose ps -a
```

Backend logs:

```bash
docker compose logs -f backend
```

Frontend logs:

```bash
docker compose logs -f frontend
```

PostgreSQL logs:

```bash
docker compose logs -f postgres
```

Backend health:

```bash
curl http://127.0.0.1:8000/api/health
```

Dashboard:

```bash
curl http://127.0.0.1:8000/api/dashboard
```

Sensors:

```bash
curl http://127.0.0.1:8000/api/sensors
```

Один датчик:

```bash
curl http://127.0.0.1:8000/api/sensors/56682
```

ML prediction:

```bash
curl http://127.0.0.1:8000/api/ml/predict/56682
```

Git status:

```bash
git status
```

Последние commits:

```bash
git log --oneline --max-count=10
```

---

# Разделение ответственности команды

```text
┌───────────────────────┬──────────────────────────────────────┐
│ Роль                  │ Основная зона                        │
├───────────────────────┼──────────────────────────────────────┤
│ Frontend              │ frontend/                            │
│ Backend               │ backend/app/                         │
│ ML                    │ ml/ + backend/app/ml integration     │
│ Database              │ backend/app/db + repositories        │
│ Infrastructure / CI   │ compose.yaml, Dockerfiles, .github/  │
└───────────────────────┴──────────────────────────────────────┘
```

Главное правило: разработчик может менять другую зону, если это необходимо, но изменение публичного контракта должно быть согласовано с разработчиком, который от этого контракта зависит.

---

# Definition of Done для Pull Request

Перед созданием PR желательно выполнить:

```bash
cd backend
source .venv/bin/activate
pytest -v

cd ../frontend
npm run build
```

PR считается технически готовым, если:

- задача реализована;
- тесты проходят;
- frontend собирается;
- `.env` и секреты не попали в commit;
- новый публичный API описан;
- при изменении environment variables обновлён `.env.example`;
- при изменении архитектуры обновлён README;
- GitHub Actions зелёный.

---

# Краткая памятка новому разработчику

```text
1. Прочитай README.
2. Клонируй репозиторий.
3. Установи Docker Engine и Docker Compose plugin, если их ещё нет.
4. Выполни ./astra.sh — зависимости устанавливаются внутри контейнеров.
5. Корневой .env из .env.example нужен только для нестандартных настроек.
6. Для ежедневного запуска используй ./astra.sh quick.
7. Создай свою feature-ветку.
8. Работай только через Pull Request.
9. Не пушь секреты и большие данные.
10. Перед PR запусти ./astra.sh check.
```

---

# ASTRA

Цель репозитория — позволить нескольким разработчикам независимо развивать frontend, backend, PostgreSQL и ML, сохраняя стабильный REST-контракт между компонентами.

Если для новой задачи приходится полностью переписывать соседний слой, сначала проверь, нельзя ли решить её через существующий interface/service/repository contract.
