#!/bin/bash
# Дамп схемы ml (очищенные события, признаки, справочники) для передачи бэкенду.
# Формат - каталог, 4 потока. Сырой журнал public.ext_journal_prepared НЕ включается
# (добавьте WITH_RAW=1, если он нужен).
#   bash tools/dump_db.sh                 -> ./djkh08_ml_dump/
# Восстановление на другой машине:
#   createdb djkh08 && pg_restore -d djkh08 -j 4 djkh08_ml_dump
set -euo pipefail
DB="${DB:-djkh08}"
OUT="${1:-djkh08_ml_dump}"
EXTRA=()
[ "${WITH_RAW:-0}" = "1" ] && EXTRA=(-t 'public.ext_journal_prepared*')
T0=$(date +%s)
pg_dump -d "$DB" -Fd -j 4 -Z 6 -n ml "${EXTRA[@]}" -f "$OUT"
echo "Готово за $(( ($(date +%s) - T0) / 60 )) мин: $OUT, $(du -sh "$OUT" | cut -f1)"
