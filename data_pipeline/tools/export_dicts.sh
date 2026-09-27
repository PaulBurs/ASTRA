#!/bin/bash
# Выгрузить справочники из БД в lct_features/dicts/ (после пересборки базы скриптами sql/).
# Запуск из папки data_pipeline:  bash tools/export_dicts.sh   (БД по умолчанию djkh08, иначе DB=...)
set -euo pipefail
DB="${DB:-djkh08}"
D="$(cd "$(dirname "$0")/.." && pwd)/lct_features/dicts"
for t in map_sensor_type map_value_type map_state map_object map_complex map_channel norm_params window_params; do
  psql -X -q -d "$DB" -c "COPY (SELECT * FROM ml.$t ORDER BY 1, 2) TO STDOUT WITH (FORMAT csv, HEADER true)" > "$D/$t.csv"
done
psql -X -q -d "$DB" -c "COPY (SELECT * FROM ml.ref_state_fixed ORDER BY 1, 2) TO STDOUT WITH (FORMAT csv, HEADER true)" > "$D/state_alarm.csv"
wc -l "$D"/*.csv
echo "Готово. Проверьте: python -m unittest -v"
