# Architecture

## Decision record

OpenClaw runs natively under the host user's systemd service. This matches its supported daemon,
keeps subscription/browser authentication straightforward, and lets its managed Codex app-server
and ACP adapters work without forwarding credentials into a container. Home Assistant stays in its
existing Docker deployment.

Cipher's MCP server and bridge also run natively. Containerizing the stdio MCP server would either
disconnect it from the host OpenClaw process or require reintroducing privileged host Docker and
systemd access into a container. That is deliberately not offered as a misleading half-working
deployment mode; a future narrow helper can be designed if host permissions prove impractical.

The OpenClaw Gateway is the source of truth for sessions and memory. The Alexa bridge calls its
private OpenResponses endpoint using `x-openclaw-agent-id: cipher` and a privacy-preserving stable
`user`/session key. Cipher does not create a second conversation database. Its SQLite files are
limited to HMAC replay keys, long-running Alexa task results, and pending mutation confirmations.

OpenClaw's current Codex integration is selected instead of repeated `codex exec` subprocesses.
The official plugin owns a managed app-server and discovers available account models. An explicit
model is optional. Claude Code uses the official `@openclaw/acpx` adapter and is not in the path for
ordinary questions.

Cipher's primary model is `openai/gpt-5.4-nano` — a cheap, fast model whose only job on most turns
is simple classification and function-calling (read a metric, call a typed MCP tool, answer a short
factual question), which does not need a larger model's reasoning depth. It carries an explicit
`agentRuntime.id: "openclaw"` override, so it runs on OpenClaw's own embedded runtime rather than on
Codex's app-server harness. This is deliberate and security-load-bearing, not a cost optimization
alone: verification during this router-agent rollout found that Codex's app-server harness exposes
its own native tools (notably `bash`) that bypass OpenClaw's `tools.deny` entirely — the `group:fs`
and `group:runtime` deny entries only cover OpenClaw's generic tool names, not Codex-native ones —
and this was live-confirmed by reading `/etc/passwd` through it despite `tools.deny`. Only an
*explicit* `agentRuntime.id: "openclaw"` override closes this; an empty `models[<id>]` override does
not, even though it looks equivalent. With the explicit override in place, the primary model has no
bash/exec tool at all and a live re-probe confirmed the `/etc/passwd` read is refused.

When the primary model judges a request too complex for its own capability — deeper reasoning,
multi-step work, or anything outside simple tool-calling — it delegates by calling `sessions_send`
against a standing specialist session, `cipher-specialist-codex`, which stays on the real Codex
runtime for genuine reasoning quality. If delegation fails, the primary model reports the failure
directly in its own words; there is no automatic retry through a Claude specialist, since no working
Claude delegation target exists (see below). This router split — a cheap model that classifies and
calls typed tools directly, escalating to a stronger model only when needed — controls cost on every
ordinary turn and also leaves room to swap the primary model for a local model later without
touching the delegation path, since delegation is keyed off request complexity, not the primary
model's own identity.

**This delegation path is a known, open security gap, not a resolved one.** The
`cipher-specialist-codex` session is intentionally left on the real Codex app-server runtime, for
the reasoning quality that runtime provides — and it therefore has the exact same bash-tool
tools.deny bypass described above, unfixed. Cipher's own `tools.allow` permits calling
`sessions_send` to reach it, so this session is currently reachable from ordinary delegated
requests. The operator was asked directly whether to cut off delegation until this is resolved, and
chose to accept the risk short-term rather than lose delegation. No narrower Codex sandbox that
actually confines reads (rather than just writes) is known to exist yet; a genuine fix — a narrower
sandbox if one appears upstream, a different delegation target, or a permanent, explicitly
re-confirmed acceptance of this risk — is still open. Do not read this document as saying the
delegated path is secured: only the primary model's direct tool-calling path is.

Claude Code delegation was also considered as a second specialist and descoped, for an unrelated
reason: OpenClaw's `sessions_spawn(runtime="acp")` requires the *spawning* agent (`cipher`) to itself
hold `apply_patch`/`edit`/`exec`/`process`/`read`/`write` permissions, which `cipher`'s own
`tools.deny` blocks by design. Routing the spawn through OpenClaw's unrestricted default `main`
agent instead would be a larger exposure, not a smaller one, so that path was rejected too. Claude
Code therefore remains only the pre-existing manual, interactive specialist (`./cipher auth claude`,
invoked directly by a human) — it is not part of the automatic router or its failure path.

## Boundaries

```text
Public                                   Private host

Alexa -> Tailscale Funnel (public HTTPS) -> 127.0.0.1:8787 Alexa Bridge
                                      |
                               127.0.0.1:18789
                                 OpenClaw Gateway
                           /             |             \
                    native Codex     Claude ACP     Web/search
                           \             |             /
                                  Cipher agent
                                       |
                             managed stdio MCP server
                         metrics / docker CLI / systemctl / HA REST
```

Tailscale Funnel exposes only the bridge's port; nothing else on the laptop is reachable through
it, since Funnel forwards exactly one local port and the Gateway/Codex/Claude/MCP/Home Assistant
ports are never passed to `tailscale funnel`.

## Tool execution

All process execution uses an argument array with `shell=False`. Container and service names first
pass a strict identifier grammar and exact allowlist membership test. No tool offers Docker exec,
Docker run, arbitrary systemctl arguments, a raw Docker API, sudo, or shell. The MCP server runs as
the unprivileged OpenClaw service user and uses the host Docker CLI only for its fixed operations;
the model never receives the Docker socket.

Home Assistant uses the official local REST API for synchronous state and service calls. The MVP
does not need WebSocket subscriptions.

## Multi-command requests

Cipher's agent instructions ask the runtime to reason over the whole utterance and call multiple
typed tools. Independent reads may run concurrently. There is deliberately no `split("and")`
parser. Mutations remain subject to policy and exact confirmation even when combined with reads.

## Long Alexa work

The bridge starts an OpenClaw request as a tracked task and waits only for the configured spoken
budget. `asyncio.shield` prevents the budget timeout from cancelling the work. The immediate answer
asks the user to request the last result; the completed or failed result is stored in local SQLite.
There is no unsupported Alexa callback trick in the MVP.
