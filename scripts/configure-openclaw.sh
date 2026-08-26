#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v openclaw >/dev/null 2>&1 || {
  echo "OpenClaw is not installed. Run ./cipher setup." >&2
  exit 1
}

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env"
set +a

if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  echo "OPENCLAW_GATEWAY_TOKEN is missing from .env. Run ./cipher setup." >&2
  exit 1
fi
AGENT_ID="${OPENCLAW_AGENT_ID:-cipher}"
if [[ ! "$AGENT_ID" =~ ^[A-Za-z][A-Za-z0-9_-]{0,63}$ ]]; then
  echo "OPENCLAW_AGENT_ID is invalid." >&2
  exit 1
fi

STATE_DIR="${CIPHER_STATE_DIR:-$ROOT_DIR/state}"
if [[ "$STATE_DIR" != /* ]]; then
  STATE_DIR="$ROOT_DIR/${STATE_DIR#./}"
fi
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
umask 077
gateway_token_file="$STATE_DIR/openclaw-gateway-token"
printf '%s' "$OPENCLAW_GATEWAY_TOKEN" > "$gateway_token_file"
chmod 600 "$gateway_token_file"

openclaw plugins install @openclaw/codex
openclaw plugins install @openclaw/acpx
openclaw config set gateway.bind loopback
openclaw config set gateway.auth.mode token
openclaw config set secrets.providers.cipher_gateway \
  "{\"source\":\"file\",\"path\":\"$gateway_token_file\",\"mode\":\"singleValue\"}"
openclaw config set gateway.auth.token \
  '{"source":"file","provider":"cipher_gateway","id":"value"}'
openclaw config set gateway.http.endpoints.responses.enabled true
openclaw config set tools.exec.mode auto
openclaw config set plugins.entries.codex.enabled true
openclaw config set plugins.entries.codex.config.discovery.enabled true
openclaw config set plugins.entries.codex.config.appServer.mode guardian
openclaw config set plugins.entries.codex.config.codexPlugins.enabled false
openclaw config set plugins.entries.codex.config.computerUse.enabled false
openclaw config set plugins.entries.acpx.enabled true
openclaw config set plugins.entries.acpx.config.permissionMode approve-reads
openclaw config set plugins.entries.acpx.config.nonInteractivePermissions deny
openclaw config set plugins.entries.acpx.config.probeAgent claude
openclaw config set plugins.entries.acpx.config.pluginToolsMcpBridge false
openclaw config set plugins.entries.acpx.config.openClawToolsMcpBridge false
openclaw config set acp.enabled true
openclaw config set acp.backend acpx
openclaw config set acp.defaultAgent claude
openclaw config set acp.allowedAgents '["claude"]'

if [[ -n "${BRAVE_API_KEY:-}" ]]; then
  brave_key_file="$STATE_DIR/brave-api-key"
  printf '%s' "$BRAVE_API_KEY" > "$brave_key_file"
  chmod 600 "$brave_key_file"
  openclaw config set secrets.providers.cipher_brave \
    "{\"source\":\"file\",\"path\":\"$brave_key_file\",\"mode\":\"singleValue\"}"
  openclaw config set plugins.entries.brave.enabled true
  openclaw config set plugins.entries.brave.config.webSearch.apiKey \
    '{"source":"file","provider":"cipher_brave","id":"value"}'
  openclaw config set tools.web.search.provider brave
fi

if ! openclaw agents list 2>/dev/null | grep -Eq "(^|[[:space:]])${AGENT_ID}([[:space:]]|$)"; then
  agent_args=(agents add "$AGENT_ID" --workspace "$ROOT_DIR/agents/cipher" --non-interactive)
  if [[ -n "${CIPHER_PRIMARY_MODEL:-}" ]]; then
    agent_args+=(--model "$CIPHER_PRIMARY_MODEL")
  fi
  openclaw "${agent_args[@]}"
elif [[ -n "${CIPHER_PRIMARY_MODEL:-}" ]]; then
  openclaw config set "agents.entries.${AGENT_ID}.model" "$CIPHER_PRIMARY_MODEL"
fi

openclaw config set "agents.entries.${AGENT_ID}.tools.allow" \
  '["cipher-tools__*","group:web","group:memory","sessions_spawn","session_status"]'
openclaw config set "agents.entries.${AGENT_ID}.tools.deny" \
  '["group:runtime","group:fs","group:nodes"]'
openclaw config set "agents.entries.${AGENT_ID}.tools.elevated.enabled" false

primary_runtime="${CIPHER_PRIMARY_RUNTIME:-codex}"
case "$primary_runtime" in
  codex|openclaw)
    openclaw config set "agents.entries.${AGENT_ID}.models" \
      "{\"openai/*\":{\"agentRuntime\":{\"id\":\"$primary_runtime\"}}}" \
      --strict-json --merge
    ;;
  *)
    echo "CIPHER_PRIMARY_RUNTIME must be codex or openclaw." >&2
    exit 1
    ;;
esac

if openclaw mcp status 2>/dev/null | grep -q 'cipher-tools'; then
  echo "Cipher MCP server is already registered."
else
  openclaw mcp add cipher-tools --command "$ROOT_DIR/scripts/run-mcp.sh" --cwd "$ROOT_DIR"
fi
openclaw config set mcp.servers.cipher-tools.codex.agents "[\"$AGENT_ID\"]"

openclaw gateway install
echo "OpenClaw is configured. Restart the gateway after authentication."
echo "An empty CIPHER_PRIMARY_MODEL leaves model choice to current OpenClaw/Codex discovery."
