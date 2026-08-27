# Next Steps

## Immediate (do next)
1. Real-world test via the phone's Alexa app now that all of tonight's fixes are live: routing
   fix, tool-choice fix, no-markdown speech, HA device control, proactive announcements, and the
   NVIDIA model switch. Confirm it feels right end-to-end, not just via server-side verification.
2. Decide whether to clean up the harmless-but-unused Groq leftovers (plugin install,
   `env.GROQ_API_KEY`, `groq/*` runtime pin) or leave them in place -- see `docs/OPENCLAW.md`.
3. Decide what to do with 5 untracked files sitting in `agents/cipher/` (`HEARTBEAT.md`,
   `IDENTITY.md`, `TOOLS.md`, `USER.md`, `openclaw-workspace-state.json`) -- look like generated
   OpenClaw workspace runtime state, not authored source; flagged repeatedly this session but
   never resolved (gitignore them, or commit them, once their purpose is confirmed).

## Upcoming (after immediate)
- Optional longer soak test (10 calls spread over several minutes) on the NVIDIA model to get a
  better real-world read on how often the ~11s latency spike recurs beyond the one anomaly seen.
- Separate, lower-priority: the `cipher-specialist-codex` session still can't be spawned via
  `sessions_spawn(runtime="acp")` for Claude -- needs a narrowly-scoped tool-policy exception
  (not a blanket `group:fs`/`group:runtime` allow). See
  `.superpowers/sdd/2026-08-27-cipher-router-agent/task-3-report.md` for the exact error.

## Blocked
(none)
