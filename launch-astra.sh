#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR" || exit 1

LOG_FILE="/tmp/astra-launch.log"

echo "Запуск ASTRA..."
echo "Лог: $LOG_FILE"
echo

./astra.sh 2>&1 | tee "$LOG_FILE"

STATUS=${PIPESTATUS[0]}

echo
echo "======================================"

if [ "$STATUS" -eq 0 ]; then
    echo "ASTRA завершила запуск без ошибок."
else
    echo "ASTRA завершилась с ошибкой."
    echo "Код ошибки: $STATUS"
fi

echo
echo "Лог сохранён:"
echo "$LOG_FILE"
echo
read -r -p "Нажмите Enter, чтобы закрыть окно..."

exit "$STATUS"
