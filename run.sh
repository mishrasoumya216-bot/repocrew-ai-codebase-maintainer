#!/usr/bin/env bash
# RepoCrew one-shot launcher (macOS/Linux).
set -euo pipefail
cd "$(dirname "$0")"

echo "== RepoCrew setup =="

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
PY=.venv/bin/python

$PY -m pip install -q -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi
(cd frontend && npm run build)

if command -v docker >/dev/null 2>&1; then
  echo "Building repocrew-sandbox image..."
  docker build -t repocrew-sandbox ./sandbox || echo "docker build failed; local fallback will be used"
else
  echo "Docker not found: running in local fallback (NOT isolated)"
fi

[ -f .env ] || cp .env.example .env

echo "RepoCrew listening on http://localhost:8000"
exec $PY -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
