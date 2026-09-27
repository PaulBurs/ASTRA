# ASTRA — ML

> **Модель прогноза тревог и детектор аномалий** — [README_MODEL.md](README_MODEL.md):
> итоговые метрики, запуск `train` / `predict`, структура `djkh_model/` и `out_final/`.

Эта директория предназначена для ML-разработки проекта ASTRA.

Здесь описаны только четыре вещи:

- какое Python-окружение используется;
- как подключить отдельное ML-окружение;
- как получать данные из PostgreSQL;
- что модель должна возвращать backend после работы.

---

# 1. Python-окружение

В проекте уже существует backend-окружение:

```text
backend/.venv
```

Оно содержит зависимости FastAPI, SQLAlchemy, Pydantic,
PostgreSQL-драйверы и другие библиотеки backend.

Активировать его можно из корня проекта:

```bash
source backend/.venv/bin/activate
```

Проверить используемый Python:

```bash
which python
python --version
```

---

# 2. Отдельное окружение для ML

Для ML рекомендуется использовать отдельное окружение:

```text
ml/.venv
```

Создать его:

```bash
cd ~/Projects/ASTRA

python3.13 -m venv ml/.venv
```

Активировать:

```bash
source ml/.venv/bin/activate
```

Проверить:

```bash
which python
```

Ожидаемый путь:

```text
.../ASTRA/ml/.venv/bin/python
```

Backend и ML окружения не следует смешивать.

Для работы с backend-контрактами в ML-окружение также необходимо
установить backend dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

Дополнительные библиотеки ML устанавливаются отдельно, например:

```bash
python -m pip install numpy pandas scikit-learn
```

Если ML-команда добавляет новую обязательную библиотеку,
её необходимо добавить в:

```text
ml/requirements.txt
```

Пример:

```text
numpy
pandas
scikit-learn
joblib
pyarrow
```

После этого новый разработчик сможет установить ML-зависимости:

```bash
python -m pip install -r ml/requirements.txt
```

Директория:

```text
ml/.venv/
```

не должна попадать в Git.

---

# 3. Как ML получает данные из БД

ML-код не должен самостоятельно писать SQL к production PostgreSQL.

Правильная схема:

```text
PostgreSQL
    ↓
Backend Repository
    ↓
Backend Service
    ↓
ML
```

Таким образом ML не зависит от физических названий таблиц,
SQL-запросов и внутренней структуры PostgreSQL.

---

## Данные для обучения

Основная точка входа:

```text
backend/app/services/ml_training_data_service.py
```

Используется:

```python
MLTrainingDataService
```

Пример:

```python
from datetime import datetime

from app.services.ml_training_data_service import (
    MLTrainingDataService,
)

for batch in service.iter_training_events(
    engineering_system="Газовая охрана",
    sensor_type="Газовый датчик",
    start=datetime(2025, 1, 1),
    end=datetime(2026, 1, 1),
    batch_size=50_000,
):
    # preprocessing
    # feature engineering
    # dataset building
    pass
```

ML получает данные batch'ами.

Не нужно загружать всю историю БД в память одновременно.

---

## Откуда берутся sensor_id

ML не должен самостоятельно искать ID каналов SQL-запросом.

Для этого используется:

```text
SensorCatalogRepository
```

Через `MLTrainingDataService`:

```python
sensor_ids = service.get_sensor_ids(
    engineering_system="Газовая охрана",
    sensor_type="Газовый датчик",
)
```

Backend сам определяет, откуда получить эти ID:

```text
Dummy repository
```

или:

```text
PostgreSQL
```

---

## Формат события для обучения

ML получает примерно такую структуру:

```python
{
    "event_id": 123,
    "sensor_id": 900001,
    "occurred_at": datetime(...),
    "value_type": "numeric",
    "numeric_value": 0.03,
    "datetime_value": None,
    "text_value": None,
}
```

Возможные:

```text
value_type
```

значения:

```text
numeric
binary
datetime
text
```

Для разных типов необходимо использовать соответствующее поле.

Например:

```text
numeric
    → numeric_value

binary
    → numeric_value

datetime
    → datetime_value

text
    → text_value
```

---

# 4. Данные для online prediction

При работе приложения ML не получает доступ ко всей базе.

Backend сам собирает временное окно нужного датчика и создаёт:

```text
MLPredictionInput
```

Контракт находится здесь:

```text
backend/app/ml/contracts.py
```

Пример логической структуры:

```python
{
    "sensor_id": 900001,
    "sensor_type": "Газовый датчик",
    "engineering_system": "Газовая охрана",
    "sensor_name": "...",
    "object_id": 1001,
    "as_of": datetime(...),
    "lookback_hours": 24,
    "events": [
        ...
    ],
}
```

ML получает этот объект через:

```python
MLService.predict(...)
```

ML не должен внутри `predict()` самостоятельно обращаться
к PostgreSQL.

Правильная схема:

```text
sensor_id
    ↓
PredictionService
    ↓
MLDataRepository
    ↓
PostgreSQL
    ↓
MLPredictionInput
    ↓
MLService.predict()
```

---

# 5. Как подключать backend-контракты из ML

Backend Python package находится в:

```text
backend/app
```

При запуске собственных ML-скриптов из корня проекта можно
добавить backend в Python path:


После этого доступны импорты:

```python
from app.ml.contracts import MLPredictionInput
```

и:

```python
from app.services.ml_training_data_service import (
    MLTrainingDataService,
)
```

---

# 6. Что должна возвращать модель

Основной интерфейс ML находится здесь:

```text
backend/app/ml/service.py
```

Реальная модель должна реализовать:

```python
class RealMLService(MLService):
    ...
```

Главный метод:

```python
def predict(
    self,
    prediction_input: MLPredictionInput,
) -> dict:
    ...
```

После расчёта модель должна вернуть:

```python
{
    "sensor_id": prediction_input.sensor_id,
    "probability": 0.73,
    "horizon_hours": 24,
    "model_version": "gas-v1",
}
```

---

## sensor_id

ID канала, для которого построен прогноз:

```python
"sensor_id": 900001
```

Он должен совпадать с:

```python
prediction_input.sensor_id
```

---

## probability

Вероятность прогнозируемого события:

```python
"probability": 0.73
```

Допустимый диапазон:

```text
0.0 <= probability <= 1.0
```

Пример:

```text
0.00 → 0%
0.42 → 42%
0.91 → 91%
1.00 → 100%
```

ML должен возвращать именно вероятность от `0` до `1`,
а не процент от `0` до `100`.

---

## horizon_hours

Горизонт прогноза:

```python
"horizon_hours": 24
```

То есть модель отвечает примерно на вопрос:

```text
Какова вероятность целевого события
в течение следующих 24 часов?
```

Если ML-команда меняет горизонт, это необходимо согласовать
с backend-командой.

---

## model_version

Версия модели:

```python
"model_version": "gas-v1"
```

При обновлении модели версия должна изменяться.

Например:

```text
gas-v1
gas-v2
gas-2026-09-01
```

Это позволяет понимать, какая именно модель построила прогноз.

---

# 7. Пример реализации модели

Минимальный пример:

```python
from app.ml.contracts import MLPredictionInput
from app.ml.service import MLService


class RealMLService(MLService):

    def health(self) -> bool:
        return True

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "gas-v1",
            "message": "Training completed",
        }

    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        # 1. preprocessing
        # 2. feature engineering
        # 3. model.predict_proba(...)
        probability = 0.73

        return {
            "sensor_id": prediction_input.sensor_id,
            "probability": probability,
            "horizon_hours": 24,
            "model_version": "gas-v1",
        }
```

Модель не должна:

```text
возвращать HTTP Response;
обращаться к frontend;
писать данные напрямую в UI;
самостоятельно формировать REST JSON;
самостоятельно читать production PostgreSQL.
```

Она возвращает обычный Python `dict`.

Дальше backend сам:

```text
MLService
    ↓
PredictionService
    ↓
FastAPI
    ↓
REST JSON
    ↓
Frontend
```

---

# 8. Результат обучения

Метод:

```python
train()
```

должен вернуть краткую информацию о результате:

```python
{
    "status": "completed",
    "model_version": "gas-v1",
    "message": "Training completed successfully",
}
```

Сама обученная модель должна сохраняться отдельно как artifact,
а не передаваться через REST API.

Например:

```text
ml/artifacts/gas-v1.joblib
```

Большие model artifacts не должны коммититься в Git.

---

# 9. Главное правило интеграции

ML отвечает за:

```text
events
    ↓
preprocessing
    ↓
features
    ↓
model
    ↓
probability
```

Backend отвечает за:

```text
PostgreSQL
    ↓
repositories
    ↓
services
    ↓
MLPredictionInput
```

После работы модели backend ожидает:

```text
sensor_id
probability
horizon_hours
model_version
```

ML-разработчику не требуется знать устройство REST API
или frontend.
