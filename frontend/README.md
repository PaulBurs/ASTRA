# ASTRA Frontend

Веб-интерфейс диспетчера и техспециалиста ASTRA. Работает в двух режимах: «Демо» — локальный сценарий на тестовых данных в браузере; «v1.0.1» — работа с загруженной базой датчиков через REST API backend (загрузка CSV, подготовка набора, ML-прогнозы, назначение и выполнение проверок).

API backend описан в [../backend/README.md](../backend/README.md).

## Стек

- React 19, TypeScript 6, Vite 8 (`@vitejs/plugin-react`)
- Маршрутизация — History API + `useSyncExternalStore`, без сторонних роутеров
- HTTP — `fetch`; загрузка файлов — `XMLHttpRequest` (прогресс через `upload.onprogress`)
- Хранение на клиенте — `localStorage` (демоданные, черновики, режим), `sessionStorage` (демосессия)
- Линтер — oxlint; тесты — `node:test` + `node:assert`
- Контейнер — Docker (`node:22-alpine`, Vite dev server, порт 5173)

## Структура

| Путь | Назначение |
|---|---|
| `index.html`, `src/main.tsx` | Точка входа; монтирует `AccessApp` в `StrictMode` |
| `src/App.tsx` | Оболочка после входа: режим (`astra.application.mode.v1`), переключение `DemoMode` / `LiveMode` |
| `src/config.ts` | `API_URL` из `VITE_API_URL` (по умолчанию пустая строка — относительные URL) |
| `src/api/` | Клиенты backend и локальные репозитории |
| `src/components/` | Экраны и UI-компоненты |
| `src/hooks/` | Контроллеры состояния экранов |
| `src/state/` | Модели, маршрутизация, чистая логика демо-workspace |
| `src/data/demo.ts` | Фикстуры демо: объекты, предупреждения, проверки, наряды |
| `src/utils/` | Форматирование |
| `src/*.css`, `src/components/*.css` | Стили (обычный CSS) |
| `src/assets/`, `public/` | Изображения и иконки |
| `tests/` | Модульные тесты (`*.test.mjs`) |
| `docs/BACKEND_INTEGRATION.md` | Заметки по интеграции UI с backend |

### src/api

| Модуль | Что делает | Как |
|---|---|---|
| `auth.ts` | Демо-вход по ID сотрудника, роли `dispatcher` / `technician`, интерфейс `AuthRepository` | `sessionStorage` (`astra.demo.session.v1`) |
| `workspace.ts` | Репозиторий демо-workspace: загрузка, валидация схемы, миграция v1→v2, оптимистичная блокировка по `revision`, фильтрация по роли, синхронизация вкладок | `localStorage` (`astra.demo.workspace.v2`), событие `storage` |
| `drafts.ts` | Черновики отчётов о проверке | `localStorage` (`astra.report-draft.v1.*`) |
| `datasets.ts` | Жизненный цикл набора: создание, загрузка файлов, подготовка, проверка ML, удаление | `fetch`, `XMLHttpRequest` (PUT octet-stream) |
| `liveWorkspace.ts` | Типы live-режима; `datasetRequest` для `/api/datasets/{id}/…` с заголовком `X-Employee-ID` | `fetch` |
| `ml.ts` | Прогноз по одному датчику | `fetch` |
| `health.ts` | Состояние backend / PostgreSQL / ML | `fetch` |
| `sensors.ts` | Тип `Sensor` для live-режима; `getSensors()` в UI не вызывается | `fetch` |
| `dashboard.ts`, `dataSource.ts` | Клиенты `/api/dashboard`, `/api/data-source/*`; в текущем UI не используются | `fetch` |

### src/components

| Компонент | Роль |
|---|---|
| `AccessApp.tsx` | Экран входа, восстановление сессии, редиректы по роли (`/login` → `/home` или `/checks`), провайдер `DraftContext` |
| `WarningsPage.tsx` | Каркас: верхняя панель, выбор режима, меню разделов по роли, статус-бар |
| `ApplicationStatus.tsx` | Модальное окно состояния приложения (`<dialog>`) |
| `DemoMode.tsx` | Демо-режим: раздел «Данные» (загрузка/сброс демо) и маршрутизация на `DemoWorkspace` |
| `DemoWorkspace.tsx` | Демо-разделы «Главная», «Карта» (схема с масштабом и панорамой), «Проверки», «Архив»; фильтры сохраняются в репозиторий |
| `DemoActions.tsx` | Формы демо: назначение проверки, ложная тревога, старт и выполнение проверки |
| `ReportForm.tsx` | Отчёт о проверке с автосохранением черновика (сериализованная очередь записей) |
| `DraftContext.ts` | React Context для `DraftRepository` |
| `LiveMode.tsx` | Live-режим: восстановление набора, выбор между `DatasetImportPanel` и `LiveWorkspace` |
| `DatasetImportPanel.tsx` | Раздел «Данные»: выбор CSV, прогресс загрузки, стадия подготовки, счётчики, удаление базы |
| `ForecastPanel.tsx` | Запуск/остановка пакетного прогноза, опрос статуса (2 с при расчёте, иначе 10 с) |
| `LiveWorkspace.tsx` | Live-разделы: таблицы датчиков и проверок (по 100 строк), карточка датчика, назначение и выполнение проверок, опрос прогнозов (2 с / 12 с) |
| `DetailPanel.tsx` | Карточка записи: боковая панель или `<dialog>` при ширине ≤ 1000px (`matchMedia`) |
| `EmptyWorkspace.tsx` | Пустое состояние разделов и 404 |
| `WorkspaceFeedback.tsx` | Toast-уведомления и диалог сброса демо |
| `DataSourcePanel.tsx`, `SensorDetails.tsx`, `PredictionButton.tsx` | Компоненты прежнего интерфейса; нигде не импортируются |

### src/hooks, src/state, src/utils

| Модуль | Роль |
|---|---|
| `hooks/useDatasetImport.ts` | Контроллер импорта: загрузка файлов, опрос `GET /api/datasets/{id}` раз в 2 с, восстановление по ID из `localStorage` (`astra.preparedDataset`) |
| `hooks/useDemoStore.ts` | Обёртка над `WorkspaceRepository`: загрузка, мутации с блокировкой, отбрасывание устаревших ответов |
| `state/navigation.ts` | Маршруты `/home`, `/map`, `/checks`, `/archive` (+ `/:id`), `/data`, `/sensors`; `parseRoute`, `navigate`, `useRoute`; алиасы `/warnings`→`/home`, `/work-orders`→`/archive` |
| `state/models.ts` | Типы демо-модели |
| `state/workspace.ts` | Чистые функции демо: `createWorkspace`, `applyAction` (assign / falseAlarm / advance / result / planWork), миграция, `reopenUnresolved` |
| `utils/forecastTiming.ts` | Строка «прошло / скорость / осталось» для задачи прогноза |
| `utils/sensorFormat.ts` | Форматирование значения датчика (используется только `SensorDetails`) |

## Экраны и сценарии

Диспетчер видит все разделы; техспециалист — «Мои проверки», «Карта», «Архив» и только назначенные ему проверки. `/sensors` перенаправляется на «Главную».

| Маршрут | Демо (без backend) | v1.0.1 (backend) |
|---|---|---|
| `/login` | Вход по ID (демосотрудники `1001`, `2001`, `2002`) | то же |
| `/home` | Предупреждения, назначение проверки, ложная тревога | Датчики, прогноз по датчику и по всем, карточка датчика, назначение проверки |
| `/map` | Схема объектов с метками проверок | Объекты и их датчики (координат в данных нет) |
| `/checks` | Старт проверки, отчёт с черновиком | Старт и завершение проверки назначенным исполнителем |
| `/archive` | Завершённые проверки | Завершённые проверки |
| `/data` (диспетчер) | Загрузка/сброс демонабора | Импорт CSV, подготовка, проверка ML, пакетный прогноз, удаление базы |
| «Состояние приложения» | `GET /api/health` | `GET /api/health` |

Эндпоинты backend в режиме v1.0.1:

- Импорт (`api/datasets.ts`): `POST /api/datasets`, `PUT /api/datasets/{id}/files/{index}`, `POST /api/datasets/{id}/prepare`, `GET /api/datasets/{id}`, `POST /api/datasets/{id}/validate-ml`, `DELETE /api/datasets/{id}` (незавершённая загрузка), `DELETE /api/datasets/{id}?confirm_delete=true` (подготовленная база, с `X-Employee-ID`).
- Рабочее пространство (`datasetRequest`, префикс `/api/datasets/{id}/`): `GET workspace`, `GET sensors/{sensor_id}`, `GET|POST forecasts`, `POST forecasts/stop`, `GET forecasts/job`, `POST checks`, `PATCH checks/{check_id}` (`action: start|complete`, `revision`).
- Прогноз по датчику: `GET /api/ml/predict/{sensor_id}?dataset_id={id}`.

## Конфигурация

| Параметр | Где | Значение |
|---|---|---|
| `VITE_API_URL` | `src/config.ts`, `.env.example` | Префикс URL для `health`, `ml`, `liveWorkspace`. Пусто — тот же origin. В `compose.yaml` задано `""` |
| Прокси `/api` | `vite.config.ts` | `http://backend:8000` (сервис Docker Compose). `datasets.ts` всегда использует относительный `/api` |

Вне Docker при пустом `VITE_API_URL` нужно изменить `target` прокси в `vite.config.ts` на адрес backend.

## Запуск и проверки

```bash
npm ci
npm run dev       # Vite dev server, порт 5173
npm run build     # tsc -b && vite build → dist/
npm run preview   # просмотр production-сборки
npm run lint      # oxlint (.oxlintrc.json: плагины react, typescript, oxc)
npm test          # node --test tests/*.test.mjs
```

Тесты импортируют `.ts` напрямую: нужен Node ≥ 22.18 (встроенный type stripping) и установленные зависимости (`npm ci`).

Docker: `Dockerfile` (`node:22-alpine`) выполняет `npm ci` и запускает `npm run dev -- --host 0.0.0.0`. В `compose.yaml` каталог `src/` монтируется в контейнер (HMR).

## Тесты

| Файл | Что проверяет |
|---|---|
| `tests/auth.test.mjs` | Демо-вход/выход и недоступный storage; права ролей в `createDemoRepository`; сценарий техспециалист → диспетчер; фильтры по сотруднику; черновики отчётов; повторное открытие неустранённой неисправности |
| `tests/workspace.test.mjs` | `applyAction`: назначение → работа → отчёт → архив и валидации; хранение, ревизии, защита от перезаписи; миграция v1; сброс; `parseRoute` / `routeHref` |
| `tests/forecast.test.mjs` | `forecastTiming`: активная задача, завершённая, без меток времени |
