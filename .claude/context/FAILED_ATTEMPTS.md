# Failed Attempts

<!-- Format per entry:
## Attempt: short description
- **What:** what was tried
- **Result:** what happened
- **Why it failed:** root cause
- **Do not retry unless:** condition that would change the outcome
-->

## Attempt: Pin an older OpenClaw npm version to get `agents.entries` schema back
- **What:** Downloaded/installed several older OpenClaw versions (back to the very first
  published release, 2026.1.29) into isolated npm prefixes and dumped `config schema` /
  tested `config set agents.entries.<id>.tools.allow` in each, hoping an older version would
  accept the `agents.entries` path this repo's scripts assumed.
- **Result:** Every version tested, from the earliest release through current, rejected
  `agents.entries` and used `agents.list[]` (array, indexed) instead.
- **Why it failed:** `agents.entries` never existed in any published OpenClaw version — this
  was a mistake in the original script, not version drift. Fixed by resolving the agent's array
  index instead (see CHANGED_FILES.md).
- **Do not retry unless:** OpenClaw publishes a version that reintroduces an id-keyed agents map
  (check `openclaw config schema` before assuming).

## Attempt: `openclaw models auth setup-token --provider openai` / `--provider codex`
- **What:** Tried to reuse the existing Codex CLI login via OpenClaw's `setup-token` subcommand
  (designed to sync a token from an already-authenticated provider CLI), first with
  `--provider openai`, then `--provider codex`.
- **Result:** Both failed identically: `Error: No provider token-auth plugins found. Install one
  via 'openclaw plugins install'.`
- **Why it failed:** The codex plugin registers a `text-inference: codex` capability, not a
  token-auth-capable provider matching either id under OpenClaw's `setup-token` mechanism.
  `setup-token` simply isn't the right path for this provider/plugin combination.
- **Do not retry unless:** A future `@openclaw/codex` plugin version explicitly documents
  `setup-token` support (check `openclaw plugins inspect codex` for auth capabilities first).
  In practice, auto-discovery (see DECISIONS.md) makes this step unnecessary anyway.

## Attempt: Diagnose "problem communicating with required skill" as a TLS/cert-trust issue
- **What:** Extensive investigation assuming Amazon's Alexa backend couldn't trust the
  certificate Tailscale Funnel serves — checked chain completeness via openssl, researched
  Let's Encrypt ISRG Root X2 (ECDSA-only root) vs ISRG Root X1 (RSA) compatibility gaps,
  researched *.ts.net domain reputation/blocklisting, fetched Amazon's own SSL requirements
  docs.
- **Result:** All research was inconclusive/eventually irrelevant. Real root cause (found later)
  was a bug in our own signature verification code, not TLS/cert trust at all — confirmed once
  server logs showed the cert-chain fetch from Amazon succeeding and *our own* signature
  verification rejecting the request afterward.
- **Why it failed:** Jumped to an external/infrastructure hypothesis before exhausting our own
  logs. The generic "alexa signature rejected" log line (no exception detail) hid the real
  reason; once exception detail was added to the log, the actual cause (self-signed-root check
  bug) was found in one retry.
- **Do not retry unless:** N/A — lesson for future debugging: check own application logs with
  full exception detail before researching external infrastructure causes, especially once
  evidence shows the remote party's request actually reached us (e.g. we made an outbound
  request as part of handling it, as `alexa_signature.py` does when fetching Amazon's cert).

## Attempt: Local Ollama model as cipher's fast-responder tier
- **What:** Pulled `qwen2.5:3b` (confirmed `tools` capability), wired it into cipher's agent
  config, and benchmarked real tool-calling latency both directly against Ollama and through the
  full OpenClaw/cipher pipeline.
- **Result:** Tool selection was fast (2-5s), but generating the actual spoken final answer took
  22-25s for a normal health-check response, and the model produced unrequested markdown despite
  explicit instructions not to.
- **Why it failed:** This laptop has only 7.1GB RAM (4.3GB available, shared with Home
  Assistant/Jellyfin/OpenClaw already running) and no usable GPU (integrated AMD Radeon only) --
  measured generation throughput was ~8 tokens/sec on the Ryzen 5500U CPU. That's a hardware
  ceiling, not a model-choice problem; smaller quantized models would be somewhat faster but with
  worse instruction-following, not fast enough to matter.
- **Do not retry unless:** This machine gets a usable GPU, or the target moves to a
  non-latency-critical channel (not Alexa's ~10s sync budget).

## Attempt: Groq as cipher's fast-responder tier
- **What:** Installed the Groq provider plugin, authenticated, and benchmarked tool-calling
  latency both directly against Groq's API and through the full OpenClaw/cipher pipeline, across
  three different models (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`).
- **Result:** Raw isolated API calls were excellent (sub-second, every time). Through the real
  pipeline, requests took 10-38s and were highly inconsistent.
- **Why it failed:** Gateway logs showed the real cause: Groq's free tier returned `429` (rate
  limited) after only ~3 real requests, and OpenClaw's retry backoff on a 429 waited 25-34
  seconds before retrying. The model itself was never slow -- the wait was. A free tier that
  rate-limits this fast, combined with a multi-second retry backoff, doesn't fit a real-time
  voice pipeline regardless of which Groq model is selected.
- **Do not retry unless:** Groq's free-tier rate limits become meaningfully more generous, or
  usage volume through this bridge is verified to stay well under whatever the current per-minute
  cap is (not established -- wasn't published in OpenClaw's docs).
