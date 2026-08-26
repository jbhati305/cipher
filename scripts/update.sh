#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
git status --short
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to update with local changes. Commit or stash them first." >&2
  exit 1
fi
git pull --ff-only
uv sync --extra dev
if command -v openclaw >/dev/null 2>&1; then
  openclaw update
fi
if command -v claude >/dev/null 2>&1; then
  claude update
fi
uv run ruff check .
uv run pytest
./cipher doctor
