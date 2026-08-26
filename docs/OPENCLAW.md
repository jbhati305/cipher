# OpenClaw

Cipher uses current native OpenClaw features rather than a compatibility wrapper:

- a dedicated agent created by `openclaw agents add cipher --workspace ...`;
- `mcp.servers` managed stdio registration, verified with `openclaw mcp doctor ... --probe`;
- a loopback Gateway and disabled-by-default OpenResponses endpoint explicitly enabled for the
  private bridge;
- the native Codex plugin for primary turns;
- `@openclaw/acpx` for the optional Claude external harness;
- OpenClaw session/memory and built-in web tools.

The Cipher agent gets an explicit tool allowlist for `cipher-tools__*`, web, memory, and specialist
session spawning. Generic runtime/filesystem/node groups and elevated execution are denied. MCP's
Codex projection is restricted to the `cipher` agent. Keep Cipher in a dedicated OpenClaw instance
if other locally configured agents must not even discover the globally registered MCP definition.
The agent's `openai/*` model catalog also carries an explicit `agentRuntime.id=codex` rule by
default, so primary runtime selection fails closed instead of depending on implicit route matching.

Cipher's MCP tools publish standard read-only/destructive/open-world annotations. OpenClaw can use
those hints for its default Codex MCP approval behavior; the server still enforces allowlists and
requester-bound confirmation tokens independently because annotations are not authorization.

`scripts/configure-openclaw.sh` applies these settings idempotently. The reviewed reference shape is
also recorded in `config/openclaw/openclaw.example.json5`; it is documentation, not a secret-bearing
file copied wholesale over the user's OpenClaw configuration.

The OpenResponses endpoint grants broad operator semantics under shared-token authentication. It
therefore stays on `127.0.0.1`. Configuration copies the Gateway token to a mode-`0600` ignored
file and gives OpenClaw a file SecretRef, so the whole application `.env` is not inherited by the
Gateway or its Codex/ACP children. The Alexa bridge receives the same token only in its private
systemd environment and never includes it in a response.

WebChat/Control UI should be reached with Tailscale, an SSH local-forward, or another private access
path. Do not add it to the public Alexa tunnel.

Web search remains an OpenClaw feature. If `BRAVE_API_KEY` is present when `./cipher configure`
runs, the script copies it to a private ignored file and configures Brave through a file SecretRef.
If no provider is configured, Cipher's instructions require an explicit unavailable answer.

Official references reviewed 2026-08-26:
[Codex harness](https://docs.openclaw.ai/plugins/codex-harness),
[MCP servers](https://docs.openclaw.ai/tools/mcp),
[ACP setup](https://docs.openclaw.ai/tools/acp-agents-setup),
and [OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api).
