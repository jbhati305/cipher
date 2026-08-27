# Changed Files

<!-- Format per entry:
## path/to/file.ext
- **Why:** reason for change
- **What changed:** brief summary
- **Last updated:** YYYY-MM-DD
-->

## scripts/configure-openclaw.sh
- **Why:** No published OpenClaw version supports `agents.entries.<id>.*`; agents are keyed by
  array index under `agents.list[]`. Also, plugin install wasn't idempotent.
- **What changed:** Resolve the cipher agent's numeric index via `openclaw agents list --json`
  before setting `agents.list[<n>].tools.allow/deny/elevated.enabled/models`. Check
  `openclaw plugins list --json` before installing codex/acpx plugins, skip if present.
- **Last updated:** 2026-08-27

## scripts/doctor.py
- **Why:** Same `agents.entries` vs `agents.list[]` schema mismatch as configure-openclaw.sh,
  in the "Primary runtime" doctor check.
- **What changed:** Look up the agent's array index via `openclaw agents list --json`, then read
  `agents.list[<n>].models` instead of the nonexistent `agents.entries.<id>.models`.
- **Last updated:** 2026-08-27

## cipher (CLI)
- **Why:** `./cipher auth codex` was broken two ways: `--agent` was placed after the `login`
  subcommand (it's a parent option on `openclaw models auth`), and after fixing that, `login`
  needs a real TTY + often a browser, which a headless server doesn't have; `setup-token` (tried
  as an alternative) fails outright — no token-auth plugin registered for the `openai` provider.
- **What changed:** Moved `--agent <id>` before the subcommand. Switched to
  `login --provider openai --device-code --set-default` (device-code avoids needing a local
  browser). Added a comment noting this step is often unnecessary: OpenClaw auto-discovers an
  already-authenticated local Codex CLI session (`~/.codex/auth.json`) for the codex-runtime
  `openai` provider at generation time — confirmed working via `./cipher doctor` without ever
  running this command.
- **Last updated:** 2026-08-27

## src/alexa_bridge/alexa_signature.py
- **Why:** Root cause of "problem communicating with required skill" on every real Alexa
  request (Echo device and cloud Simulator both failed identically). Certificate-chain validation
  required the last certificate in Alexa's served chain to be self-signed. Amazon's own
  `echo-api` chain ends in "Amazon Root CA 1", which is cross-signed by Starfield's root, not
  self-signed — standard PKI practice, but this check rejected every genuine Alexa request.
- **What changed:** Removed the `root.verify_directly_issued_by(root)` self-signed requirement
  from `_validate_chain`. Per-link issuer verification (each cert directly issued by the next)
  plus leaf SAN/date checks are sufficient and match how real-world verifiers behave.
- **Last updated:** 2026-08-27

## src/alexa_bridge/app.py
- **Why:** The signature-rejection log line only said "alexa signature rejected" with no reason,
  which is what let the cert-chain bug hide behind a generic error for so long during debugging.
- **What changed:** Log `str(exc)` alongside the rejection (still server-side only, in our own
  journal — never exposed in the HTTP response to the caller).
- **Last updated:** 2026-08-27

## tests/test_alexa_signature.py
- **Why:** Need a regression test reproducing Amazon's real certificate chain shape (leaf ->
  intermediate -> cross-signed-but-not-self-signed root) so the cert-chain bug can't reappear
  silently.
- **What changed:** Added `test_chain_ending_in_cross_signed_root_is_accepted`, built with a
  3-cert chain whose top cert is issued by a 4th, deliberately-unincluded CA (not self-signed).
  Confirmed failing before the alexa_signature.py fix, passing after. Uses a unique chain URL to
  avoid colliding with the shared `_cert_cache` keyed by URL across tests in the same process.
- **Last updated:** 2026-08-27

## .gitignore
- **Why:** `.claude/` was blanket-ignored, so context-keeper's own files (`.claude/context/`,
  `.claude/hooks/`, `.claude/settings.json`) never tracked despite being created.
- **What changed:** Changed `.claude/` to `.claude/*` with explicit `!` negations for
  `context/`, `hooks/`, and `settings.json`, keeping everything else under `.claude/` (e.g. any
  future local-only `settings.local.json`) ignored.
- **Last updated:** 2026-08-27

## src/alexa_bridge/openclaw.py
- **Why:** Real Alexa traffic was silently routed to OpenClaw's unrestricted default "main" agent
  instead of the hardened "cipher" agent -- the `x-openclaw-session-key` header lacked the
  `agent:<agentId>:` namespace prefix that OpenClaw actually uses for routing, overriding the
  `x-openclaw-agent-id` header. Verified live: this meant every prior security fix in this project
  had never been exercised by real traffic.
- **What changed:** Session key now built as `f"agent:{self.agent_id}:alexa:{requester_hash}"`.
- **Last updated:** 2026-08-27

## tests/test_openclaw_client.py
- **Why:** The existing test asserted the old buggy bare session-key format as correct.
- **What changed:** Updated to assert the `agent:cipher:alexa:<hash>` format.
- **Last updated:** 2026-08-27

## agents/cipher/AGENTS.md
- **Why:** Three real bugs found via live Alexa testing: (1) skills-allowlist bloat caused the
  model to try `openclaw doctor` for "check server health" instead of the right typed tool; (2)
  spoken responses contained raw markdown (bold, bullets, `---`), which Alexa's TTS reads
  literally; (3) the model echoed a stale tool denial from earlier in the same conversation
  instead of re-calling the tool for the current request (Tubelight control kept failing after
  the underlying allowlist bug was already fixed).
- **What changed:** Added explicit "server health means this exact tool" disambiguation, a
  no-markdown/plain-prose rule for the Alexa channel, and a rule forbidding answering a
  tool-shaped request from memory of a past turn's result.
- **Last updated:** 2026-08-27

## config/home-assistant-allowlist.yaml
- **Why:** `control.entities` held placeholder example entity IDs (`light.office`,
  `light.bedroom`, `switch.desk`) that don't exist on this HA instance -- every real device
  control request was silently denied.
- **What changed:** Replaced with the real entity IDs (`light.bedroom_tubelight_socket_1`,
  `light.wiz_rgbw_tunable_3d3a44`, `switch.lifelong_smart_socket_socket_1`).
- **Last updated:** 2026-08-27

## src/alexa_bridge/announce.py (new)
- **Why:** Alexa Custom Skills are request/response only -- no way to push a result once a
  background task finishes past the sync budget, beyond the existing "ask me for the result"
  pattern.
- **What changed:** New best-effort module: when a background task finishes late, checks the
  Echo's do-not-disturb switch via Home Assistant, and if off, speaks the result through the
  already-installed Alexa Media Player HA integration (`notify.alexa_media_*`). Never raises;
  `TaskStore` is always updated first regardless of announce outcome.
- **Last updated:** 2026-08-27

## src/alexa_bridge/app.py
- **Why:** Wire the new proactive-announcement module into the existing background-task
  completion path, only for tasks that actually missed the sync budget (so a fast inline answer
  is never announced a second time).
- **What changed:** Added `_announce_if_late` helper called from `run_task()` after
  `tasks.complete`/`tasks.fail`; added `announce_transport` DI param to `create_app` for testing.
- **Last updated:** 2026-08-27

## src/alexa_bridge/settings.py
- **Why:** New config needed for the announcement feature and to keep `.env` self-consistent.
- **What changed:** Added `home_assistant_url/token/timeout_seconds`, `proactive_announce_enabled`,
  `alexa_notify_service`, `alexa_dnd_entity` fields (all with safe defaults), plus loopback/shape
  validation for `HOME_ASSISTANT_URL` matching the existing `OPENCLAW_BASE_URL` pattern.
- **Last updated:** 2026-08-27

## scripts/sync-env.sh
- **Why (this session):** The new proactive-announcement env vars weren't in the script's
  explicit allowlist of vars it writes into `.env`, so setting them in the central
  `~/.env_vars.sh` had no effect until the script itself was updated.
- **What changed:** Added `ALEXA_PROACTIVE_ANNOUNCE_ENABLED`, `HOME_ASSISTANT_ALEXA_NOTIFY_SERVICE`,
  `HOME_ASSISTANT_ALEXA_DND_ENTITY` to the generated `.env` template.
- **Last updated:** 2026-08-27

## docs/OPENCLAW.md
- **Why:** Live model-provider config (NVIDIA primary/backup + fallback chain, security runtime
  pins, reasoning-truncation fix, MCP session idle TTL) exists only in
  `~/.openclaw/openclaw.json`, is not in git, and is not reproduced by
  `scripts/configure-openclaw.sh` -- would be silently lost if that file is ever reset.
- **What changed:** Added a "Model providers" section recording what's configured, why (cost --
  NVIDIA hosted models are currently free vs. paid OpenAI nano-tier), what was evaluated and
  rejected (local Ollama: too slow on this laptop's CPU; Groq: free-tier rate-limit backoff made
  real latency 25-38s), and exact reproducible `openclaw config set` commands for everything.
- **Last updated:** 2026-08-27
