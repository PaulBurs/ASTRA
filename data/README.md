# data

Каталог данных времени выполнения. В репозитории хранится только этот файл.

| Путь | Назначение | Git |
|---|---|---|
| `data/uploads/` | CSV-датасеты, загруженные через интерфейс; по подкаталогу на датасет (UUID hex) | Игнорируется (`.gitignore`) |

## Использование

- `compose.yaml`, сервис `backend`: bind mount `./data/uploads:/data/uploads`, переменная `DATASET_UPLOAD_DIR=/data/uploads`.
- `DatasetImportService` ([`../backend/app/services/dataset_import_service.py`](../backend/app/services/dataset_import_service.py)) пишет сюда загрузки; без `DATASET_UPLOAD_DIR` использует `<корень проекта>/data/uploads`. Перед импортом проверяет свободное место на этом разделе (`DATASET_STORAGE_EXPANSION_FACTOR`, `DATASET_STORAGE_RESERVE_BYTES`).
- Исходный каталог CSV для Source Agent сюда не входит: он задаётся `ASTRA_SOURCE_DIR` (по умолчанию `./DJKH_transport`), см. [`../source_agent/README.md`](../source_agent/README.md).

Большие датасеты в Git не коммитятся.
