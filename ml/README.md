# ASTRA — ML workspace

Эта директория предназначена для разработки ML-части проекта ASTRA.

ASTRA решает задачу анализа истории инженерных датчиков и
прогнозирования потенциально опасных состояний.

ML-код отделён от:

- REST API;
- структуры PostgreSQL;
- SQL-запросов;
- frontend;
- бизнес-логики web-приложения.

Основной принцип:

```text
PostgreSQL
    ↓
Backend repositories
    ↓
Backend services
    ↓
ML input
    ↓
ml/src
    ↓
Model
```

ML-разработчик не должен писать SQL внутри `ml/src`.

---

## 1. Текущий статус

На текущем этапе реализован интеграционный каркас.

Настоящая обученная модель пока не подключена.

В backend уже существуют интерфейсы для:

- поиска каналов нужного типа;
- потокового чтения исторических событий;
- получения истории для online prediction;
- передачи типизированных данных в ML;
- возврата prediction через REST API.

Для разработки без большой PostgreSQL существуют Dummy repositories.

---

## 2. Структура

```text
ml/
├── example.py
├── README.md
│
├── src/
│   └── __init__.py
│
├── notebooks/
│   └── .gitkeep
│
└── artifacts/
    └── .gitkeep
```

Назначение:

### `ml/example.py`

Минимальный рабочий пример интеграции ML с backend.

С него рекомендуется начать знакомство с проектом.

### `ml/src/`

Production ML-код:

- preprocessing;
- feature engineering;
- dataset building;
- training;
- validation;
- inference adapter;
- model loading.

### `ml/notebooks/`

Jupyter notebooks для исследования данных.

Notebook не должен становиться единственным местом,
где существует важная preprocessing-логика.

Рабочую логику после исследования необходимо переносить в `ml/src/`.

### `ml/artifacts/`

Локальные артефакты модели:

- `.joblib`;
- `.pkl`;
- `.onnx`;
- checkpoints;
- другие бинарные модели.

Большие модели не должны коммититься в Git.

---

# 3. Быстрый старт

Из корня ASTRA:

```bash
cd ~/Projects/ASTRA
```

Активировать backend virtual environment:

```bash
source backend/.venv/bin/activate
```

Запустить пример:

```bash
python ml/example.py
```

Пример использует Dummy repositories и поэтому не требует
наличия реальной большой базы данных.

---

# 4. Архитектурная граница Backend ↔ ML

Для ML существуют два разных сценария.

## Обучение

```text
SensorCatalogRepository
        ↓
поиск подходящих каналов
        ↓
TrainingDataRepository
        ↓
исторические события batch'ами
        ↓
MLTrainingDataService
        ↓
ml/src preprocessing
        ↓
feature engineering
        ↓
training
```

Основная точка входа:

```text
backend/app/services/ml_training_data_service.py
```

ML-разработчику рекомендуется работать через:

```python
service.iter_training_events(...)
```

а не обращаться к PostgreSQL самостоятельно.

---

## Online prediction

Online prediction обрабатывает один канал.

```text
REST API
    ↓
PredictionService
    ↓
MLDataRepository
    ↓
последнее временное окно событий
    ↓
MLPredictionInput
    ↓
MLService.predict(...)
    ↓
probability
```

Контракт входных данных находится здесь:

```text
backend/app/ml/contracts.py
```

Основной объект:

```python
MLPredictionInput
```

Он содержит:

- `sensor_id`;
- тип датчика;
- инженерную систему;
- название датчика;
- объект;
- время прогноза `as_of`;
- размер исторического окна;
- последовательность событий.

---

# 5. Источник данных

Исходные данные организованы следующим образом:

```text
Объект
  ↓
Канал / датчик
  ↓
События
```

Связи:

```text
ид_объект
```

связывает объект и канал.

```text
ид_канала_данных
```

связывает канал с журналом событий.

Подготовленный журнал событий:

```text
ext_journal_prepared
```

В нём используются следующие основные поля:

```text
ид_события
ид_канала_данных
дата_время_события
тип_значения
значение_число
значение_дата_время
значение_текст
```

Типы значения:

```text
numeric
binary
datetime
text
```

ML должен использовать подготовленные типизированные поля,
а не самостоятельно парсить `значение_датчика_raw`.

---

# 6. Основное направление исследования — газ

На текущем этапе основным кандидатом для ML является:

```text
Инженерная система:
Газовая охрана

Тип датчика:
Газовый датчик
```

Рабочая гипотеза:

```text
история числовых значений
        ↓
изменение временного ряда
        ↓
состояние "Обнаружен газ"
```

Потенциальная target event:

```text
Обнаружен газ
```

Необходимо исследовать, существует ли статистически полезная
динамика значений перед этим состоянием.

Не следует заранее предполагать физический смысл чисел.
Расшифровка измеряемой величины в предоставленной документации
пока отсутствует.

---

# 7. Как получить газовые каналы

ML-коду не нужно знать SQL.

Используется каталог:

```python
sensor_ids = service.get_sensor_ids(
    engineering_system="Газовая охрана",
    sensor_type="Газовый датчик",
)
```

После подключения реального справочника ожидается, что результат
будет содержать реальные IDs газовых каналов.

Dummy-реализация сейчас использует:

```text
900001
900002
```

Это искусственные тестовые IDs.

---

# 8. Как читать обучающие данные

Нельзя загружать всю историю в Python одним запросом.

Использовать batch processing:

```python
for batch in service.iter_training_events(
    engineering_system="Газовая охрана",
    sensor_type="Газовый датчик",
    start=start,
    end=end,
    batch_size=50_000,
):
    process(batch)
```

Каждый `batch` представляет собой:

```python
list[dict]
```

Пример одного события:

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

---

# 9. Почему данные читаются batch'ами

Журнал очень большой.

Один тип датчиков может содержать сотни миллионов событий.

Поэтому запрещён подход:

```python
all_rows = load_everything()
```

или:

```sql
SELECT *
FROM ext_journal_prepared;
```

Production-код должен использовать:

- временной диапазон;
- конкретные sensor IDs;
- streaming;
- ограниченный batch size.

---

# 10. Feature engineering

Backend намеренно НЕ вычисляет ML-features.

Backend предоставляет корректную историю.

Feature engineering является ответственностью ML.

Примеры признаков, которые можно исследовать для numeric
временного ряда:

```text
последнее значение
mean
median
std
min
max

delta
slope

mean за 5 минут
mean за 30 минут
mean за 1 час

std за 1 час

количество измерений в окне

время с предыдущего измерения

частота событий

изменение относительно предыдущего окна
```

Это только кандидаты.

Не следует считать их доказанно полезными до исследования данных
и валидации модели.

---

# 11. Формирование target

Для газового датчика потенциальной целевой меткой является:

```text
Обнаружен газ
```

Пример постановки задачи:

```text
данные до момента T
        ↓
есть ли "Обнаружен газ"
в следующие N часов?
```

Важно строго разделять:

```text
features:
только информация, доступная ДО T

target:
события ПОСЛЕ T
```

Иначе возникает data leakage.

---

# 12. Data leakage

Это особенно важно для данной задачи.

Нельзя использовать в features:

- будущее событие `Обнаружен газ`;
- значения после точки прогнозирования;
- поля, которые непосредственно кодируют наступившую тревогу;
- агрегаты, вычисленные с использованием будущих данных.

Поле:

```text
тревожное_raw
```

пока не используется как feature.

Его семантика должна быть отдельно проверена.

Если оно напрямую отражает тревогу, использование его в модели
может привести к leakage.

---

# 13. Временное разделение train / validation / test

Для временных рядов нельзя случайным образом перемешивать
всю историю и затем делить строки.

Предпочтительная логика:

```text
ранний период
    ↓
TRAIN

более поздний период
    ↓
VALIDATION

самый поздний период
    ↓
TEST
```

Иначе информация из будущего может попасть в обучение.

Конкретные временные границы должны быть выбраны после
анализа распределения данных.

---

# 14. События разных типов

`numeric`, `binary`, `datetime` и `text` не следует
механически смешивать как одно числовое поле.

Например:

```text
numeric
0.03
```

и:

```text
text
Обнаружен газ
```

имеют разный смысл.

Сначала данные следует разделить по `value_type`,
а затем определить preprocessing для каждого типа.

---

# 15. Online prediction contract

Контракт расположен здесь:

```text
backend/app/ml/contracts.py
```

Пример логической структуры:

```python
{
    "sensor_id": ...,
    "sensor_type": ...,
    "engineering_system": ...,
    "sensor_name": ...,
    "object_id": ...,
    "as_of": ...,
    "lookback_hours": 24,
    "events": [
        ...
    ],
}
```

Будущая реальная реализация:

```python
class RealMLService(MLService):

    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        features = ...
        probability = ...

        return {
            "sensor_id": prediction_input.sensor_id,
            "probability": probability,
            "horizon_hours": 24,
            "model_version": "...",
        }
```

REST frontend не должен знать,
какие признаки использует модель.

---

# 16. Где писать ML-код

Рекомендуемая будущая структура:

```text
ml/src/
├── __init__.py
├── preprocessing.py
├── features.py
├── dataset.py
├── train.py
├── evaluate.py
└── model.py
```

Например:

```text
preprocessing.py
```

очистка и преобразование событий.

```text
features.py
```

feature engineering.

```text
dataset.py
```

построение обучающих примеров и target.

```text
train.py
```

обучение.

```text
evaluate.py
```

метрики и временная validation.

```text
model.py
```

сохранение, загрузка и inference.

Эту структуру можно менять по согласованию с ML-командой.

---

# 17. Что ML-разработчику делать не нужно

Не нужно:

```text
писать REST endpoints
```

Не нужно:

```text
знать пароль PostgreSQL для production inference
```

Не нужно:

```text
писать SQL внутри feature engineering
```

Не нужно:

```text
менять frontend
```

Не нужно:

```text
зависеть от структуры таблиц PostgreSQL
```

Для этого существует backend abstraction layer.

---

# 18. Backend-код, полезный ML-разработчику

Основные файлы:

```text
backend/app/ml/contracts.py

backend/app/ml/service.py

backend/app/services/prediction_service.py

backend/app/services/ml_training_data_service.py

backend/app/repositories/ml_data_repository.py

backend/app/repositories/training_data_repository.py

backend/app/repositories/sensor_catalog_repository.py
```

Dummy implementations:

```text
backend/app/repositories/dummy_ml_data_repository.py

backend/app/repositories/dummy_training_data_repository.py

backend/app/repositories/dummy_sensor_catalog_repository.py
```

PostgreSQL implementation исторического журнала:

```text
backend/app/repositories/postgres_ml_data_repository.py

backend/app/repositories/postgres_training_data_repository.py
```

---

# 19. Что пока не завершено

До полного подключения production PostgreSQL ещё необходимо:

1. узнать физическое имя таблицы справочника каналов;
2. реализовать `PostgresSensorCatalogRepository`;
3. проверить реальные индексы PostgreSQL;
4. проверить скорость выборок на большом журнале;
5. определить окончательный prediction lookback;
6. определить ML target horizon;
7. исследовать смысл числовых значений газовых датчиков;
8. реализовать настоящий ML model pipeline.

До выполнения этих шагов Dummy implementations являются
официальным способом разработки интеграции.

---

# 20. Проверка backend после изменений

Из корня проекта:

```bash
cd ~/Projects/ASTRA/backend
source .venv/bin/activate

python -m tabnanny app tests
pytest -v
```

Все тесты должны проходить без:

```text
FAILED
ERROR
```

---

# 21. Проверка ML example

```bash
cd ~/Projects/ASTRA
source backend/.venv/bin/activate

python ml/example.py
```

Скрипт должен:

1. найти тестовые газовые каналы;
2. получить историю событий;
3. получить её несколькими batch'ами;
4. вывести события;
5. завершиться без прямого SQL.

---

# 22. Правило интеграции

Если ML-разработчику не хватает данных:

не добавлять SQL непосредственно в `ml/src`.

Сначала сформулировать необходимый контракт, например:

```text
Мне нужны за последние 6 часов:

- numeric значения;
- состояние устройства;
- timestamp;
- object_id;
- sensor_type.
```

После этого backend расширяет repository/service contract.

Так ML-модель остаётся независимой от внутренней структуры БД.

---

# 23. Основной принцип

ML-команда отвечает за:

```text
данные → признаки → модель → probability
```

Backend-команда отвечает за:

```text
PostgreSQL → корректные данные → ML contract
```

Frontend-команда отвечает за:

```text
REST API → отображение результата
```

Такое разделение позволяет менять модель, БД и интерфейс
независимо друг от друга.
