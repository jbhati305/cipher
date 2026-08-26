# Roadmap

## Next validation milestone

Test one real Echo against a read-only chain: launch Cipher, request server health, then ask a
follow-up about the same container. This validates Alexa recognition, HMAC ingress, stable OpenClaw
session routing, Codex selection, and the MCP boundary without taking a disruptive action.

## Phase 2

- Stronger recovered/background task resumption and reliable completion callbacks.
- Evaluate officially applicable Alexa proactive mechanisms and Home Assistant Alexa notification
  integrations; keep callbacks optional.
- Add an OS-level narrow privileged helper only if a real allowlisted operation cannot run safely as
  the unprivileged service user.

## Phase 3

- Optional Home Assistant voice pipeline and local TTS/speaker notifications.
- Event subscriptions through the Home Assistant WebSocket API where they reduce polling.
- Additional channels: Telegram, WhatsApp, Discord, Signal, and a custom mobile/Web UI.

## Phase 4

- Custom voice hardware or Home Assistant voice satellites with a local `Cipher` wake word.
- This cannot be implemented as a replacement wake word on ordinary Amazon Echo hardware.
