#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ASTRA_PROJECT_DIR="$PROJECT_DIR"
cd "$PROJECT_DIR"
# shellcheck source=scripts/docker-compose.sh
source "$PROJECT_DIR/scripts/docker-compose.sh"

APP_URL="http://127.0.0.1:5173"
COMMAND="${1:-run}"

usage() {
    echo "Использование: ./astra.sh [run|quick|check|rebuild|stop|status|logs]"
    echo "  run      собрать с кэшем и запустить (по умолчанию)"
    echo "  quick    запустить готовые образы; недостающие соберутся автоматически"
    echo "  check    backend-тесты и frontend build/lint/test внутри Docker"
    echo "  rebuild  пересобрать образы и запустить приложение"
    echo "  stop     остановить приложение, сохранив БД"
    echo "  status   состояние контейнеров"
    echo "  logs     журнал контейнеров"
}

wait_for_services() {
    local deadline=$((SECONDS + ${ASTRA_WAIT_TIMEOUT:-180}))
    local service container state ready
    echo "Ожидание готовности ASTRA..."
    while ((SECONDS < deadline)); do
        ready=1
        for service in postgres source-agent ml backend frontend; do
            container="$(astra_compose ps -q "$service")"
            state=""
            if [[ -n "$container" ]]; then
                state="$(astra_docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"
            fi
            case "$state" in
                healthy) ;;
                unhealthy|exited|dead)
                    echo "Ошибка: сервис $service — $state." >&2
                    astra_compose logs --tail=50 "$service" >&2
                    return 1
                    ;;
                *) ready=0 ;;
            esac
        done
        if ((ready)); then return 0; fi
        sleep 2
    done
    echo "Ошибка: сервисы не готовы за ${ASTRA_WAIT_TIMEOUT:-180} секунд." >&2
    astra_compose ps >&2
    astra_compose logs --tail=30 >&2
    return 1
}

start_project() {
    if [[ "$COMMAND" == quick ]]; then
        astra_compose up -d
    else
        astra_compose up -d --build
    fi
    wait_for_services
    echo
    echo "ASTRA готова: $APP_URL"
    echo "API: http://127.0.0.1:8000/docs"
    if [[ "${ASTRA_OPEN_BROWSER:-1}" == 1 ]] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$APP_URL" >/dev/null 2>&1 &
    fi
}

check_project() {
    # No host npm, Python, curl or .venv is required.
    astra_compose build backend frontend
    astra_compose up -d postgres db-init
    echo "Backend tests..."
    astra_compose run --rm --no-deps \
        -e DATA_SOURCE=dummy -e ML_DATA_SOURCE=dummy -e ML_SERVICE_URL= \
        backend python -m pytest tests -q
    echo "Frontend build, lint and tests..."
    astra_compose run --rm --no-deps frontend sh -ec 'npm run build && npm run lint && npm test'
    echo "Проверки ASTRA завершены успешно."
}

case "$COMMAND" in
    help|--help|-h) usage; exit 0 ;;
    run|quick|check|rebuild|stop|status|logs) ;;
    *) usage >&2; exit 2 ;;
esac

echo "======================================"
echo " ASTRA"
echo "======================================"
astra_prepare_docker
echo "Docker Compose: $(astra_compose_name)"

case "$COMMAND" in
    run|quick|rebuild) start_project ;;
    check) check_project ;;
    stop) astra_compose down; echo "ASTRA остановлена. Загруженная БД сохранена." ;;
    status) astra_compose ps ;;
    logs) astra_compose logs -f ;;
esac
