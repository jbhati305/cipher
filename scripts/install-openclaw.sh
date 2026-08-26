#!/usr/bin/env bash
set -Eeuo pipefail

if command -v openclaw >/dev/null 2>&1; then
  echo "OpenClaw already installed: $(openclaw --version)"
  exit 0
fi

echo "Installing OpenClaw with its official host installer (onboarding is deferred)."
curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-onboard
