#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if command -v pyright >/dev/null 2>&1; then
  exec pyright -p pyrightconfig.json
fi

if command -v basedpyright >/dev/null 2>&1; then
  exec basedpyright -p pyrightconfig.json
fi

if command -v pnpm >/dev/null 2>&1; then
  exec pnpm exec pyright -p pyrightconfig.json
fi

if command -v npx >/dev/null 2>&1; then
  exec npx pyright -p pyrightconfig.json
fi

printf >&2 '%s\n' "pyright is not available. Run pnpm install, install pyright/basedpyright, or ensure npx can run pyright."
exit 127
