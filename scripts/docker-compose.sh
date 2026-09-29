#!/usr/bin/env bash

# Shared Docker Compose compatibility layer. Ubuntu commonly installs Compose
# as `docker compose`, while older Fedora/Docker packages may expose the
# standalone `docker-compose` command.
declare -a ASTRA_COMPOSE_COMMAND=()
declare -a ASTRA_DOCKER_COMMAND=(docker)
declare -a ASTRA_SUDO_COMMAND=(sudo --preserve-env=ASTRA_PROJECT_DIR,ASTRA_SOURCE_DIR,FORECAST_WORKERS,FORECAST_BATCH_SIZE,DATASET_BUILD_WORKERS,DATASET_WORK_MEM_MB,DATASET_MAINTENANCE_MEM_MB,DATASET_STORAGE_EXPANSION_FACTOR,DATA_SOURCE,ML_DATA_SOURCE,COMPOSE_PROJECT_NAME)
ASTRA_DOCKER_READY=0

ASTRA_DOCKER_INSTALL_URL="${ASTRA_DOCKER_INSTALL_URL:-https://get.docker.com}"
ASTRA_COMPOSE_PLUGIN_DIR="${ASTRA_COMPOSE_PLUGIN_DIR:-/usr/local/lib/docker/cli-plugins}"
ASTRA_DOCKER_APPARMOR_ISSUE_URL="https://github.com/canonical/docker-snap/issues/190"

astra_docker() {
    "${ASTRA_DOCKER_COMMAND[@]}" "$@"
}

# Runs a command as root: directly for root, otherwise through sudo.
astra_as_root() {
    if ((EUID == 0)); then
        "$@"
    else
        sudo "$@"
    fi
}

# Downloads $1 to file $2 with curl or wget.
astra_download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        echo "Ошибка: для установки Docker нужен curl или wget." >&2
        return 1
    fi
}

# Automatic installation is on by default; ASTRA_AUTO_INSTALL_DOCKER=0 turns it off.
astra_can_install_docker() {
    if [[ "${ASTRA_AUTO_INSTALL_DOCKER:-1}" != 1 ]]; then
        return 1
    fi
    if [[ "$OSTYPE" != linux* ]]; then
        echo "Автоматическая установка Docker поддерживается только в Linux." >&2
        echo "Установите Docker Desktop: https://docs.docker.com/desktop/" >&2
        return 1
    fi
    if ((EUID != 0)) && ! command -v sudo >/dev/null 2>&1; then
        echo "Ошибка: для установки Docker нужны права администратора, а sudo не найден." >&2
        return 1
    fi
}

# Docker Engine + Compose plugin via the official script (Ubuntu, Debian, Fedora, RHEL, CentOS).
astra_install_docker() {
    astra_can_install_docker || return 1
    local installer="${TMPDIR:-/tmp}/astra-get-docker.$$.sh"
    echo "Docker не найден. Устанавливаю Docker Engine и Docker Compose plugin ($ASTRA_DOCKER_INSTALL_URL)..."
    echo "Потребуются права администратора; может понадобиться ваш пароль."
    astra_download "$ASTRA_DOCKER_INSTALL_URL" "$installer" || return 1
    if ! astra_as_root sh "$installer"; then
        rm -f "$installer"
        echo "Ошибка: установка Docker не удалась. Инструкция: https://docs.docker.com/engine/install/" >&2
        return 1
    fi
    rm -f "$installer"
    hash -r
    if ! command -v docker >/dev/null 2>&1; then
        echo "Ошибка: после установки команда docker не найдена." >&2
        return 1
    fi
    if command -v systemctl >/dev/null 2>&1; then
        astra_as_root systemctl enable --now docker || true
    fi
    # Next runs work without sudo after re-login; this run falls back to sudo below.
    if ((EUID != 0)) && [[ -n "${USER:-}" ]]; then
        astra_as_root usermod -aG docker "$USER" || true
    fi
    echo "Docker установлен."
}

# Compose v2 plugin from the official docker/compose release, for Docker without it.
astra_install_compose_plugin() {
    astra_can_install_docker || return 1
    local arch tmp="${TMPDIR:-/tmp}/astra-docker-compose.$$"
    case "$HOSTTYPE" in
        x86_64|amd64) arch=x86_64 ;;
        aarch64|arm64) arch=aarch64 ;;
        *) echo "Ошибка: нет сборки Docker Compose для архитектуры $HOSTTYPE." >&2; return 1 ;;
    esac
    echo "Docker Compose не найден. Устанавливаю Docker Compose plugin в $ASTRA_COMPOSE_PLUGIN_DIR..."
    astra_download "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$arch" "$tmp" \
        || return 1
    astra_as_root mkdir -p "$ASTRA_COMPOSE_PLUGIN_DIR" \
        && astra_as_root install -m 0755 "$tmp" "$ASTRA_COMPOSE_PLUGIN_DIR/docker-compose"
    local status=$?
    rm -f "$tmp"
    return "$status"
}

astra_prepare_docker() {
    if [[ "$ASTRA_DOCKER_READY" == 1 ]]; then return 0; fi
    if ! command -v docker >/dev/null 2>&1 && ! astra_install_docker; then
        echo "Ошибка: установите Docker Engine и Docker Compose plugin, затем повторите ./astra.sh." >&2
        echo "Инструкция: https://docs.docker.com/engine/install/" >&2
        return 1
    fi
    if ! astra_docker info >/dev/null 2>&1; then
        local context endpoint
        context="${DOCKER_CONTEXT:-$(docker context show 2>/dev/null || true)}"
        endpoint="${DOCKER_HOST:-unix:///var/run/docker.sock}"
        # Rootless, remote and Desktop contexts must keep their selected daemon.
        if [[ "${context:-default}" != default || "$endpoint" != unix:///var/run/docker.sock ]]; then
            echo "Ошибка: недоступен выбранный Docker context ($context, $endpoint). Запустите соответствующий Docker и повторите команду." >&2
            return 1
        fi
        if ((EUID != 0)); then
            if ! command -v sudo >/dev/null 2>&1; then
                echo "Ошибка: нет доступа к Docker socket и не найден sudo. Администратору нужно настроить доступ к Docker." >&2
                return 1
            fi
            echo "Для доступа к системному Docker требуются права администратора."
            echo "Docker-команды будут выполнены через sudo; может потребоваться ваш пароль."
            sudo -v || return 1
            ASTRA_DOCKER_COMMAND=("${ASTRA_SUDO_COMMAND[@]}" docker)
        fi
        if ! astra_docker info >/dev/null 2>&1; then
            if command -v systemctl >/dev/null 2>&1; then
                echo "Запуск службы Docker..."
                if ((EUID == 0)); then
                    systemctl start docker || return 1
                else
                    sudo systemctl start docker || return 1
                fi
            fi
            if ! astra_docker info >/dev/null 2>&1; then
                echo "Ошибка: Docker Engine недоступен. Проверьте установку и службу Docker." >&2
                return 1
            fi
        fi
    fi
    astra_detect_compose || return 1
    ASTRA_DOCKER_READY=1
}

astra_detect_compose() {
    if ((${#ASTRA_COMPOSE_COMMAND[@]})); then
        return 0
    fi
    if astra_find_compose; then
        return 0
    fi
    if astra_install_compose_plugin && astra_find_compose; then
        return 0
    fi

    echo "Ошибка: Docker Compose не найден." >&2
    echo "Установите Docker Compose plugin (команда 'docker compose')" >&2
    echo "или legacy docker-compose." >&2
    return 1
}

astra_find_compose() {
    if command -v docker >/dev/null 2>&1 \
        && astra_docker compose version >/dev/null 2>&1; then
        ASTRA_COMPOSE_COMMAND=("${ASTRA_DOCKER_COMMAND[@]}" compose)
        return 0
    fi

    if command -v docker-compose >/dev/null 2>&1; then
        ASTRA_COMPOSE_COMMAND=("$(command -v docker-compose)")
        if [[ "${ASTRA_DOCKER_COMMAND[0]}" == sudo ]]; then
            ASTRA_COMPOSE_COMMAND=("${ASTRA_SUDO_COMMAND[@]}" "${ASTRA_COMPOSE_COMMAND[@]}")
        fi
        if "${ASTRA_COMPOSE_COMMAND[@]}" version >/dev/null 2>&1; then
            return 0
        fi
        ASTRA_COMPOSE_COMMAND=()
    fi
    return 1
}

astra_compose() {
    astra_prepare_docker || return 1
    "${ASTRA_COMPOSE_COMMAND[@]}" "$@"
}

# Some Ubuntu installations of Docker from snap leave an AppArmor profile that
# prevents dockerd/runc from signalling an existing container. In that state
# even `sudo docker stop` returns "permission denied". Recover only containers
# selected by this Compose project, using the host PID reported by Docker. Named
# volumes (including PostgreSQL data) are not removed.
astra_recover_apparmor_containers() {
    local -a container_ids=()
    local container_id pid running found=0

    mapfile -t container_ids < <(astra_compose ps -a -q)
    for container_id in "${container_ids[@]}"; do
        [[ -n "$container_id" ]] || continue
        found=1
        running="$(astra_docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)"
        if [[ "$running" == true ]]; then
            pid="$(astra_docker inspect --format '{{.State.Pid}}' "$container_id" 2>/dev/null || true)"
            if [[ ! "$pid" =~ ^[0-9]+$ ]] || ((pid <= 1)); then
                echo "Ошибка: Docker не сообщил безопасный PID контейнера $container_id." >&2
                return 1
            fi

            echo "Останавливаю зависший контейнер ASTRA ${container_id:0:12}..."
            astra_as_root kill -TERM "$pid" 2>/dev/null || true
            for _ in {1..30}; do
                running="$(astra_docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)"
                [[ "$running" != true ]] && break
                sleep 0.1
            done
            if [[ "$running" == true ]]; then
                astra_as_root kill -KILL "$pid" 2>/dev/null || true
                for _ in {1..20}; do
                    running="$(astra_docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)"
                    [[ "$running" != true ]] && break
                    sleep 0.1
                done
            fi
            if [[ "$running" == true ]]; then
                echo "Ошибка: процесс контейнера $container_id не остановился." >&2
                return 1
            fi
        fi

        # Remove only the container object. Compose recreates it; named volumes survive.
        astra_docker rm -f "$container_id" >/dev/null || return 1
    done

    if ((found == 0)); then
        echo "Ошибка: Compose не нашёл контейнеры ASTRA для восстановления." >&2
        return 1
    fi
}

# Run a Compose mutation and retry it once after the exact Docker/AppArmor stop
# failure. Output remains live because image builds can take several minutes.
astra_compose_with_recovery() {
    local log_file
    local status had_errexit=0

    log_file="$(mktemp "${TMPDIR:-/tmp}/astra-compose.XXXXXX.log")" || {
        echo "Ошибка: не удалось создать временный журнал Docker Compose." >&2
        return 1
    }

    [[ $- == *e* ]] && had_errexit=1
    set +e
    astra_compose "$@" 2>&1 | tee "$log_file"
    status=${PIPESTATUS[0]}
    ((had_errexit)) && set -e

    if ((status == 0)); then
        rm -f "$log_file"
        return 0
    fi
    if ! grep -Eqi 'cannot (stop|kill) container.*permission denied' "$log_file"; then
        rm -f "$log_file"
        return "$status"
    fi

    echo >&2
    echo "Docker не может остановить контейнеры из-за сбоя AppArmor." >&2
    echo "Восстанавливаю только контейнеры ASTRA; загруженная БД сохранится." >&2
    if [[ "${ASTRA_AUTO_REPAIR_DOCKER:-1}" != 1 ]] || ! astra_recover_apparmor_containers; then
        rm -f "$log_file"
        echo "Автовосстановление Docker не выполнено." >&2
        echo "Описание известной проблемы Ubuntu: $ASTRA_DOCKER_APPARMOR_ISSUE_URL" >&2
        echo "После обновления Docker или перезагрузки системы повторите ./astra.sh." >&2
        return "$status"
    fi

    rm -f "$log_file"
    echo "Контейнеры ASTRA восстановлены. Повторяю команду Docker Compose..."
    astra_compose "$@"
}

astra_compose_name() {
    astra_detect_compose
    printf '%s' "${ASTRA_COMPOSE_COMMAND[*]}"
}
