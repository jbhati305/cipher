#!/usr/bin/env bash
set -Eeuo pipefail

command -v openclaw >/dev/null 2>&1 || {
  echo "OpenClaw is required first. Run ./cipher setup." >&2
  exit 1
}
openclaw plugins install @openclaw/codex
openclaw config set plugins.entries.codex.enabled true
openclaw config set plugins.entries.codex.config.appServer.mode guardian
echo "Native Codex app-server plugin installed in guardian mode."
