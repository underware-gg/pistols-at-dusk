#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  printf >&2 '%s\n' "Python is not available. Create .venv or ensure python3 is on PATH."
  exit 127
fi

"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m unittest discover tests
"$PYTHON" -m coverage report -m
