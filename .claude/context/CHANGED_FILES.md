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
