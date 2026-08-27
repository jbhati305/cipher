#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

AUTH_KEYS="${CIPHER_CENTRAL_AUTH_KEYS:-$HOME/.auth_keys.sh}"
ENV_VARS="${CIPHER_CENTRAL_ENV_VARS:-$HOME/.env_vars.sh}"

for f in "$AUTH_KEYS" "$ENV_VARS"; do
  if [[ ! -f "$f" ]]; then
    echo "Central env file not found: $f" >&2
    echo "Create it (see docs/SECRETS.md) or set CIPHER_CENTRAL_AUTH_KEYS / CIPHER_CENTRAL_ENV_VARS to point elsewhere." >&2
    exit 1
  fi
  mode="$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f" 2>/dev/null || echo '')"
  if [[ -n "$mode" && "$mode" != "600" ]]; then
    echo "Warning: $f has permissions $mode, expected 600. Run: chmod 600 $f" >&2
  fi
done

# shellcheck disable=SC1090
source "$AUTH_KEYS"
# shellcheck disable=SC1090
source "$ENV_VARS"

for required in OPENCLAW_GATEWAY_TOKEN ALEXA_ID_HMAC_SECRET; do
  if [[ -z "${!required:-}" ]]; then
    echo "$required is empty in the central files. ./cipher setup normally generates this; if it's" >&2
    echo "genuinely missing, set it in $AUTH_KEYS with: openssl rand -hex 32" >&2
    exit 1
  fi
done

umask 077
cat > .env <<ENVFILE
# Runtime
CIPHER_ENV=${CIPHER_ENV:-production}
CIPHER_LOG_LEVEL=${CIPHER_LOG_LEVEL:-INFO}
CIPHER_VERBOSE_REQUEST_LOGGING=${CIPHER_VERBOSE_REQUEST_LOGGING:-false}
CIPHER_CONFIG_DIR=${CIPHER_CONFIG_DIR:-./config}
CIPHER_STATE_DIR=${CIPHER_STATE_DIR:-./state}

# OpenClaw: keep the Gateway bound to loopback.
OPENCLAW_BASE_URL=${OPENCLAW_BASE_URL:-http://127.0.0.1:18789}
OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN}
OPENCLAW_AGENT_ID=${OPENCLAW_AGENT_ID:-cipher}
CIPHER_PRIMARY_RUNTIME=${CIPHER_PRIMARY_RUNTIME:-codex}
# Empty means use the current model selected/discovered by OpenClaw/Codex.
CIPHER_PRIMARY_MODEL=${CIPHER_PRIMARY_MODEL:-}

# Home Assistant
HOME_ASSISTANT_URL=${HOME_ASSISTANT_URL:-http://127.0.0.1:8123}
HOME_ASSISTANT_TOKEN=${HOME_ASSISTANT_TOKEN:-}
HOME_ASSISTANT_TIMEOUT_SECONDS=${HOME_ASSISTANT_TIMEOUT_SECONDS:-5}

# Alexa bridge. Generate with: openssl rand -hex 32
ALEXA_ID_HMAC_SECRET=${ALEXA_ID_HMAC_SECRET}
# From the Alexa Developer Console: Custom Skill -> Endpoint -> Skill ID.
ALEXA_SKILL_ID=${ALEXA_SKILL_ID:-}
ALEXA_BRIDGE_HOST=${ALEXA_BRIDGE_HOST:-127.0.0.1}
ALEXA_BRIDGE_PORT=${ALEXA_BRIDGE_PORT:-8787}
ALEXA_SYNC_BUDGET_SECONDS=${ALEXA_SYNC_BUDGET_SECONDS:-6}
ALEXA_OPENCLAW_TIMEOUT_SECONDS=${ALEXA_OPENCLAW_TIMEOUT_SECONDS:-120}
ALEXA_REQUEST_MAX_BYTES=${ALEXA_REQUEST_MAX_BYTES:-16384}
ALEXA_SIGNATURE_MAX_AGE_SECONDS=${ALEXA_SIGNATURE_MAX_AGE_SECONDS:-150}
ALEXA_RATE_LIMIT_PER_MINUTE=${ALEXA_RATE_LIMIT_PER_MINUTE:-20}

# Optional web-search provider consumed by OpenClaw, not Cipher services.
BRAVE_API_KEY=${BRAVE_API_KEY:-}
ENVFILE
chmod 600 .env

echo "Regenerated .env from $AUTH_KEYS and $ENV_VARS."
echo "Restart services to pick up any changes: ./cipher restart"
