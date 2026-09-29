#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ASTRA_PROJECT_DIR="$PROJECT_DIR"
cd "$PROJECT_DIR"
# shellcheck source=scripts/docker-compose.sh
source "$PROJECT_DIR/scripts/docker-compose.sh"

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

service_url() {
    local service="$1" container_port="$2" binding="" published_port
    while IFS= read -r binding; do
        [[ -n "$binding" ]] && break
    done < <(astra_compose port "$service" "$container_port")
    published_port="${binding##*:}"
    if [[ ! "$published_port" =~ ^[0-9]+$ ]]; then
        echo "Ошибка: Docker не сообщил внешний порт сервиса $service." >&2
        return 1
    fi
    printf 'http://127.0.0.1:%s' "$published_port"
}

reset_db_init() {
    # Compose reuses completed one-shot containers and cannot see changes inside
    # bind-mounted SQL files. Recreate db-init on every run so migrations are
    # applied and a container left by a failed launch cannot poison the next one.
    astra_compose_with_recovery rm -sf db-init >/dev/null
}

show_start_failure() {
    echo >&2
    echo "ASTRA не запустилась. Состояние сервисов:" >&2
    astra_compose ps -a >&2 || true
    echo >&2
    echo "Журнал инициализации базы данных:" >&2
    astra_compose logs --no-color --tail=100 db-init postgres >&2 || true
    show_network_diagnostics
}

show_network_diagnostics() {
    # db-init reaches PostgreSQL by the service name: show where the containers really are.
    local container_id="" network
    read -r container_id < <(astra_compose ps -q postgres 2>/dev/null) || true
    [[ -n "$container_id" ]] || return 0
    echo >&2
    echo "Сеть Docker для PostgreSQL:" >&2
    astra_docker inspect --format '{{range $name, $net := .NetworkSettings.Networks}}{{$name}} {{$net.IPAddress}}{{"\n"}}{{end}}' \
        "$container_id" >&2 2>/dev/null || true
    network="$(astra_docker inspect --format '{{range $name, $net := .NetworkSettings.Networks}}{{$name}}{{end}}' \
        "$container_id" 2>/dev/null || true)"
    if [[ -n "$network" ]]; then
        echo "Контейнеры в сети $network:" >&2
        astra_docker network inspect --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}' \
            "$network" >&2 2>/dev/null || true
    fi
}

compose_up() {
    astra_compose_with_recovery up -d "$@"
}

# Start services; if it fails and firewalld was blocking the (possibly just created)
# ASTRA network, allow it and start once more.
start_services() {
    astra_firewalld_allow_bridge || true
    reset_db_init
    compose_up "$@" && return 0
    if astra_firewalld_allow_bridge; then
        echo "Повторяю запуск после настройки firewalld..."
        reset_db_init
        compose_up "$@" && return 0
    fi
    show_start_failure
    return 1
}

start_project() {
    local app_url api_url
    astra_remove_stale_recreates
    if [[ "$COMMAND" == quick ]]; then
        start_services || return 1
    else
        start_services --build || return 1
    fi
    wait_for_services
    app_url="$(service_url frontend 5173)"
    api_url="$(service_url backend 8000)"
    echo
    echo "ASTRA готова: $app_url"
    echo "API: $api_url/docs"
    if [[ "${ASTRA_OPEN_BROWSER:-1}" == 1 ]] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$app_url" >/dev/null 2>&1 &
    fi
}

check_project() {
    # No host npm, Python, curl or .venv is required.
    astra_compose build backend frontend
    start_services postgres db-init || return 1
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
    stop) astra_compose_with_recovery down; echo "ASTRA остановлена. Загруженная БД сохранена." ;;
    status) astra_compose ps ;;
    logs) astra_compose logs -f ;;
esac
