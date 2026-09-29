#!/bin/sh
# PostgreSQL for ASTRA with a RAM cache sized from the memory available to Docker.
#
# Budget: ASTRA_DB_CACHE_PERCENT (50 by default) of the RAM visible in the container
# (the computer's RAM with Docker Engine on Linux, the VM size with Docker Desktop),
# or exactly ASTRA_DB_CACHE_MB; never more than 90% of it. Half of the budget is
# PostgreSQL's own cache (shared_buffers). The other half is left for the sorts and index
# builds of dataset preparation, which reads the budget from the setting
# astra.ram_budget_mb (data_pipeline/astra_pipeline/cache.py).
#
# WAL is minimal: nothing replicates this database, and a table filled and made durable
# in one transaction is then written to disk once instead of twice (WAL + table).
# ASTRA_DB_WAL_LEVEL=replica restores the PostgreSQL default.
#
# Used as the entrypoint of the postgres service in compose.yaml: computes the settings and
# hands over to the image's docker-entrypoint.sh. ASTRA_MEMINFO / ASTRA_CGROUP_ROOT are for tests.
set -eu

# Another command (psql, bash, ...) or a question to postgres (--version, --help) runs as
# the image would run it; only the server itself gets the cache settings.
case "${1:-postgres}" in
    postgres) [ $# -eq 0 ] || shift ;;
    -*) ;;
    *) exec docker-entrypoint.sh "$@" ;;
esac
case "${1:-}" in
    --help|-\?|--version|-V|--describe-config) exec docker-entrypoint.sh postgres "$@" ;;
esac

meminfo=${ASTRA_MEMINFO:-/proc/meminfo}
cgroup=${ASTRA_CGROUP_ROOT:-/sys/fs/cgroup}
percent=${ASTRA_DB_CACHE_PERCENT:-50}
fixed=${ASTRA_DB_CACHE_MB:-}
wal_level=${ASTRA_DB_WAL_LEVEL:-minimal}

fail() { echo "ASTRA: $*" >&2; exit 1; }
case "$percent" in ''|*[!0-9]*) fail "ASTRA_DB_CACHE_PERCENT должно быть целым числом процентов" ;; esac
case "$fixed" in *[!0-9]*) fail "ASTRA_DB_CACHE_MB должно быть целым числом мегабайт" ;; esac
[ ${#percent} -le 3 ] && [ ${#fixed} -le 9 ] || fail "ASTRA_DB_CACHE_PERCENT / ASTRA_DB_CACHE_MB: слишком большое значение"
# Without leading zeros: sh arithmetic would read 08 as an (invalid) octal number.
percent=$(printf '%s' "$percent" | sed 's/^0*\([0-9]\)/\1/')
fixed=$(printf '%s' "$fixed" | sed 's/^0*\([0-9]\)/\1/')
case "$wal_level" in minimal|replica|logical) ;; *) fail "ASTRA_DB_WAL_LEVEL: minimal, replica или logical" ;; esac

total_mb=$(awk '/^MemTotal:/ { print int($2 / 1024) }' "$meminfo")
[ -n "$total_mb" ] || fail "не удалось определить объём памяти ($meminfo)"
# A memory limit of the container, if set, is the RAM it may use.
for file in "$cgroup/memory.max" "$cgroup/memory/memory.limit_in_bytes"; do
    [ -r "$file" ] || continue
    limit=$(cat "$file")
    case "$limit" in
        ''|max|*[!0-9]*) ;;
        *) limit_mb=$((limit / 1048576))
           [ "$limit_mb" -ge "$total_mb" ] || total_mb=$limit_mb ;;
    esac
    break
done

if [ -n "$fixed" ]; then budget_mb=$fixed; else budget_mb=$((total_mb * percent / 100)); fi
[ "$budget_mb" -le $((total_mb * 9 / 10)) ] || budget_mb=$((total_mb * 9 / 10))
[ "$budget_mb" -ge 256 ] || budget_mb=256

clamp() { v=$1; [ "$v" -ge "$2" ] || v=$2; [ "$v" -le "$3" ] || v=$3; echo "$v"; }
shared_mb=$((budget_mb / 2))
maintenance_mb=$(clamp $((budget_mb / 16)) 64 2048)
# Disk, not RAM: fewer checkpoints while a dataset is being prepared.
max_wal_mb=$(clamp $((budget_mb / 4)) 1024 16384)

echo "ASTRA: память, доступная Docker: ${total_mb} МБ; кэш БД: ${budget_mb} МБ" \
     "(shared_buffers ${shared_mb} МБ, остальное - сортировки подготовки данных); WAL: ${wal_level}" >&2

set -- postgres \
    -c "shared_buffers=${shared_mb}MB" \
    -c "effective_cache_size=${budget_mb}MB" \
    -c "maintenance_work_mem=${maintenance_mb}MB" \
    -c "max_wal_size=${max_wal_mb}MB" \
    -c "checkpoint_timeout=30min" \
    -c "wal_level=${wal_level}" \
    -c "effective_io_concurrency=200" \
    -c "maintenance_io_concurrency=200" \
    -c "track_io_timing=on" \
    -c "astra.ram_budget_mb=${budget_mb}" \
    "$@"
if [ "$wal_level" = minimal ]; then
    set -- "$@" -c "max_wal_senders=0"
fi
exec docker-entrypoint.sh "$@"
