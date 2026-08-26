#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  id_secret="$(openssl rand -hex 32)"
  gateway_token="$(openssl rand -hex 32)"
  sed -i "s/^ALEXA_ID_HMAC_SECRET=.*/ALEXA_ID_HMAC_SECRET=${id_secret}/" .env
  sed -i "s/^OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=${gateway_token}/" .env
  chmod 600 .env
  echo "Created .env with local random secrets."
fi

for name in cipher docker-allowlist services-allowlist home-assistant-allowlist; do
  if [[ ! -f "config/${name}.yaml" ]]; then
    cp "config/${name}.example.yaml" "config/${name}.yaml"
  fi
done

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed. See https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
uv sync --extra dev
mkdir -p state dist
chmod 700 state
echo "Cipher Python environment is ready."
