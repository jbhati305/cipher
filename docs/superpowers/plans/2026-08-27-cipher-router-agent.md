# Cipher Router Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cipher's default responder a cheap/fast model that handles directly-actionable
requests itself and delegates complex/reasoning-heavy requests to a standing Codex or Claude
specialist session via `sessions_send`, with Claude as backup if the Codex specialist is
unreachable.

**Architecture:** Two standing OpenClaw sessions (Codex-backed, Claude-backed) are created once
with fixed session keys and the `cipher` agent's existing tool restrictions. The `cipher` agent's
primary model switches to a cheap model; its workspace prompt instructs it to use its own tools for
simple requests and `sessions_send(target=<fixed key>, message, timeoutSeconds)` to delegate,
blocking on the reply within the same turn.

**Tech Stack:** OpenClaw 2026.7.1-2 CLI/config (`openclaw config set`, `openclaw agents`,
`openclaw models`), the `cipher` management CLI and its `scripts/*.sh`, Python 3.11 (`cipher_mcp`,
`alexa_bridge` — unmodified by this plan, verified not to regress).

**Spec:** `docs/superpowers/specs/2026-08-27-cipher-router-agent-design.md`

## Global Constraints

- Never weaken `tools.deny` (`group:runtime`, `group:fs`, `group:nodes`) or
  `tools.elevated.enabled: false` for the `cipher` agent or either standing specialist session.
- Never bind the OpenClaw Gateway, MCP server, or any new session to anything but loopback.
- `./cipher doctor`, `uv run pytest`, and `uv run ruff check .` must all still pass clean after
  every task that touches config or code.
- Do not commit or push unless explicitly asked (per the user's original hard constraint on this
  server) — this plan's git steps are the exception the user already granted by asking for prior
  work to be pushed; confirm before pushing new commits from this plan specifically if that
  standing instruction has not been reconfirmed for this feature.
- No real secret value in a commit, log line, or terminal output shown back to the user.

---

### Task 1: Confirm the live Gateway mechanics for standing sessions and `sessions_send`

This is a verification task — the spec explicitly flags these as unconfirmed against the live
Gateway. Its deliverable is a recorded, working command sequence, not new permanent config.

**Files:**
- Create: `docs/superpowers/plans/notes/2026-08-27-sessions-send-findings.md` (scratch findings,
  committed so later tasks and future readers don't have to re-derive this)

**Interfaces:**
- Produces: the exact confirmed `openclaw` CLI/tool-call sequence for (a) creating a session with a
  fixed, rediscoverable key pinned to a specific model, (b) sending it a message with a wait
  timeout and getting the reply inline. Later tasks use whatever is recorded here verbatim.

- [ ] **Step 1: List current sessions for the cipher agent to see key/label conventions**

Run:
```bash
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
openclaw sessions list --agent cipher --json 2>&1
```
Record the output shape (field names, what a `main` session's key looks like) in the findings file.

- [ ] **Step 2: Check `sessions_spawn`/`sessions_send`/`session_status` tool schemas directly**

Run:
```bash
openclaw config schema 2>/dev/null > /tmp/openclaw-schema.json
python3 -c "
import json
d = json.load(open('/tmp/openclaw-schema.json'))
# Tool schemas are not part of openclaw.json config schema; this call is expected to show
# nothing useful for tool parameter shapes -- record that finding and move to Step 3 instead.
print('agents' in d.get('properties', {}))
"
```
If this doesn't surface tool parameter schemas (expected), record that and proceed to Step 3 to
get the answer from a live probe instead.

- [ ] **Step 3: Attempt to create a standing session with a fixed key via the CLI**

Check whether the CLI exposes session creation directly (not just the in-agent tool):
```bash
openclaw sessions --help 2>&1
openclaw session --help 2>&1
```
Record whichever subcommand exists and its flags for: creating/ensuring a session by a given key,
and setting its model. If no CLI-level session-creation command exists, record that the standing
sessions must be created by having the `cipher` agent itself call `sessions_spawn`/`session_status`
once during a one-time interactive setup turn (e.g. via `openclaw tui --message "..."`), and note
that as the actual mechanism for Task 3.

- [ ] **Step 4: Confirm `sessions_send` timeout/target parameter names**

Run:
```bash
openclaw --help 2>&1 | grep -i "sessions_send\|message send"
openclaw message send --help 2>&1
```
Cross-reference against `docs/concepts/session-tool.md`'s prose ("Fire-and-forget: set
`timeoutSeconds: 0`... Wait for reply: set a timeout") — these are in-agent tool call parameters
(used by the model, not the `openclaw` CLI directly), so the CLI won't expose them. Record in the
findings file: confirmed parameter names are `target` and `timeoutSeconds` per the docs; there is
no independent CLI-level way to verify this without either (a) a live agent turn that actually
calls the tool, or (b) reading the tool's TypeScript/JSON schema in
`~/.hermes/node/lib/node_modules/openclaw/dist/*.js` (search for `sessions_send` tool definition).
Do the file search now:
```bash
grep -rl "sessions_send" /home/jitesh/.hermes/node/lib/node_modules/openclaw/dist/*.js 2>/dev/null | head -3
```
If found, grep the matching file(s) for the parameter list near that string and record the exact
schema (parameter names, types, required/optional) in the findings file.

- [ ] **Step 5: Commit the findings**

```bash
cd /home/jitesh/Projects/cipher
git add docs/superpowers/plans/notes/2026-08-27-sessions-send-findings.md
git commit -m "docs: record sessions_send/standing-session findings for router agent plan"
```

---

### Task 2: Resolve the `openai/*` codex-runtime collision and add the cheap model

**Files:**
- Modify: `openclaw.json` (via `openclaw config set` commands, not hand-edited)
- Modify: `.env` is NOT touched directly — go through `~/.auth_keys.sh` /
  `~/.env_vars.sh` + `./cipher sync-env` per the central-secrets convention already in place
  (`docs/SECRETS.md`)

**Interfaces:**
- Consumes: Task 1's findings only if they affect model config (unlikely — this task is
  independent of the session-addressing question).
- Produces: a confirmed, non-colliding model id string for the cheap primary model (e.g.
  `openai/gpt-5-mini` with no `codex` runtime override) that Task 5's workspace prompt and Task 6's
  manual tests reference by this exact id.

- [ ] **Step 1: Check current model config for the collision**

```bash
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
openclaw config get 'agents.list[1].models' 2>&1
```
Confirm it still shows only `openai/*` -> `codex` runtime (as set earlier in this server's setup).

- [ ] **Step 2: Add a narrower entry for the specific cheap model that overrides the wildcard**

Per `docs/openclaw-agent-runtime.md`'s stated rule ("model entry wins over provider entry"), add an
entry for the exact cheap model id that does NOT set `agentRuntime`, so it falls through to `auto`
(plain API-key path) instead of inheriting the `openai/*` wildcard's `codex` mapping:
```bash
CHEAP_MODEL="openai/gpt-5-mini"  # confirm this id is valid: openclaw models list --provider openai
openclaw models list --provider openai 2>&1 | grep -i mini
openclaw config set "agents.list[1].models[\"$CHEAP_MODEL\"]" '{}' --strict-json --merge
```

- [ ] **Step 3: Verify the override took effect**

```bash
openclaw config get 'agents.list[1].models' 2>&1
```
Expected: both the `openai/*` -> `codex` entry AND the new `openai/gpt-5-mini` entry (empty object,
i.e. no runtime override) are present.

- [ ] **Step 4: Add the OpenAI API key to central secrets and sync**

```bash
# Do NOT print the key value. Prompt the user for it interactively if not already provided,
# write directly into ~/.auth_keys.sh under a new "# --- cipher (router agent) ---" section:
export OPENAI_API_KEY="<value>"
```
Append to `/home/jitesh/.auth_keys.sh` (under the existing `# --- cipher` section), matching the
existing file's style (`export KEY="value"`).

- [ ] **Step 5: Register the key with OpenClaw**

```bash
openclaw models auth --agent cipher paste-api-key --provider openai
```
This prompts interactively for the key — run it in a real terminal (same TTY constraint as the
earlier Codex/Claude auth work in this project), not via a non-interactive Bash tool call.

- [ ] **Step 6: Set the cheap model as the agent's primary**

```bash
openclaw config set 'agents.list[1].model' '"openai/gpt-5-mini"' --strict-json
```

- [ ] **Step 7: Verify with a real query**

```bash
openclaw models status --agent cipher --probe --json 2>&1 | python3 -m json.tool
```
Expected: `defaultModel` is now `openai/gpt-5-mini`, and its auth route shows a usable profile
(not `"status": "missing"`).

- [ ] **Step 8: Run `./cipher doctor` to confirm nothing broke**

```bash
cd /home/jitesh/Projects/cipher && ./cipher doctor 2>&1
```
Expected: still all `PASS` except the pre-existing optional `HOME_ASSISTANT` line (if not yet
configured) — the "Primary runtime" check may need updating in a later task if it hardcodes
`codex` as the only expected runtime (see Task 7).

- [ ] **Step 9: Commit config-affecting script/doc changes if any were made**

(This task is mostly live `openclaw config set` calls, which persist in `~/.openclaw/openclaw.json`
directly — not repo files. If `scripts/configure-openclaw.sh` needs a new idempotent block for the
cheap-model override so a fresh install reproduces this, add it now and commit.)

```bash
cd /home/jitesh/Projects/cipher
git add scripts/configure-openclaw.sh  # if modified
git commit -m "feat: configure cheap primary model for cipher agent, avoiding codex-runtime collision"
```

---

### Task 3: Create the two standing specialist sessions

**Files:**
- Modify: `scripts/configure-openclaw.sh` (add idempotent session-creation block, using whatever
  mechanism Task 1 confirmed)
- Modify: `agents/cipher/AGENTS.md` or a new `agents/cipher/ROUTER.md` if the specialist session
  keys need to be documented for the primary model's own reference (exact file depends on how the
  workspace prompt is structured — check `agents/cipher/` contents first)

**Interfaces:**
- Consumes: Task 1's confirmed session-creation mechanism.
- Produces: two session keys (naming convention: `cipher:specialist:codex` and
  `cipher:specialist:claude`, or whatever Task 1 found actually works) that Task 4/5 reference
  verbatim.

- [ ] **Step 1: Check current agent workspace files**

```bash
ls -la /home/jitesh/Projects/cipher/agents/cipher/
```

- [ ] **Step 2: Create the Codex specialist session using Task 1's confirmed mechanism**

Exact commands depend on Task 1's findings. If a CLI session-creation command exists, use it
directly here (concrete example, adjust to Task 1's actual findings):
```bash
openclaw sessions create --agent cipher --key "cipher:specialist:codex" --model "openai/gpt-5.5" 2>&1
```
If no CLI command exists and it must be done via a live agent turn calling `sessions_spawn` once,
use:
```bash
openclaw tui --local --message "Use sessions_spawn to create a session with model openai/gpt-5.5 and report back the childSessionKey it returns. Do nothing else." 2>&1
```
and record the returned key.

- [ ] **Step 3: Create the Claude specialist session the same way, model `anthropic/*` on `claude-cli` runtime**

Mirror Step 2 with the Claude-backed model id (confirm exact id via
`openclaw models list --provider anthropic`).

- [ ] **Step 4: Lock down both sessions' tool policy to match `cipher`'s existing restrictions**

```bash
for KEY in "cipher:specialist:codex" "cipher:specialist:claude"; do
  echo "Verify tools.allow/deny for session $KEY matches the cipher agent's:"
  echo '["cipher-tools__*","group:web","group:memory","sessions_send","session_status"]'
  echo '["group:runtime","group:fs","group:nodes"]'
done
```
(Exact command to set per-session, not per-agent, tool policy depends on whether OpenClaw supports
session-scoped tool overrides distinct from agent-scoped ones — check
`docs/concepts/multi-agent.md`'s "Per-agent sandbox and tool configuration" section again; if
session-level overrides aren't supported, both specialist sessions inherit the `cipher` agent's
tool policy automatically since they belong to the same agent, which already satisfies this
requirement with no extra config.)

- [ ] **Step 5: Verify both sessions are listed and reachable**

```bash
openclaw sessions list --agent cipher --json 2>&1 | python3 -m json.tool
```
Expected: both `cipher:specialist:codex` and `cipher:specialist:claude` (or Task 1's actual key
format) appear.

- [ ] **Step 6: Add idempotent creation to `scripts/configure-openclaw.sh`**

Add a block (matching the script's existing style — check-before-create, like the plugin-install
idempotency added earlier in this project) that ensures both standing sessions exist on every
`./cipher configure` run without erroring if they already do.

- [ ] **Step 7: Run `./cipher configure` to confirm idempotency**

```bash
cd /home/jitesh/Projects/cipher
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
./cipher configure 2>&1
```
Expected: exits 0, no duplicate-session errors on a second run.

- [ ] **Step 8: Commit**

```bash
git add scripts/configure-openclaw.sh
git commit -m "feat: create standing Codex/Claude specialist sessions for router delegation"
```

---

### Task 4: Update the `cipher` agent's tool allowlist

**Files:**
- Modify: `scripts/configure-openclaw.sh:84-88` (the existing `tools.allow`/`tools.deny` block)
- Modify: `scripts/doctor.py` if it references the tool list anywhere (check first)

**Interfaces:**
- Consumes: nothing new from earlier tasks.
- Produces: `cipher` agent's `tools.allow` includes `sessions_send` (replacing `sessions_spawn`,
  which this design no longer uses).

- [ ] **Step 1: Read the current allowlist block**

```bash
grep -n -A5 "tools.allow" /home/jitesh/Projects/cipher/scripts/configure-openclaw.sh
```

- [ ] **Step 2: Edit the allowlist**

Change:
```bash
openclaw config set "${AGENT_PATH}.tools.allow" \
  '["cipher-tools__*","group:web","group:memory","sessions_spawn","session_status"]'
```
to:
```bash
openclaw config set "${AGENT_PATH}.tools.allow" \
  '["cipher-tools__*","group:web","group:memory","sessions_send","session_status"]'
```

- [ ] **Step 3: Re-run configure and verify**

```bash
cd /home/jitesh/Projects/cipher
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
./cipher configure 2>&1
openclaw config get 'agents.list[1].tools.allow' 2>&1
```
Expected: `sessions_send` present, `sessions_spawn` absent.

- [ ] **Step 4: Run `uv run pytest` and `uv run ruff check .` to confirm nothing regressed**

```bash
uv run pytest 2>&1 | tail -5
uv run ruff check . 2>&1
```
Expected: 51 passed, all checks passed (this task doesn't touch Python source, so this is a
guard-rail check, not expected to find anything).

- [ ] **Step 5: Commit**

```bash
git add scripts/configure-openclaw.sh
git commit -m "feat: swap sessions_spawn for sessions_send in cipher agent tool allowlist"
```

---

### Task 5: Write the routing instructions into the agent workspace prompt

**Files:**
- Modify: `agents/cipher/AGENTS.md` (or create if it doesn't exist as a distinct file — check
  Task 3 Step 1's listing first; OpenClaw workspace prompts commonly live in `AGENTS.md` per the
  `agents/cipher/AGENTS.md` file already seen in this workspace)

**Interfaces:**
- Consumes: Task 3's confirmed session keys, Task 2's confirmed cheap model id (for context/
  self-awareness in the prompt, not strictly required functionally).
- Produces: prompt text later verified against Task 6's five manual test scenarios.

- [ ] **Step 1: Read the current `AGENTS.md`**

```bash
cat /home/jitesh/Projects/cipher/agents/cipher/AGENTS.md
```

- [ ] **Step 2: Add a routing section**

Append a new section (exact heading style matching the file's existing conventions) containing:

```markdown
## Request routing

You are Cipher's fast, low-cost default responder. For every incoming request, decide:

**Handle directly** if it's a simple, tool-shaped request you can fully answer with your own
tools: Home Assistant device control or status (`cipher-tools__*`), docker/systemd status
(`cipher-tools__*`), web search/lookup (`group:web`), or memory recall (`group:memory`). A
multi-part request ("turn on the light, check the weather, and check docker status") is still
"simple" if every part is independently tool-shaped — call each tool in this same turn and combine
the results into one answer.

**Delegate** if the request needs real reasoning, planning, writing code, or anything you're not
confident answering correctly yourself. Use:

sessions_send(target="cipher:specialist:codex", message="<the request, verbatim or lightly
cleaned up>", timeoutSeconds=100)

If that times out or errors, retry once with:

sessions_send(target="cipher:specialist:claude", message="<the same request>", timeoutSeconds=100)

Relay the specialist's reply as your final answer (voice-friendly phrasing if this came from
Alexa — short, no markdown, no code blocks read aloud).

When unsure whether something counts as simple or complex, delegate rather than guessing — an
under-reasoned direct answer is worse than the extra delegation latency.
```

(Adjust the exact session keys/timeout to whatever Task 1 and Task 3 actually confirmed — the text
above is the intended content, not necessarily the final key names.)

- [ ] **Step 3: Commit**

```bash
cd /home/jitesh/Projects/cipher
git add agents/cipher/AGENTS.md
git commit -m "docs: add request-routing instructions to cipher agent workspace prompt"
```

---

### Task 6: Manual verification against the five spec test scenarios

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: a pass/fail record for each of the spec's five testing scenarios, and a decision on
  whether Task 7 (docs) can proceed.

- [ ] **Step 1: Confirm `./cipher doctor` is still all green**

```bash
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
cd /home/jitesh/Projects/cipher
./cipher doctor 2>&1
```

- [ ] **Step 2: Restart services to pick up all config changes**

```bash
./cipher restart 2>&1
curl -s -w '\nHTTP_STATUS:%{http_code}\n' http://127.0.0.1:8787/readyz
```

- [ ] **Step 3: Test scenario (a) — simple directly-actionable request, one-shot invocation**

Via Alexa Simulator or Echo, **without** a prior "Alexa, open Cipher" turn: "Alexa, ask Cipher to
check my server health." This also resolves spec open question #4 — confirm whether one-shot
invocation already works as `docs/ALEXA.md` claims. If it does not launch/answer in one shot,
record that as a separate, narrower bug report (per the spec's Non-goals, fixing it is explicitly
out of scope for this plan) rather than expanding this plan to fix it. Confirm the response is
immediate (no delegation latency) and correct.

- [ ] **Step 4: Test scenario (b) — request needing delegation**

"Alexa, ask Cipher to help me write a bash one-liner to find the five largest files on this
server." Confirm the response reflects real reasoning (not a canned/wrong answer) and check
`journalctl --user -u openclaw-gateway.service` for a `sessions_send` call to the Codex specialist
in the relevant time window.

- [ ] **Step 5: Test scenario (c) — multi-part single-utterance request**

"Alexa, ask Cipher to check my server health and tell me a fun fact." Confirm both parts are
answered in one reply.

- [ ] **Step 6: Test scenario (d) — forced Codex delegation failure, confirm Claude backup fires**

Temporarily break the Codex specialist session's reachability (e.g. rename its session key in
config, or revoke Codex auth for that one session if possible without touching the cheap primary's
own auth) and repeat scenario (b). Confirm the reply still succeeds via the Claude specialist.
Revert the temporary breakage afterward.

- [ ] **Step 7: Test scenario (e) — confirm delegated specialist can't exceed cipher's own tool restrictions**

Via a delegated request, ask Cipher to do something the `cipher` agent's `tools.deny` blocks (e.g.
"read a file from disk" — `group:fs` is denied). Confirm the specialist session also refuses/lacks
that tool, not just the primary.

- [ ] **Step 8: Record results**

If any scenario fails, stop here and return to the relevant earlier task rather than proceeding to
Task 7 — do not paper over a failed verification with documentation.

---

### Task 7: Documentation and doctor-check updates

**Files:**
- Modify: `docs/ARCHITECTURE.md` (add the router-agent pattern to the existing decision record)
- Modify: `scripts/doctor.py` (if the "Primary runtime" check at the section checking
  `CIPHER_PRIMARY_RUNTIME` needs to account for the cheap model no longer using the `codex`
  runtime — check whether this check still makes sense post-change or needs updating to check the
  delegation path instead)
- Modify: `README.md` (if the architecture diagram needs the router layer added)

**Interfaces:**
- Consumes: final confirmed config from all prior tasks.
- Produces: docs that match what's actually running (this project's own established pattern from
  earlier work this session — keep docs and reality in sync).

- [ ] **Step 1: Read `scripts/doctor.py`'s "Primary runtime" check**

```bash
grep -n -B2 -A10 "Primary runtime" /home/jitesh/Projects/cipher/scripts/doctor.py
```

- [ ] **Step 2: Decide whether it needs updating**

If it still checks that `agents.list[<n>].models["openai/*"].agentRuntime.id == CIPHER_PRIMARY_RUNTIME`
and that mapping still exists (Task 2 added a narrower override, didn't remove the wildcard), this
check should still pass as-is — the codex mapping is still true for `openai/*` broadly, it's just
no longer what the *primary* model resolves to. Decide whether the check's meaning ("primary
runtime is explicit and agent-scoped") is now misleading and needs a comment or rename, or whether
it's still accurate enough to leave alone. Make the call and document the reasoning in the commit
message.

- [ ] **Step 3: Update `docs/ARCHITECTURE.md`**

Add a paragraph to the "Decision record" section describing the router pattern: cheap primary
model, delegation via standing specialist sessions, why (cost, and a path to a local model later).

- [ ] **Step 4: Run full verification**

```bash
cd /home/jitesh/Projects/cipher
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
uv run pytest 2>&1 | tail -5
uv run ruff check . 2>&1
./cipher doctor 2>&1
```

- [ ] **Step 5: Commit and push**

```bash
git add docs/ARCHITECTURE.md scripts/doctor.py README.md
git commit -m "docs: document the router-agent pattern in ARCHITECTURE.md"
git push origin main 2>&1
```
