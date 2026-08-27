# Next Steps

## Immediate (do next)
- None blocking — core goal (server install + working Alexa connectivity) is done and verified
  end-to-end (real Echo/Simulator request got a live 200 response through full signature
  verification).

## Upcoming (after immediate)
- Optional: set `HOME_ASSISTANT_TOKEN` in `.env` (HA reachable at `http://127.0.0.1:8123`,
  long-lived access token not yet provided) to enable HA tools through Alexa/MCP.
- Optional: wire up real assistant responses beyond the current echo/live-query smoke test —
  confirm richer multi-turn conversations work through the `cipher` agent's restricted toolset
  (`cipher-tools__*`, `group:web`, `group:memory`, `sessions_spawn`, `session_status`).
- Open decision from DECISIONS.md: mixed-model routing (cheap API-key model for simple queries,
  Codex/Claude CLI subscriptions for complex ones) via per-model `agentRuntime` config — not yet
  designed or applied.
- `agents/cipher/{HEARTBEAT,IDENTITY,TOOLS,USER}.md` + `openclaw-workspace-state.json` are
  OpenClaw's own auto-generated agent scaffolding, currently untracked/uncommitted (deliberately
  left out of the fix commits as out of scope) — revisit if the user wants those version
  controlled too.

## Blocked
- None currently.
