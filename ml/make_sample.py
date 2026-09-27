"""
Вырезает представительный срез для прототипа:
  по PER_TYPE случайных датчиков каждого типа (из активных в 2025),
  вся их история за 2022-2026 (2021 пропускаем по рекомендации организаторов).
Запуск из папки, где лежит data/ (окружение .venv активно):
    python make_sample.py                          # 30 датчиков на тип -> sample_30.parquet
    python make_sample.py 20 sample_20.parquet     # поменьше (первые 20 из тех же 30)
Результат: parquet рядом со скриптом (около 190 МБ на 30 датчиков/тип).

Типы колонок заданы явно: без них duckdb угадывает `значение` как BIGINT
и округляет газ (0.01 % метана, шаг 0.01) до целых - порог тревоги 1 % ломается.
"""
import sys

import duckdb

sys.path.insert(0, 'djkh_model')
from model import COL_TYPES  # noqa: E402

YEARS = [2022, 2023, 2024, 2025, 2026]
PER_TYPE = int(sys.argv[1]) if len(sys.argv) > 1 else 30
OUT = sys.argv[2] if len(sys.argv) > 2 else 'sample_30.parquet'

files = [f'data/dataset_ml_{y}.csv.gz' for y in YEARS]
src = f"read_csv({files}, union_by_name = true, header = true, types = {COL_TYPES})"

con = duckdb.connect()
con.sql(f"""
CREATE TEMP TABLE ch AS
SELECT ид_канала_данных, код_типа_датчика FROM (
  SELECT ид_канала_данных, код_типа_датчика,
         row_number() OVER (PARTITION BY код_типа_датчика ORDER BY hash(ид_канала_данных)) AS rn  -- воспроизводимо
  FROM (SELECT DISTINCT ид_канала_данных, код_типа_датчика
        FROM read_csv('data/dataset_ml_2025.csv.gz', header = true, types = {COL_TYPES})))
WHERE rn <= {PER_TYPE}
""")

con.sql(f"""
COPY (
  SELECT * FROM {src}
  WHERE ид_канала_данных IN (SELECT ид_канала_данных FROM ch)
  ORDER BY ид_канала_данных, дата_время_события
) TO '{OUT}' (FORMAT parquet, COMPRESSION zstd)
""")

print(con.sql(f"""
SELECT код_типа_датчика,
       count(DISTINCT ид_канала_данных) AS датчиков,
       count(*)                         AS строк,
       sum(тревожное_событие)           AS тревог,
       max(значение)                    AS макс_значение
FROM '{OUT}' GROUP BY 1 ORDER BY 1
"""))
