#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=../scripts/docker-compose.sh
source "$ROOT_DIR/scripts/docker-compose.sh"

DB_USER="astra"
DB_NAME="astra"

echo "ASTRA PostgreSQL initialization"
echo "================================"

echo "[1/4] Starting PostgreSQL..."

astra_compose up -d --no-build postgres

echo "[2/4] Waiting for PostgreSQL..."

until astra_compose exec -T postgres \
    pg_isready \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    >/dev/null 2>&1
do
    sleep 1
done

echo "PostgreSQL is ready."

apply_sql() {
    local file="$1"

    echo
    echo "Applying: $file"

    astra_compose exec -T postgres \
        psql \
        -v ON_ERROR_STOP=1 \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        < "$file"
}

echo "[3/4] Applying schema and indexes..."

apply_sql "sql/schema/01_core_schema.sql"
apply_sql "sql/indexes/01_ext_journal_sensor_time.sql"
apply_sql "sql/indexes/02_astra_channels_catalog.sql"

if [[ "${1:-}" == "--seed" ]]; then
    echo
    echo "Applying development seed..."

    apply_sql "sql/seed/01_dev_seed.sql"
fi

echo
echo "[4/4] Checking database..."

astra_compose exec -T postgres \
    psql \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -c "
SELECT
    table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'astra_objects',
      'astra_channels',
      'ext_journal_prepared'
  )
ORDER BY table_name;
"

echo
echo "ASTRA PostgreSQL initialization completed."
