#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PYTHON_BIN:-}"
if [[ -z "$PY_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  else
    PY_BIN="python"
  fi
fi

pytest -q
ruff check .
mypy main.py cogs utils tests
PYTHONPYCACHEPREFIX=/tmp/pycache "$PY_BIN" -m compileall main.py cogs utils tests
