#!/bin/bash
# =============================================================================
# build_db.sh — собрать всю БД проекта из файла организаторов одной командой.
#
#   bash tools/build_db.sh /путь/к/ext_journal_prepared.csv
#
# Шаги (каждый с проверкой, при ошибке скрипт останавливается):
#   1. создаёт БД (если её нет) и пустой журнал public.ext_journal_prepared  (sql/00)
#   2. загружает CSV организаторов                                            (\copy)
#   3. справочники                                                            (sql/01)
#   4. очищенные события ml.dataset_events                                    (sql/02)
#   5. признаки ml.dataset_ml + ml.v_dataset_ml                               (sql/03)
# Время: несколько часов на полном журнале.
# Место на диске: ориентир 150 ГБ (журнал + события 67 ГБ + признаки 39 ГБ).
#
# Переменные окружения: DB (по умолчанию djkh08), PGHOST/PGPORT/PGUSER - как для psql.
#   EXPECTED_ROWS - сколько строк должно загрузиться (по умолчанию 313545997 - полный журнал).
# Уже загруженный журнал можно не грузить заново: SKIP_LOAD=1 bash tools/build_db.sh
# =============================================================================
set -euo pipefail
DB="${DB:-djkh08}"
CSV="${1:-}"
EXPECTED_ROWS="${EXPECTED_ROWS:-313545997}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PGOPTIONS="-c jit=off"
PSQL=(psql -X -v ON_ERROR_STOP=1 -d "$DB")
T0=$(date +%s)
step() { echo; echo "=== [$(( ($(date +%s) - T0) / 60 )) мин] $*"; }

if [ "${SKIP_LOAD:-0}" != "1" ]; then
  [ -f "$CSV" ] || { echo "Укажите путь к ext_journal_prepared.csv: bash tools/build_db.sh /путь/к/файлу.csv"; exit 1; }
  if ! psql -X -d "$DB" -c 'SELECT 1' >/dev/null 2>&1; then
    step "Создаю базу $DB"; createdb "$DB"
  fi
  step "1/5 Пустой журнал (sql/00)"
  "${PSQL[@]}" -q -f "$HERE/sql/00_create_journal.sql"
  step "2/5 Загрузка $CSV (самый долгий шаг вместе с 4 и 5)"
  "${PSQL[@]}" -c "\\copy public.ext_journal_prepared FROM '$CSV' WITH (FORMAT csv, HEADER true)"
fi
n=$("${PSQL[@]}" -Atc "SELECT count(*) FROM public.ext_journal_prepared")
echo "В журнале строк: $n (ожидается $EXPECTED_ROWS)"
[ "$n" = "$EXPECTED_ROWS" ] || { echo "ОШИБКА: число строк не совпало - файл не тот или загрузился не полностью"; exit 1; }

step "3/5 Справочники (sql/01)"
"${PSQL[@]}" -q -f "$HERE/sql/01_reference_tables.sql"
step "4/5 Очищенные события ml.dataset_events (sql/02)"
"${PSQL[@]}" -q -f "$HERE/sql/02_build_dataset.sql"
step "5/5 Признаки ml.dataset_ml (sql/03)"
"${PSQL[@]}" -q -f "$HERE/sql/03_ml_features.sql"

step "Итог"
"${PSQL[@]}" -At -F ' | ' -c "SELECT 'ml.dataset_events', count(*) FROM ml.dataset_events
                                UNION ALL SELECT 'ml.dataset_ml', count(*) FROM ml.dataset_ml"
echo "Для полного журнала обе цифры должны быть 303163533."
echo "Готово за $(( ($(date +%s) - T0) / 60 )) мин."
