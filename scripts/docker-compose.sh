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

astra_compose_name() {
    astra_detect_compose
    printf '%s' "${ASTRA_COMPOSE_COMMAND[*]}"
}
