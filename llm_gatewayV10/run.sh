#!/usr/bin/env bash
# Unix / Git Bash launcher. On Windows, prefer:  .\run.ps1  or  run.bat
set -e
cd "$(dirname "$0")"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
PY=".venv/bin/python"
if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "Setting up gateway dependencies (no dev/test packages)..."
  uv sync --no-dev
fi
exec "$PY" main.py
