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
