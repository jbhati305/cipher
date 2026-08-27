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

## [OPEN] Mixed-model routing (cheap API key for simple queries, subscription CLIs for complex)
- **Decision:** Not implemented. User proposed routing simple queries through a cheap API-key
  model (e.g. gpt-mini) and complex queries through the Codex/Claude CLI subscriptions for cost
  reasons. The repo's per-model `agentRuntime` config (`agents.list[<n>].models["<pattern>"]`)
  already supports this in principle, but no concrete routing rule was designed or applied.
- **Reason:** Scoped out of this session to avoid scope creep on "first Alexa connectivity"
  install work; flagged as a legitimate follow-up tuning decision, not a blocker.
- **Date:** 2026-08-27

## [RESOLVED] Pin PATH for OpenClaw's npm-installed bin directory
- **Decision:** Added `export PATH="/home/jitesh/.hermes/node/bin:$PATH"` to `~/.bashrc`.
- **Reason:** OpenClaw's official installer put its bin link at
  `~/.hermes/node/bin/openclaw`, which wasn't on PATH by default, causing `./cipher setup` to
  report "OpenClaw is not installed" even after a successful install.
- **Date:** 2026-08-27
