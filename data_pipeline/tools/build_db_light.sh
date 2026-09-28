#!/bin/bash
# =============================================================================
# build_db_light.sh — ЛЁГКАЯ база для приложения: только последние DAYS дней журнала.
#
#   bash tools/build_db_light.sh /путь/к/ext_journal_prepared.csv
#
# Зачем: приложению для расчёта признаков по потоку нужна история максимум за 90 дней
# (самое длинное окно нормировки) + по одному последнему событию каждого датчика до неё.
# Вся история за 7,5 лет и обучающая таблица ml.dataset_ml приложению не нужны.
#
# По умолчанию берутся 150 дней до конца данных (30.06.2026):
#   первые 90 дней - прогрев окон, остальные 60 - можно проигрывать как поток на демо.
# Итог: около 25 млн событий вместо 313 млн, ~10 ГБ вместо ~150 ГБ, десятки минут вместо часов.
#
# Что делается:
#   1. из CSV берутся строки с датой >= CUTOFF и, для каждого датчика, его последнее событие
#      до CUTOFF (чтобы у первого события в окне было верное «время с прошлого события»);
#   2. грузятся в public.ext_journal_prepared (sql/00);
#   3. справочники (sql/01) и очищенные события ml.dataset_events (sql/02).
#   ml.dataset_ml (sql/03) НЕ строится - приложение считает признаки само (lct_features).
#
# Параметры (переменные окружения):
#   DAYS=150            сколько дней истории брать (не меньше 90)
#   END=2026-07-01      граница конца данных (исключительно)
#   DB=djkh08           имя базы; PGHOST/PGPORT/PGUSER - как для psql
#   WITH_FEATURES=1     дополнительно построить ml.dataset_ml за эти дни (sql/03)
# =============================================================================
set -euo pipefail
DB="${DB:-djkh08}"
CSV="${1:-}"
DAYS="${DAYS:-150}"
END="${END:-2026-07-01}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PGOPTIONS="-c jit=off"
PSQL=(psql -X -v ON_ERROR_STOP=1 -d "$DB")
T0=$(date +%s)
step() { echo; echo "=== [$(( ($(date +%s) - T0) / 60 )) мин] $*"; }

[ -f "$CSV" ] || { echo "Укажите путь к ext_journal_prepared.csv: bash tools/build_db_light.sh /путь/к/файлу.csv"; exit 1; }
[ "$DAYS" -ge 90 ] || { echo "DAYS должно быть не меньше 90 (самое длинное окно нормировки)"; exit 1; }
CUTOFF=$(psql -X -d postgres -Atc "SELECT (DATE '$END' - $DAYS)::text" 2>/dev/null || \
         python3 -c "import datetime as d;print(d.date.fromisoformat('$END')-d.timedelta(days=$DAYS))")
echo "Берём события с $CUTOFF по $END (не включая) + последнее событие каждого датчика до $CUTOFF"

if ! psql -X -d "$DB" -c 'SELECT 1' >/dev/null 2>&1; then
  step "Создаю базу $DB"; createdb "$DB"
fi
step "1/4 Пустой журнал (sql/00)"
"${PSQL[@]}" -q -f "$HERE/sql/00_create_journal.sql"

step "2/4 Отбор и загрузка строк из CSV (читается весь файл, ~5-15 мин)"
# В файле организаторов нет кавычек и запятых внутри полей (проверено), поэтому awk по запятой безопасен.
# 5-е поле - дата_время_события 'ГГГГ-ММ-ДД чч:мм:сс', сравнивается как строка.
LC_ALL=C awk -F, -v cut="$CUTOFF" -v end="$END" '
  NR == 1 { print; next }
  $5 >= cut { if ($5 < end) print; next }
  $5 > last[$2] { last[$2] = $5; row[$2] = $0 }
  END { for (c in row) print row[c] }
' "$CSV" | "${PSQL[@]}" -c "\\copy public.ext_journal_prepared FROM pstdin WITH (FORMAT csv, HEADER true)"
n=$("${PSQL[@]}" -Atc "SELECT count(*) FROM public.ext_journal_prepared")
echo "Загружено строк: $n"
[ "$n" -gt 0 ] || { echo "ОШИБКА: ничего не загрузилось - проверьте файл и END"; exit 1; }

step "3/4 Справочники (sql/01)"
"${PSQL[@]}" -q -f "$HERE/sql/01_reference_tables.sql" >/dev/null
step "4/4 Очищенные события ml.dataset_events (sql/02)"
"${PSQL[@]}" -q -f "$HERE/sql/02_build_dataset.sql" >/dev/null

if [ "${WITH_FEATURES:-0}" = "1" ]; then
  step "Доп.: ml.dataset_ml за эти дни (sql/03)"
  "${PSQL[@]}" -q -f "$HERE/sql/03_ml_features.sql" >/dev/null
fi

step "Итог"
"${PSQL[@]}" -c "SELECT count(*) AS событий,
                        min(\"дата_время_события\") FILTER (WHERE \"дата_время_события\" >= '$CUTOFF') AS с,
                        max(\"дата_время_события\") AS по
                 FROM ml.dataset_events"
"${PSQL[@]}" -Atc "SELECT 'Размер базы: ' || pg_size_pretty(pg_database_size('$DB'))"
echo
echo "Прогрев приложения: warm_up_from_postgres(conn, now) с now не раньше $CUTOFF + 90 дней:"
"${PSQL[@]}" -Atc "SELECT '  now >= ' || (DATE '$CUTOFF' + 90)::text || '  (для проигрывания на демо доступно ' || ($DAYS - 90) || ' дн.)'"
echo "Готово за $(( ($(date +%s) - T0) / 60 )) мин."
