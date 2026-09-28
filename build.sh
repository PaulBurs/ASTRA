#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"

cd "$ROOT_DIR"

# shellcheck source=scripts/docker-compose.sh
source "$ROOT_DIR/scripts/docker-compose.sh"


echo "======================================"
echo " ASTRA — full project build"
echo "======================================"


if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is not installed."
    exit 1
fi


astra_detect_compose || exit 1


echo
echo "[1/6] Building Docker images..."

astra_compose build


echo
echo "[2/6] Starting PostgreSQL..."

astra_compose up -d postgres


echo
echo "Waiting for PostgreSQL..."

until astra_compose exec -T postgres \
    pg_isready \
    -U astra \
    -d astra \
    >/dev/null 2>&1
do
    sleep 1
done


echo
echo "[3/6] Initializing database..."

bash sql/init-dev.sh --seed


echo
echo "[4/6] Starting ML service..."

astra_compose up -d ml


echo "Waiting for ML..."

until astra_compose exec -T ml \
    python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)" \
    >/dev/null 2>&1
do
    sleep 1
done


echo
echo "[5/6] Checking ML and frontend builds..."

astra_compose run \
    --rm \
    --no-deps \
    ml \
    python -m ml.example


astra_compose run \
    --rm \
    --no-deps \
    frontend \
    npm run build


echo
echo "[6/6] Checking backend..."

astra_compose run \
    --rm \
    --no-deps \
    -e DATA_SOURCE=dummy \
    -e ML_DATA_SOURCE=dummy \
    -e ML_SERVICE_URL= \
    backend \
    pytest -q


echo
echo "Stopping temporary services..."

astra_compose stop ml postgres >/dev/null


echo
echo "======================================"
echo " ASTRA build completed successfully"
echo "======================================"
echo
echo "Run the project with:"
echo
echo "    ./run.sh"
