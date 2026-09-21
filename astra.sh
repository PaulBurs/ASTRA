#!/usr/bin/env bash

set -euo pipefail


PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

APP_URL="http://127.0.0.1:5173"
API_URL="http://127.0.0.1:8000"

COMMAND="${1:-run}"


print_header() {
    echo
    echo "======================================"
    echo " ASTRA"
    echo "======================================"
    echo
}


check_dependencies() {
    echo "[1/6] Проверка инструментов..."

    command -v docker-compose >/dev/null 2>&1 || {
        echo "Ошибка: docker-compose не установлен"
        exit 1
    }

    command -v npm >/dev/null 2>&1 || {
        echo "Ошибка: npm не установлен"
        exit 1
    }

    command -v curl >/dev/null 2>&1 || {
        echo "Ошибка: curl не установлен"
        exit 1
    }

    if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
        echo "Ошибка: не найден backend/.venv"
        exit 1
    fi

    echo "OK"
}


start_database() {
    echo
    echo "[2/6] Запуск PostgreSQL..."

    cd "$PROJECT_DIR"

    docker-compose up -d --no-build postgres

    echo "Ожидание PostgreSQL..."

    local attempts=30

    for ((i = 1; i <= attempts; i++)); do
        if docker-compose exec -T postgres \
            pg_isready -U astra -d astra >/dev/null 2>&1; then

            echo "PostgreSQL готова"
            return 0
        fi

        echo "Ожидание базы... $i/$attempts"
        sleep 1
    done

    echo "Ошибка: PostgreSQL не запустилась"
    exit 1
}


run_backend_tests() {
    echo
    echo "[3/6] Backend tests..."

    cd "$BACKEND_DIR"

    .venv/bin/python -m pytest -q

    echo "Backend OK"
}


build_frontend() {
    echo
    echo "[4/6] Frontend build..."

    cd "$FRONTEND_DIR"

    npm run build

    echo "Frontend OK"
}


start_services() {
    echo
    echo "[5/6] Запуск ASTRA..."

    cd "$PROJECT_DIR"

    docker-compose up -d --no-build

    echo "Docker-сервисы запущены"
}


wait_for_services() {
    echo
    echo "[6/6] Ожидание ASTRA..."

    local attempts=30

    for ((i = 1; i <= attempts; i++)); do
        if curl -fsS "$API_URL/api/health" >/dev/null 2>&1 \
            && curl -fsS "$APP_URL" >/dev/null 2>&1; then

            echo
            echo "ASTRA готова."
            echo
            echo "Frontend: $APP_URL"
            echo "API:      $API_URL"
            echo "Swagger:  $API_URL/docs"
            echo

            return 0
        fi

        echo "Ожидание сервисов... $i/$attempts"
        sleep 1
    done

    echo
    echo "Ошибка: ASTRA не запустилась за 30 секунд."
    echo
    echo "Проверь:"
    echo "  docker-compose ps"
    echo "  docker-compose logs backend"
    echo "  docker-compose logs frontend"

    exit 1
}


open_browser() {
    if command -v xdg-open >/dev/null 2>&1; then
        echo "Открываю ASTRA в браузере..."

        xdg-open "$APP_URL" >/dev/null 2>&1 &
    else
        echo "Открой вручную: $APP_URL"
    fi
}


run_project() {
    print_header
    check_dependencies
    start_database
    run_backend_tests
    build_frontend
    start_services
    wait_for_services
    open_browser
}


rebuild_project() {
    print_header

    echo "Полная пересборка ASTRA..."
    echo

    cd "$PROJECT_DIR"

    docker-compose up --build -d

    wait_for_services
    open_browser
}


stop_project() {
    print_header

    cd "$PROJECT_DIR"

    echo "Останавливаю ASTRA..."

    docker-compose down

    echo
    echo "ASTRA остановлена."
}


show_status() {
    print_header

    cd "$PROJECT_DIR"

    docker-compose ps
}


show_logs() {
    print_header

    cd "$PROJECT_DIR"

    docker-compose logs -f
}


case "$COMMAND" in
    run)
        run_project
        ;;

    rebuild)
        rebuild_project
        ;;

    stop)
        stop_project
        ;;

    status)
        show_status
        ;;

    logs)
        show_logs
        ;;

    *)
        echo "Использование:"
        echo
        echo "  ./astra.sh          запуск ASTRA"
        echo "  ./astra.sh rebuild  полная пересборка Docker"
        echo "  ./astra.sh stop     остановить ASTRA"
        echo "  ./astra.sh status   состояние контейнеров"
        echo "  ./astra.sh logs     логи"
        exit 1
        ;;
esac
