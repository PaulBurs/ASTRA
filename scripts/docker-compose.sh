#!/usr/bin/env bash

# Shared Docker Compose compatibility layer. Ubuntu commonly installs Compose
# as `docker compose`, while older Fedora/Docker packages may expose the
# standalone `docker-compose` command.
declare -a ASTRA_COMPOSE_COMMAND=()
declare -a ASTRA_DOCKER_COMMAND=(docker)
declare -a ASTRA_SUDO_COMMAND=(sudo --preserve-env=ASTRA_PROJECT_DIR,ASTRA_SOURCE_DIR,FORECAST_WORKERS,FORECAST_BATCH_SIZE,DATASET_BUILD_WORKERS,DATASET_WORK_MEM_MB,DATASET_STORAGE_EXPANSION_FACTOR,DATA_SOURCE,ML_DATA_SOURCE,COMPOSE_PROJECT_NAME)
ASTRA_DOCKER_READY=0

astra_docker() {
    "${ASTRA_DOCKER_COMMAND[@]}" "$@"
}

astra_prepare_docker() {
    if [[ "$ASTRA_DOCKER_READY" == 1 ]]; then return 0; fi
    if ! command -v docker >/dev/null 2>&1; then
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

    echo "Ошибка: Docker Compose не найден." >&2
    echo "Установите Docker Compose plugin (команда 'docker compose')" >&2
    echo "или legacy docker-compose." >&2
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
