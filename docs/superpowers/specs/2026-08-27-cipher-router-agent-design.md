# Cipher router agent

## Problem

Today, every Alexa request to Cipher runs on the `codex` runtime — a full-power, subscription-backed
model — for everything, including trivial device-control asks like "turn on the light." There's no
tier between "full reasoning model" and "the deliberately dumb echo fallback used when
`OPENCLAW_GATEWAY_TOKEN` is unset." The user wants:

1. A cheap/fast model as Cipher's default responder, backed by an OpenAI API key today and a local
   tiny model later (a config swap, not a rebuild).
2. That model to handle directly-actionable requests itself (Home Assistant control, docker/systemd
   status, quick facts) and delegate anything needing real reasoning to a specialist sub-agent.
3. Multi-part single-utterance commands ("turn on the light, check the weather, and check the status
   of all my docker and services") to work without a separate "open Cipher" launch turn first.
4. Claude as a backup delegation target if the Codex-backed delegation path fails.

## Goals

- Cheap default model handles simple, tool-shaped requests itself.
- Complex/ambiguous/coding-adjacent requests get delegated to a standing Codex or Claude specialist
  session via `sessions_send` with a wait timeout, with the result relayed back to the user in the
  same turn.
- Swapping the cheap model for a local model later requires only an `agents.list[].model` /
  `CIPHER_PRIMARY_MODEL` change — no prompt or code rewrite.
- No new privilege surface: the router model gets exactly the tools `cipher` already has, plus
  `sessions_send` (`cipher-tools__*`, `group:web`, `group:memory`, `sessions_send`,
  `session_status`) — nothing broader.
- One-shot multi-part Alexa utterances ("Alexa, ask Cipher to turn on the light, check the weather,
  and check docker status") work in a single turn.

**Correction (post-spec-approval):** the original draft of this spec used `sessions_spawn` +
`sessions_yield` for delegation. Both are asynchronous — `sessions_spawn` returns immediately and
delivers results via a later, separate "announce" message; `sessions_yield` ends the current turn
entirely and expects the follow-up as a future turn. That fits persistent chat channels (Discord,
Slack) where a bot can send a delayed follow-up message. It does not fit Alexa's request/response
model: one HTTP request gets one response, with no channel for a delayed push into an
already-answered turn. The corrected mechanism below uses `sessions_send` with a wait timeout,
which genuinely blocks the calling turn for a reply — see Architecture and Configuration changes.

## Non-goals

- Building a custom NLU/intent classifier outside the model itself. The router *is* the model —
  classification is prompt-driven tool selection, not a separate deterministic parser.
- Changing the Alexa interaction model or bridge signature/session logic. `docs/ALEXA.md` already
  documents one-shot invocation (`"Alexa, ask Cipher to <request>"`); if that isn't working as
  expected in practice, that's a separate, narrower bug to isolate first — not something this
  design should silently bundle in.
- Real-time voice interruption/streaming mid-delegation. The existing pending-task UX
  ("I'm still working on that. Ask me for the result in a moment.") already covers slow responses
  and is reused as-is, not redesigned.

## Architecture

```
Alexa utterance
      |
      v
Alexa Bridge (unchanged) --openclaw responses API--> OpenClaw Gateway
                                                            |
                                                            v
                                              cipher agent, primary model =
                                              cheap/fast model (was: codex/gpt-5.5)
                                                            |
                              +-----------------------------+-----------------------------+
                              |                                                           |
                    tool call: cipher-tools__*,                        sessions_send(target, message,
                    group:web, group:memory                                timeoutSeconds=N)
                    (handled directly, same as today)                     (delegate + wait inline)
                              |                                                           |
                              |                                          +----------------+----------------+
                              |                                          v                                 v
                              |                                standing Codex specialist          standing Claude specialist
                              |                                session (fixed session key,         session (fixed session key,
                              |                                openai/* on codex runtime)          anthropic/* on claude-cli)
                              |                                          |                                 |
                              |                                          +----------------+----------------+
                              |                                                           v
                              |                                              reply returned inline from
                              |                                              sessions_send (same turn,
                              |                                              no async follow-up needed)
                              v                                                          |
                        final answer  <--------------------------------------------------+
```

The two specialist sessions are **standing sessions created once** (at setup/configure time), not
spawned fresh per query — `sessions_send` targets an existing session by a fixed key, it doesn't
create one. This also sidesteps the child-session-key-discovery problem a fresh-spawn-per-query
design would have (the router model would otherwise need to remember or look up a new
`childSessionKey` every time).

The Alexa bridge, signature verification, task/pending-result store, and rate limiting are **all
unchanged** — this design is entirely inside OpenClaw's agent config, two standing sessions, and the
`cipher` agent workspace prompt. The bridge already calls the same OpenResponses endpoint; it has no
idea whether the reply came from the primary model directly or via a delegated specialist session.
The bridge's existing pending-task UX (`ALEXA_SYNC_BUDGET_SECONDS`, "I'm still working on that...")
already covers a `sessions_send` wait that runs long, up to the bridge's own
`ALEXA_OPENCLAW_TIMEOUT_SECONDS` (120s) ceiling — no new latency-handling code needed there either.

## Configuration changes

1. **Primary model**: `agents.list[<n>].model` for the `cipher` agent becomes the cheap model
   (e.g. `openai/gpt-5-mini` or similar, via the plain `openai` provider using the API key — not
   the `codex` runtime, since that's reserved for the delegated Codex sub-agent path). Verify at
   implementation time whether this needs an explicit `agentRuntime` override to keep it off the
   Codex harness (the existing `agents.list[<n>].models["openai/*"].agentRuntime.id = "codex"`
   entry currently applies to *all* `openai/*` models — the cheap model needs its own entry, or a
   provider/runtime combination that doesn't collide with that wildcard).
2. **OpenAI API key**: added via `openclaw models auth paste-api-key --provider openai` (or the
   `auth.order.openai` backup-profile pattern from `concepts/model-failover.md` if the cheap model
   should also be able to fail over to the Codex subscription — needs a decision at implementation
   time, see Open Questions).
3. **Two standing specialist sessions**, created once (not per query): one pinned to a Codex-backed
   model (`openai/*` on the `codex` runtime, matching today's default), one pinned to a
   Claude-backed model (`anthropic/*` on the `claude-cli` runtime). Fixed, predictable session keys
   so the router model always targets the same two addresses. Exact creation mechanism (a one-time
   `sessions_spawn` + `session_status(model=...)` pin, vs. a config-level session/label
   pre-declaration) to be confirmed against the live Gateway in the plan's first task — the docs
   describe the primitives but not a turnkey "create a standing labeled session" recipe.
4. **Agent workspace prompt** (`agents/cipher/AGENTS.md` or equivalent): add explicit routing
   instructions — what counts as directly-actionable (maps to existing tool categories) vs. what
   should be delegated, the two specialist session keys to `sessions_send` to, and the timeout to
   pass.
5. **Delegation fallback**: the workspace prompt instructs the primary model to retry via the
   Claude specialist session if `sessions_send` to the Codex specialist times out or errors, before
   giving up.
6. **Tool allowlist**: `sessions_send` replaces `sessions_spawn` in `agents.list[<n>].tools.allow`
   for the `cipher` agent (set via `scripts/configure-openclaw.sh`, same mechanism used for the
   existing allowlist).

## Data flow: multi-part command example

"Alexa, ask Cipher to turn on the light, check the weather, and check the status of all my docker
and services":

1. Bridge receives one `CipherQueryIntent` with the full utterance in the `Query` slot (existing
   `AMAZON.SearchQuery` slot already captures free-form text like this — no interaction model
   change needed).
2. Primary (cheap) model receives the query, recognizes three independently actionable sub-requests.
3. Calls `cipher-tools__home_assistant_*` (or whatever the actual HA tool name is) to toggle the
   light, `group:web` for weather, `cipher-tools__docker_*` / `cipher-tools__systemd_*` for status —
   three tool calls in one turn, same as any agentic tool-calling loop.
4. Composes one combined spoken answer from the three results.
5. If the bridge's `ALEXA_SYNC_BUDGET_SECONDS` (6s) is exceeded before all three tool calls finish,
   the existing pending-task path kicks in unchanged ("I'm still working on that...").

No new decomposition logic — this is exactly how tool-calling agents already work; the "routing" is
just the model choosing between its own tools and `sessions_send` to a specialist session.

For a request needing delegation (e.g. "help me write a script to back up my Docker volumes"): the
router model calls `sessions_send(target=<codex-specialist-key>, message=<the request>,
timeoutSeconds=<budget>)`, blocks on the reply within that turn, then relays it (verbatim or lightly
rephrased for voice) as its final answer. If the specialist send times out or errors, retry once
against the Claude specialist session with the same message before surfacing a failure.

## Error handling

- **`sessions_send` to the Codex specialist times out or errors**: workspace prompt instructs retry
  via `sessions_send` to the Claude specialist session with the same message.
- **Both specialist sends fail**: primary model reports the failure in its own words; bridge's
  existing `except Exception` path ("I couldn't reach Cipher safely...") is the final backstop,
  unchanged.
- **Cheap model itself fails/rate-limited**: this is a separate question from delegation failure —
  see Open Questions on whether the cheap model gets its own `model.fallbacks` chain (e.g. falling
  back to Codex directly as primary, temporarily) or just surfaces the error.
- **Ambiguous requests** (router unsure whether something is simple or complex): default to
  delegating rather than guessing wrong and giving an under-reasoned answer for something that
  needed real thought. Prompt should say this explicitly.

## Security

No new privilege surface beyond adding `sessions_send` to the allowlist in place of `sessions_spawn`
(both are session-orchestration tools already in the same risk class — cross-session messaging vs.
cross-session creation). The two standing specialist sessions are created explicitly with their own
`tools.allow`/`tools.deny`/`tools.elevated.enabled: false`, matching the `cipher` agent's existing
restrictions (`cipher-tools__*`, `group:web`, `group:memory`, `sessions_send`, `session_status`
allowed; `group:runtime`, `group:fs`, `group:nodes` denied; elevated tools disabled) — since we
control their creation directly (standing sessions, not per-query spawns), there's no inheritance
ambiguity to resolve at runtime.

## Testing

- Unit-level: none of the existing Python test suite changes (bridge/signature/MCP logic is
  untouched) — the 51 existing tests should keep passing unmodified.
- Manual/integration: real Alexa Simulator and Echo tests for (a) a simple directly-actionable
  request, (b) a request needing delegation, (c) a multi-part single-utterance request mixing both,
  (d) forcing a Codex delegation failure (e.g. temporarily wrong auth) to confirm Claude backup
  fires, (e) confirming tool restrictions still hold for a delegated sub-agent (it should not be
  able to do anything the primary `cipher` agent couldn't).
- `./cipher doctor` should still show `PASS` across the board after the primary model change.

## Rollout

1. Configure the cheap model as primary, keep the existing `openai/* -> codex` and Claude ACP setup
   as delegation targets (not the default path anymore).
2. Update the workspace prompt with routing instructions.
3. Test the five scenarios above.
4. Later: swap `CIPHER_PRIMARY_MODEL` (or the equivalent `agents.list[].model` entry) to a local
   model — no other change expected, but re-run the same five test scenarios to confirm the new
   model still follows the routing/delegation instructions correctly (a much weaker local model may
   need a simplified or more explicit prompt).

## Open questions (resolve during implementation planning)

1. Does `agents.list[<n>].models["openai/*"].agentRuntime.id = "codex"` (currently set) collide with
   also wanting a plain, non-codex `openai/*` model as primary? May need the cheap model on a
   different provider entry, an explicit per-model override that takes precedence over the
   wildcard, or the codex mapping narrowed to a specific model id instead of `openai/*`.
2. Exact recipe for creating a **standing, fixed-key** specialist session pinned to a specific
   model/runtime that outlives a single turn and is reachable by `sessions_send` on every future
   query — confirm against the live Gateway (`sessions_spawn` once + `session_status(model=...)` to
   pin, vs. some other pattern) rather than assuming the docs prose maps directly to a working
   sequence of calls.
3. Should the cheap primary model have its own `model.fallbacks` for when *it* fails (distinct from
   specialist delegation failure), or is delegating to the Codex specialist effectively already a
   fallback path?
4. Confirm whether the "Alexa, ask Cipher to ..." one-shot phrasing already works as documented
   before assuming any bridge/interaction-model change is needed for the "no separate open-Cipher
   turn" requirement.
5. Confirm `sessions_send`'s exact parameter names/types (target addressing, timeout field name,
   response shape) directly from the Gateway/tool schema — the docs describe behavior in prose, not
   a formal parameter schema.
