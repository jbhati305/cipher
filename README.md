# Cipher

Cipher is a self-hosted personal AI assistant built around OpenClaw,
with Alexa, Codex, Claude Code, server-management and Home Assistant integrations.

OpenClaw owns the persistent agent, sessions, routing, memory, WebChat, and web tools. Cipher's
primary model is a cheap, fast model that runs on OpenClaw's own embedded runtime and handles most
turns directly (simple classification, typed tool calls); it delegates to a standing Codex
specialist session only when a request needs deeper reasoning. Claude Code remains a separate,
manual specialist a human invokes directly — it is not part of the automatic router. See
[Architecture](docs/ARCHITECTURE.md) for why, including a known, accepted security gap on the
delegated Codex path. Infrastructure access crosses a small MCP server that exposes typed,
allowlisted operations—never an unrestricted root shell.

```text
Alexa Custom Skill -> Tailscale Funnel -> Alexa Bridge (loopback)
                                                    |
WebChat ----------------------------------------- OpenClaw
                                                    |
                                 Cipher agent (cheap primary model,
                                   embedded OpenClaw runtime)
                                    |                        |
                    delegates via sessions_send      Cipher MCP typed tools
                       to Codex specialist session   server / Docker / systemd / HA
```

## Current features

- Dedicated `cipher` OpenClaw agent and workspace.
- Cheap primary model pinned to OpenClaw's embedded runtime, with a standing Codex specialist
  session (native Codex plugin, explicit `guardian` mode) reached via delegation for harder requests.
- Optional Claude Code specialist through OpenClaw's official `@openclaw/acpx` backend, invoked
  manually — not part of the automatic delegation path.
- CPU, memory, load, uptime, disk, temperature, Docker, systemd, and Home Assistant tools.
- Fixed argv execution, strict schemas, allowlists, bounded logs, and one-time confirmations.
- Alexa `en-IN` and `en-US` models built around one `AMAZON.SearchQuery` intent.
- Alexa-signature-verified bridge with replay defense, rate/size limits, private logging, stable
  conversations, and long-task result retrieval.
- Tailscale Funnel, systemd, CI, health checks, and management CLI assets.

## Quick start

```bash
git clone <repository-url> cipher
cd cipher

./cipher setup
./cipher auth codex
./cipher auth claude       # optional
./cipher configure

# Edit .env and config/*.yaml for this host.
./cipher up
./cipher doctor
```

Package or deploy the Alexa edge after configuring AWS and the skill:

```bash
./cipher alexa package
./cipher alexa deploy
```

## Security model

The model chooses a capability, not a raw privileged command. Docker and systemd identifiers must
match configured values before a fixed argument vector is executed. Home Assistant reads and
controls have separate policies; locks, alarms, and covers are denied by default. OpenClaw, its
OpenResponses API, Codex, Claude, Home Assistant, and the MCP server remain private. Only
`/alexa/*` reaches the loopback Alexa Bridge through the public tunnel.

Do not put credentials in Git. `./cipher setup` creates `.env` with random local secrets and mode
`0600`; add the Home Assistant token, public URL, and Alexa skill ID locally.

## Management commands

Run `./cipher help` for the complete command list. Common operations are:

```text
setup, configure, auth codex, auth claude
up, down, restart, status, doctor, logs
alexa package, alexa deploy
tunnel setup, tunnel status, update
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Installation](docs/INSTALL.md)
- [Alexa](docs/ALEXA.md)
- [OpenClaw](docs/OPENCLAW.md), [Codex](docs/CODEX.md), [Claude Code](docs/CLAUDE.md)
- [Home Assistant](docs/HOME_ASSISTANT.md)
- [Security](docs/SECURITY.md), [Secrets](docs/SECRETS.md)
- [Operations](docs/OPERATIONS.md), [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Roadmap](docs/ROADMAP.md)
