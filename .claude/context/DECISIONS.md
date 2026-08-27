# Decisions

<!-- Format per entry:
## [OPEN|RESOLVED] Decision title
- **Decision:** what was decided
- **Reason:** why
- **Date:** YYYY-MM-DD
-->

## [RESOLVED] Skip explicit OpenClaw model auth; rely on Codex CLI auto-discovery
- **Decision:** Did not run `openclaw models auth login/paste-api-key` for the openai provider.
  `CIPHER_PRIMARY_RUNTIME=codex` routes `openai/*` through the codex-runtime harness, which
  auto-discovers the existing local Codex CLI session (`~/.codex/auth.json`) at generation time
  per OpenClaw's documented external-CLI-credential-discovery semantics.
- **Reason:** User already has both Codex CLI and Claude Code authenticated on this server via
  their own subscriptions and wants to use those instead of paying for a separate OpenAI API
  key. Confirmed working end-to-end: `./cipher doctor` shows "Codex authentication: OpenAI
  profile detected" and a real Alexa request got a live response with no explicit auth step.
- **Date:** 2026-08-27

## [RESOLVED] Mixed-model routing -- fast-responder tier moved off paid OpenAI
- **Decision:** Cipher's fast-responder ("handle directly") tier now runs on NVIDIA's free
  hosted `nemotron-3-super-120b-a12b` (two independent free accounts as fallbacks, then
  `openai/gpt-5.4-nano` as a final paid safety net), instead of going straight to OpenAI.
  Delegation to `cipher-specialist-codex` for real reasoning is unchanged.
- **Reason:** Two other free options were evaluated and rejected first: a local Ollama model
  (this laptop's CPU-only inference measured ~8 tok/s -- 25s+ per answer, and small models broke
  the no-markdown speech rule); Groq (raw model latency was excellent, sub-second, but its free
  tier's 429 rate limit plus OpenClaw's retry backoff produced real request latency of 25-38s
  after only a handful of calls). NVIDIA's hosted models were consistently fast (<500ms per model
  call, verified via direct instrumentation) and free with no rate-limiting observed across 8+
  test calls. Full detail and reproducible config commands: `docs/OPENCLAW.md`.
- **Date:** 2026-08-27

## [RESOLVED] Every new model provider gets an explicit embedded-runtime pin
- **Decision:** Any newly added provider (`nvidia/*`, `nvidia-2/*`, and the now-unused `groq/*`)
  gets an explicit `agentRuntime.id: "openclaw"` override in `agents.list[1].models`, matching
  the existing `openai/gpt-5.4-nano` pattern -- never left to OpenClaw's `auto` resolution.
- **Reason:** `auto` only falls back to the safe embedded runtime when no registered harness
  claims the provider; relying on that implicitly, rather than pinning explicitly, is exactly the
  kind of silent gap that caused the original Codex-harness `tools.deny`-bypass vulnerability this
  project was built to close. Verified live via `openclaw sessions list --all-agents --json`
  showing `agentRuntime: {id: "openclaw", source: "model"}` (pin-driven, not a coincidental
  default) before trusting the new provider with real traffic.
- **Date:** 2026-08-27

## [RESOLVED] Proactive Alexa announcements live in bridge code, not as an agent tool
- **Decision:** The proactive-announcement feature (`src/alexa_bridge/announce.py`) is invoked
  deterministically from the bridge's own background-task-completion path in `app.py`, not
  exposed to the LLM as a callable MCP tool.
- **Reason:** Announcing reliably (checking do-not-disturb, only firing for genuinely late tasks)
  needs to not depend on the model remembering to call it. Keeping it server-side also avoids
  adding a new agent-callable tool that could message an arbitrary HA notify target -- the target
  device/service and the DND entity are fixed server-side config, not something the model chooses.
- **Date:** 2026-08-27

## [RESOLVED] Pin PATH for OpenClaw's npm-installed bin directory
- **Decision:** Added `export PATH="/home/jitesh/.hermes/node/bin:$PATH"` to `~/.bashrc`.
- **Reason:** OpenClaw's official installer put its bin link at
  `~/.hermes/node/bin/openclaw`, which wasn't on PATH by default, causing `./cipher setup` to
  report "OpenClaw is not installed" even after a successful install.
- **Date:** 2026-08-27
