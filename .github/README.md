# .github

CI на GitHub Actions. Единственный workflow — `workflows/backend-tests.yml` («Backend tests»).

**Триггеры:** `push` в любую ветку; `pull_request` в `main`. Права токена: `contents: read`.

## Jobs

| Job | Runner / сервисы | Рабочий каталог | Шаги |
|---|---|---|---|
| `pytest` | `ubuntu-latest`; service container `postgres:16` (`astra/astra/astra`, порт 5432, healthcheck `pg_isready`); `DATABASE_URL=postgresql+psycopg://astra:astra@localhost:5432/astra` | `backend` | `actions/checkout@v6` → `actions/setup-python@v5` (Python 3.13, pip-кэш по `backend/requirements.txt`) → `pip install -r requirements.txt` и `pip install --no-deps ../data_pipeline` → `pytest -v` → проверка паритета признаков: `python -m unittest discover -s ../data_pipeline/tests -v` |
| `frontend-build` | `ubuntu-latest` | `frontend` | `actions/checkout@v6` → `actions/setup-node@v4` (Node.js 22, npm-кэш по `frontend/package-lock.json`) → `npm ci` → `npm run build` → `npm test` |

Jobs выполняются параллельно (`needs` не задан). Скрипты [`../sql/`](../sql/) в workflow не запускаются.
