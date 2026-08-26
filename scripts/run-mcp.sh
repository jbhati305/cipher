#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing $ROOT_DIR/.env. Run ./cipher setup first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env"
set +a
exec uv run --project "$ROOT_DIR" python -m cipher_mcp.server
