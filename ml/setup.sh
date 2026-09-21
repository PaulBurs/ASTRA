#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.."
    pwd
)"

cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"
VENV_DIR="$PROJECT_ROOT/ml/.venv"

echo "ASTRA ML environment setup"
echo "=========================="

echo
echo "[1/4] Checking Python..."

"$PYTHON_BIN" --version

echo
echo "[2/4] Creating ML virtual environment..."

if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "ML virtual environment already exists."
fi

PYTHON="$VENV_DIR/bin/python"

echo
echo "[3/4] Installing dependencies..."

"$PYTHON" -m pip install --upgrade pip

"$PYTHON" -m pip install \
    -r ml/requirements.txt

echo
echo "[4/4] Checking installation..."

"$PYTHON" - <<'PY'
import numpy
import pandas
import sklearn
import joblib
import matplotlib
import pyarrow

print("numpy:", numpy.__version__)
print("pandas:", pandas.__version__)
print("scikit-learn:", sklearn.__version__)
print("joblib:", joblib.__version__)
print("matplotlib:", matplotlib.__version__)
print("pyarrow:", pyarrow.__version__)

print()
print("ASTRA ML environment is ready.")
PY

echo
echo "Activate it with:"
echo
echo "source ml/.venv/bin/activate"
