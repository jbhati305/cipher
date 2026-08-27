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

## Model providers (live config, not managed by `scripts/configure-openclaw.sh`)

Set 2026-08-27 via `openclaw config set` directly against the Gateway (`~/.openclaw/openclaw.json`).
**This state is NOT in git and NOT reproduced by any script** -- if OpenClaw's config is ever reset
or this machine's `~/.openclaw` is lost, it must be manually reapplied using the commands below.

**Why:** the OpenAI nano-tier fast-responder cost money per call. NVIDIA's hosted models
(`integrate.api.nvidia.com`, OpenAI-compatible) are currently free. Two other free-tier candidates
were evaluated and rejected: a local Ollama model (CPU-only inference on this laptop's 7GB-RAM
Ryzen 5500U measured ~8 tok/s -- 25s+ for a normal answer, and small models produced markdown
despite instructions not to); Groq (raw model latency was excellent, sub-second, but its free-tier
429 rate limit combined with OpenClaw's retry backoff produced 25-38s real request latency after
only a handful of calls).

**Primary model chain** (`agents.list[1].model` for the `cipher` agent):

```bash
openclaw config set 'agents.list[1].model' \
  '{"primary":"nvidia/nvidia/nemotron-3-super-120b-a12b","fallbacks":["nvidia-2/nvidia/nemotron-3-super-120b-a12b","openai/gpt-5.4-nano"]}' \
  --strict-json
```

Two independent NVIDIA accounts (`NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY1` in
`~/.auth_keys.sh`) back `nvidia` and a custom `nvidia-2` provider, so a rate limit on one account
fails over to the other before finally falling back to the original paid OpenAI tier:

```bash
grep '^export NVIDIA_NIM_API_KEY=' ~/.auth_keys.sh | sed 's/^export NVIDIA_NIM_API_KEY="//; s/"$//' | { read -r key; openclaw config set env.NVIDIA_API_KEY "$key"; }
grep '^export NVIDIA_NIM_API_KEY1=' ~/.auth_keys.sh | sed 's/^export NVIDIA_NIM_API_KEY1="//; s/"$//' | { read -r key; openclaw config set env.NVIDIA_API_KEY_2 "$key"; }
openclaw config set 'models.providers.nvidia-2' \
  '{"baseUrl":"https://integrate.api.nvidia.com/v1","api":"openai-completions","apiKey":"NVIDIA_API_KEY_2","models":[{"id":"nvidia/nemotron-3-super-120b-a12b","name":"nvidia/nemotron-3-super-120b-a12b","input":["text"],"contextWindow":1048576,"maxTokens":8192}]}' \
  --strict-json
```

**Security: runtime pin.** `openai/*` defaults to the Codex app-server harness (which exposes
native `bash`-style tools that bypass `tools.deny` -- see `docs/SECURITY.md`); `openai/gpt-5.4-nano`
already had an explicit override back onto the safe embedded runtime. The same override is required
for every other provider added here, since OpenClaw's `auto` resolution is not something to trust
implicitly for a new provider:

```bash
openclaw config set 'agents.list[1].models["nvidia/*"].agentRuntime.id' "openclaw"
openclaw config set 'agents.list[1].models["nvidia-2/*"].agentRuntime.id' "openclaw"
```

Verify live with `openclaw sessions list --all-agents --json` -- each session's `agentRuntime` must
read `{"id": "openclaw", "source": "model"}`, not `"source": "default"`.

**Reasoning-token truncation fix.** Nemotron 3 Super is a reasoning model; without disabling hidden
thinking it intermittently burned its `max_output_tokens` budget on invisible chain-of-thought and
returned `stopReason=length` (an empty/failed turn) instead of an answer. Fixed the same way
NVIDIA's own bundled catalog entry disables it for the Ultra model:

```bash
openclaw config set 'agents.list[1].models["nvidia/nvidia/nemotron-3-super-120b-a12b"].params' \
  '{"chat_template_kwargs":{"enable_thinking":false,"force_nonempty_content":true}}' --strict-json
```

**MCP session idle TTL.** A brand-new OpenClaw session pays a real, one-time ~5s tax reconnecting to
the `cipher-tools` MCP server (proven via direct instrumentation: the tool call itself and the raw
MCP handshake are both under 1s combined -- the cost is specifically in OpenClaw's session-scoped
MCP runtime setup). That connection is cached and reused for follow-up requests in the same session,
but was reaped after only 10 minutes of idle time by default. Raised to 1 hour so realistic gaps
between Alexa requests still hit the warm path:

```bash
openclaw config set 'mcp.sessionIdleTtlMs' 3600000 --strict-json
```

**Known residual behavior:** even warm, a tool-calling turn against NVIDIA's free tier typically
takes several seconds and occasionally spikes higher (observed up to ~11s) -- this is NVIDIA's own
response-time variance, not something further config here can fix. Alexa requests that miss
`ALEXA_SYNC_BUDGET_SECONDS` fall into the existing pending-task pattern (`docs/ALEXA.md`) and, since
the proactive-announcement feature, are usually spoken on the Echo automatically once they finish.

**Inert leftovers from evaluating Groq** (harmless, unused, left in place rather than torn down):
`@openclaw/groq-provider` plugin installed, `env.GROQ_API_KEY` set, and a
`agents.list[1].models["groq/*"].agentRuntime.id = "openclaw"` pin. None of these do anything unless
a `groq/*` model is explicitly selected again. Remove with `openclaw plugins remove groq` and the
corresponding `config unset` calls if you want them gone.
