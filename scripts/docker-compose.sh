#!/usr/bin/env bash

# Shared Docker Compose compatibility layer. Ubuntu commonly installs Compose
# as `docker compose`, while older Fedora/Docker packages may expose the
# standalone `docker-compose` command.
declare -a ASTRA_COMPOSE_COMMAND=()

astra_detect_compose() {
    if ((${#ASTRA_COMPOSE_COMMAND[@]})); then
        return 0
    fi

    if command -v docker >/dev/null 2>&1 \
        && docker compose version >/dev/null 2>&1; then
        ASTRA_COMPOSE_COMMAND=(docker compose)
        return 0
    fi

    if command -v docker-compose >/dev/null 2>&1 \
        && docker-compose version >/dev/null 2>&1; then
        ASTRA_COMPOSE_COMMAND=(docker-compose)
        return 0
    fi

    echo "Ошибка: Docker Compose не найден." >&2
    echo "Установите Docker Compose plugin (команда 'docker compose')" >&2
    echo "или legacy docker-compose." >&2
    return 1
}

astra_compose() {
    astra_detect_compose
    "${ASTRA_COMPOSE_COMMAND[@]}" "$@"
}

astra_compose_name() {
    astra_detect_compose
    printf '%s' "${ASTRA_COMPOSE_COMMAND[*]}"
}
