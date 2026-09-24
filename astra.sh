#!/usr/bin/env bash

set -euo pipefail


PROJECT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"

BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
SOURCE_AGENT_FILE="$PROJECT_DIR/source_agent/main.py"

RUNTIME_DIR="$PROJECT_DIR/.astra-runtime"
SOURCE_AGENT_PID_FILE="$RUNTIME_DIR/source-agent.pid"
SOURCE_AGENT_LOG_FILE="$RUNTIME_DIR/source-agent.log"

APP_URL="http://127.0.0.1:5173"
API_URL="http://127.0.0.1:8000"
SOURCE_AGENT_URL="http://127.0.0.1:9100"

COMMAND="${1:-run}"


print_header() {
    echo
    echo "======================================"
    echo " ASTRA"
    echo "======================================"
    echo
}


check_dependencies() {
    echo "[1/7] Проверка инструментов..."

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

    if [ ! -f "$SOURCE_AGENT_FILE" ]; then
        echo "Ошибка: не найден source_agent/main.py"
        exit 1
    fi

    echo "OK"
}


source_agent_is_ready() {
    curl -fsS \
        "$SOURCE_AGENT_URL/health" \
        >/dev/null 2>&1
}


start_source_agent() {
    echo
    echo "[2/7] Запуск Source Agent..."

    mkdir -p "$RUNTIME_DIR"

    if source_agent_is_ready; then
        echo "Source Agent уже запущен"
        return 0
    fi

    rm -f "$SOURCE_AGENT_PID_FILE"

    nohup \
        "$BACKEND_DIR/.venv/bin/python" \
        "$SOURCE_AGENT_FILE" \
        >"$SOURCE_AGENT_LOG_FILE" 2>&1 &

    local agent_pid=$!

    echo "$agent_pid" \
        > "$SOURCE_AGENT_PID_FILE"

    echo "PID: $agent_pid"
    echo "Ожидание Source Agent..."

    local attempts=30

    for ((i = 1; i <= attempts; i++)); do
        if source_agent_is_ready; then
            echo "Source Agent готов"
            return 0
        fi

        if ! kill -0 "$agent_pid" 2>/dev/null; then
            echo
            echo "Ошибка: Source Agent завершился."
            echo
            echo "Лог:"
            cat "$SOURCE_AGENT_LOG_FILE" || true
            exit 1
        fi

        sleep 1
    done

    echo
    echo "Ошибка: Source Agent не запустился за 30 секунд."
    echo "Лог: $SOURCE_AGENT_LOG_FILE"
    exit 1
}


stop_source_agent() {
    if [ ! -f "$SOURCE_AGENT_PID_FILE" ]; then
        echo "Source Agent PID не найден"
        return 0
    fi

    local agent_pid

    agent_pid="$(
        cat "$SOURCE_AGENT_PID_FILE"
    )"

    if kill -0 "$agent_pid" 2>/dev/null; then
        echo "Останавливаю Source Agent..."

        kill "$agent_pid" 2>/dev/null || true

        for _ in {1..10}; do
            if ! kill -0 "$agent_pid" 2>/dev/null; then
                break
            fi

            sleep 0.2
        done
    fi

    rm -f "$SOURCE_AGENT_PID_FILE"

    echo "Source Agent остановлен"
}


start_database() {
    echo
    echo "[3/7] Запуск PostgreSQL..."

    cd "$PROJECT_DIR"

    docker-compose up -d --no-build postgres

    echo "Ожидание PostgreSQL..."

    local attempts=30

    for ((i = 1; i <= attempts; i++)); do
        if docker-compose exec -T postgres \
            pg_isready -U astra -d astra \
            >/dev/null 2>&1; then

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
    echo "[4/7] Backend tests..."

    cd "$BACKEND_DIR"

    .venv/bin/python -m pytest -q

    echo "Backend OK"
}


build_frontend() {
    echo
    echo "[5/7] Frontend build..."

    cd "$FRONTEND_DIR"

    npm run build

    echo "Frontend OK"
}


start_services() {
    echo
    echo "[6/7] Запуск Docker-сервисов..."

    cd "$PROJECT_DIR"

    docker-compose up -d --no-build

    echo "Docker-сервисы запущены"
}


wait_for_services() {
    echo
    echo "[7/7] Ожидание ASTRA..."

    local attempts=30

    for ((i = 1; i <= attempts; i++)); do
        if \
            source_agent_is_ready \
            && curl -fsS \
                "$API_URL/openapi.json" \
                >/dev/null 2>&1 \
            && curl -fsS \
                "$APP_URL" \
                >/dev/null 2>&1
        then
            echo
            echo "ASTRA готова."
            echo
            echo "Frontend:     $APP_URL"
            echo "API:          $API_URL"
            echo "Swagger:      $API_URL/docs"
            echo "Source Agent: $SOURCE_AGENT_URL"
            echo
            echo "Источник данных выбирается"
            echo "после запуска ASTRA."
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
    echo "  ./astra.sh status"
    echo "  ./astra.sh logs"
    echo "  cat $SOURCE_AGENT_LOG_FILE"

    exit 1
}


open_browser() {
    if command -v xdg-open >/dev/null 2>&1; then
        echo "Открываю ASTRA в браузере..."

        xdg-open \
            "$APP_URL" \
            >/dev/null 2>&1 &
    else
        echo "Открой вручную: $APP_URL"
    fi
}


run_project() {
    print_header
    check_dependencies
    start_source_agent
    start_database
    run_backend_tests
    build_frontend
    start_services
    wait_for_services
    open_browser
}


rebuild_project() {
    print_header

    check_dependencies
    start_source_agent

    echo
    echo "Полная пересборка ASTRA..."
    echo

    cd "$PROJECT_DIR"

    docker-compose up \
        --build \
        -d

    wait_for_services
    open_browser
}


stop_project() {
    print_header

    cd "$PROJECT_DIR"

    echo "Останавливаю Docker-сервисы..."

    docker-compose down

    stop_source_agent

    echo
    echo "ASTRA остановлена."
}


show_status() {
    print_header

    cd "$PROJECT_DIR"

    echo "Docker:"
    docker-compose ps

    echo
    echo "Source Agent:"

    if source_agent_is_ready; then
        curl -s \
            "$SOURCE_AGENT_URL/health"

        echo
    else
        echo "не запущен"
    fi

    echo
    echo "Источник данных:"

    if source_agent_is_ready; then
        curl -s \
            "$SOURCE_AGENT_URL/source/status"

        echo
    else
        echo "недоступен"
    fi
}


show_logs() {
    print_header

    echo "=== Source Agent ==="

    if [ -f "$SOURCE_AGENT_LOG_FILE" ]; then
        tail -n 100 \
            "$SOURCE_AGENT_LOG_FILE"
    else
        echo "Лог Source Agent отсутствует"
    fi

    echo
    echo "=== Docker ==="

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
        echo "  ./astra.sh rebuild  полная пересборка"
        echo "  ./astra.sh stop     остановить ASTRA"
        echo "  ./astra.sh status   состояние"
        echo "  ./astra.sh logs     логи"
        exit 1
        ;;
esac
