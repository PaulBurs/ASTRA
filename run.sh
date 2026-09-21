#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"

cd "$ROOT_DIR"


echo "======================================"
echo " ASTRA — starting"
echo "======================================"


docker-compose up -d


echo
echo "Waiting for ML service..."

until docker-compose exec -T ml \
    python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)" \
    >/dev/null 2>&1
do
    sleep 1
done


echo "ML service: OK"


echo
echo "Waiting for backend..."

until docker-compose exec -T backend \
    python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" \
    >/dev/null 2>&1
do
    sleep 1
done


echo "Backend: OK"


echo
echo "Waiting for frontend..."

until docker-compose exec -T frontend \
    wget -qO- \
    http://127.0.0.1:5173 \
    >/dev/null 2>&1
do
    sleep 1
done


echo "Frontend: OK"


echo
echo "Checking full Backend -> ML pipeline..."

docker-compose exec -T backend \
    python -c \
    "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/ml/predict/900001').read().decode())"


echo
echo "======================================"
echo " ASTRA is running"
echo "======================================"

echo
echo "Frontend:"
echo "  http://127.0.0.1:5173"

echo
echo "Backend:"
echo "  http://127.0.0.1:8000"

echo
echo "Backend Swagger:"
echo "  http://127.0.0.1:8000/docs"

echo
echo "ML service:"
echo "  http://127.0.0.1:9000"

echo
echo "ML Swagger:"
echo "  http://127.0.0.1:9000/docs"

echo
echo "Stop:"
echo "  docker-compose down"
echo
