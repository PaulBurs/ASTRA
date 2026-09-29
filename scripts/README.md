# scripts — запуск ASTRA в Docker

`docker-compose.sh` — библиотека функций для `../astra.sh` (подключается через `source`):
поиск и установка Docker, выбор Compose, доступ через `sudo`, восстановление после
сбоев Docker. Только Bash, без внешних утилит (кроме `docker`, `sudo`, `curl`/`wget`,
`firewall-cmd`), чтобы launcher работал на чистой системе.

## docker-compose.sh

| Функция | Что делает | Как |
|---|---|---|
| `astra_prepare_docker` | Проверяет Docker; при отказе доступа к сокету переключает команды на `sudo`; запускает остановленную службу; выбирает Compose | `docker info`, `systemctl start docker` |
| `astra_install_docker` | Ставит Docker Engine + Compose plugin, если `docker` не найден (Linux); включает службу, добавляет пользователя в группу `docker` | официальный `get.docker.com`, `usermod -aG docker` |
| `astra_install_compose_plugin` | Ставит Compose v2, если есть Docker, но нет Compose | бинарник docker/compose releases → `/usr/local/lib/docker/cli-plugins` |
| `astra_can_install_docker`, `astra_download`, `astra_as_root` | Условия автоустановки (`ASTRA_AUTO_INSTALL_DOCKER=0` — выключить), загрузка, выполнение от root | `curl`/`wget`, `sudo` |
| `astra_detect_compose`, `astra_find_compose` | Выбор `docker compose` (v2) или `docker-compose` (v1) | — |
| `astra_compose`, `astra_docker`, `astra_compose_name` | Вызов Compose/Docker с учётом `sudo` | массивы команд Bash |
| `astra_compose_with_recovery` | Выполняет команду Compose; при сбое остановки контейнеров (AppArmor) или конфликте имени после неудачного пересоздания восстанавливает контейнеры проекта и повторяет один раз | поиск сигнатур ошибок в журнале команды |
| `astra_recover_apparmor_containers` | Останавливает процессы контейнеров проекта по PID хоста и удаляет контейнеры; тома (БД) не затрагиваются | `docker inspect .State.Pid`, `kill -TERM/-KILL`, `docker rm -f` |
| `astra_remove_stale_recreates` | Удаляет остановленные контейнеры проекта с временными именами `<12 hex>_<проект>-…` от прерванного пересоздания | `docker inspect .Name` |
| `astra_firewalld_allow_bridge` | Если firewalld активен и мост сети проекта не в зоне — добавляет его в зону `docker` (или `trusted`) до перезагрузки firewalld | `firewall-cmd --add-interface`, мост `br-<id сети>` |

Автовосстановление (контейнеры, firewalld) отключается `ASTRA_AUTO_REPAIR_DOCKER=0`.

## ../astra.sh

| Функция | Что делает |
|---|---|
| `start_project` | `run`/`quick`/`rebuild`: уборка остатков пересоздания, запуск, ожидание готовности, адреса сервисов |
| `start_services` | Настройка firewalld, пересоздание `db-init`, `docker compose up`; при неудаче из-за firewalld — настройка и один повтор |
| `check_project` | `check`: тесты backend и сборка/линт/тесты frontend внутри контейнеров |
| `wait_for_services` | Ожидание статуса `healthy` всех сервисов с ограничением `ASTRA_WAIT_TIMEOUT` |
| `reset_db_init` | Пересоздание одноразового контейнера `db-init` на каждом запуске (применение SQL) |
| `show_start_failure`, `show_network_diagnostics` | При ошибке: состояние сервисов, журналы `db-init`/`postgres`, IP PostgreSQL и контейнеры сети проекта |
| `service_url` | Внешний адрес сервиса по назначенному Docker порту |

## ../compose.yaml — параметры подготовки и прогноза

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATASET_BUILD_WORKERS` | доступные ядра, 2–8 | параллельные работники подготовки |
| `DATASET_WORK_MEM_MB` | 128 | `work_mem` работника |
| `DATASET_FEATURE_DAYS` | 120 | период ML-признаков на канал (`all` — вся история) |
| `FORECAST_WORKERS` | 4 | параллельные пакеты прогноза (backend и ML-сервис) |
| `FORECAST_BATCH_SIZE` | 256 | датчиков в пакете прогноза |

У `postgres` задан `shm_size: 1g`: 64 МБ `/dev/shm` Docker по умолчанию недостаточно для
параллельного построения индексов. `db-init` при недоступности PostgreSQL выводит ошибку
`psql` и адрес хоста `postgres` в сети Docker.

## tests/test_launcher.py

Контрактные тесты launcher без настоящего Docker: `docker`, `sudo`, `firewall-cmd`, `curl`
подменяются скриптами, `PATH` ограничен. Проверяются автоустановка Docker и Compose,
режим `sudo`, восстановление после AppArmor и конфликта имён, уборка остатков
пересоздания, настройка firewalld, диагностика `db-init`, отсутствие ложного «ASTRA готова».
