# ASTRA Backend

Backend проекта ASTRA построен на FastAPI.

## Структура

```text
backend/
├── app/
│   ├── api/             REST endpoints
│   ├── core/            dependency injection и общая конфигурация
│   ├── db/              подключение PostgreSQL
│   ├── ml/              интерфейс backend ↔ ML
│   ├── repositories/    абстракция доступа к данным
│   ├── schemas/         Pydantic API-схемы
│   └── services/        бизнес-логика
├── tests/
├── main.py
├── requirements.txt
└── Dockerfile
