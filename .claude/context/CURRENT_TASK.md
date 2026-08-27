# Current Task

## Goal
Server-side install of Cipher (OpenClaw/Codex/Claude/MCP/HA stack) and first Alexa Custom Skill
connectivity through the self-hosted bridge — DONE as of 2026-08-27 (see CHANGED_FILES.md /
NEXT_STEPS.md for what's left optional).

## Scope
In scope: repo clone/setup, OpenClaw + Codex + Claude auth, Tailscale Funnel exposure, Alexa
skill endpoint wiring, fixing any install/runtime bugs hit along the way, committing/pushing
fixes. Out of scope: Amazon Developer Console work (user does this themselves), AWS/Lambda
(architecture has none), weakening the loopback-only binding on the bridge/Gateway/MCP server.

## Project Context
Python 3.11+ repo ("cipher-assistant") built with `uv` (not pip/venv directly): `uv sync --extra
dev`, `uv run pytest`, `uv run ruff check .`. FastAPI-based Alexa bridge (`src/alexa_bridge/`)
verifies Alexa's own request signatures directly (no AWS Lambda) and is reached over a Tailscale
Funnel HTTPS URL. `src/cipher_mcp/` is a typed, allowlisted MCP server (server metrics, Docker,
systemd, Home Assistant) exposed to an OpenClaw-managed `cipher` agent that runs on the native
Codex app-server harness, with Claude Code as an optional ACP specialist. `./cipher` is the
management CLI (setup/configure/auth/up/down/status/doctor/logs/alexa/tunnel/update) — run
`./cipher help` for the full list. Tests live in `tests/`, config allowlists in `config/*.yaml`
(generated from `.example.yaml`, gitignored), secrets in `.env` (gitignored).

## Status
active
