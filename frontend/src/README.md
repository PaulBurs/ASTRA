# frontend/src — запуск и отображение прогноза модели

Описаны файлы, отвечающие за отдельный запуск прогноза и отображение хода расчёта.
Интерфейс — React + TypeScript, API — REST backend (`backend/app/README.md`).

| Файл | Что делает | Как |
|---|---|---|
| `components/ForecastPanel.tsx` | Блок «Прогноз модели» на вкладке «Данные»: запуск и остановка прогноза всех датчиков, прогресс, время. Кнопка недоступна до готовности набора и во время подготовки любого набора | опрос `GET …/forecasts/job` (2 с во время расчёта, 10 с иначе), `POST …/forecasts`, `POST …/forecasts/stop` |
| `components/DatasetImportPanel.tsx` | Встраивает `ForecastPanel` под блоком подготовки набора | — |
| `components/LiveMode.tsx` | Передаёт в панель импорта идентификатор пользователя (заголовок `X-Employee-ID`) | — |
| `components/LiveWorkspace.tsx` | На главной в прогрессе расчёта показывает время и скорость | `forecastTiming` |
| `utils/forecastTiming.ts` | «Прошло / заняло», датчиков в минуту, оценка оставшегося времени по `created_at`, `updated_at`, `completed`, `total` задачи | чистая функция без зависимостей |
| `api/liveWorkspace.ts` | Типы `ForecastJob` (с `created_at`, `updated_at`), запросы к рабочему месту | `fetch` |

Тесты: `../tests/forecast.test.mjs` — `forecastTiming` для идущего, завершённого расчёта и
задачи без времени (`node --test`).
