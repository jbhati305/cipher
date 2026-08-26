#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
GATEWAY_DROPIN_DIR="$USER_UNIT_DIR/openclaw-gateway.service.d"
mkdir -p "$USER_UNIT_DIR" "$GATEWAY_DROPIN_DIR"
sed "s|@CIPHER_ROOT@|$ROOT_DIR|g" \
  "$ROOT_DIR/infra/systemd/cipher-alexa-bridge.service" \
  > "$USER_UNIT_DIR/cipher-alexa-bridge.service"
# Overwrite Cipher's legacy drop-in, which loaded every application secret into
# the Gateway process. Gateway credentials now use file-backed SecretRefs.
cp "$ROOT_DIR/infra/systemd/openclaw-cipher.conf" \
  "$GATEWAY_DROPIN_DIR/cipher.conf"
systemctl --user daemon-reload
echo "Installed user systemd units. Enable lingering if services must start before login:"
echo "  sudo loginctl enable-linger $USER"
