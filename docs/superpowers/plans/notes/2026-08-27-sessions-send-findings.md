# Findings: live Gateway mechanics for standing sessions and `sessions_send`

Task 1 of the cipher-router-agent plan. Investigation only, live Gateway, no config mutated.
OpenClaw version at time of investigation: `OpenClaw 2026.7.1-2 (0790d9f)`.
`openclaw` binary resolved from `/home/jitesh/.hermes/node/bin` (must be on `PATH`).

## Step 1: `openclaw sessions list --agent cipher --json`

Command run:
```
export PATH="/home/jitesh/.hermes/node/bin:$PATH"
openclaw sessions list --agent cipher --json
```

Exact output:
```json
{
  "path": "/home/jitesh/.openclaw/agents/cipher/sessions/sessions.json",
  "count": 0,
  "totalCount": 0,
  "limitApplied": 100,
  "hasMore": false,
  "activeMinutes": null,
  "sessions": []
}
```

**Finding:** the `cipher` agent currently has **zero** stored sessions (`sessions.json` is
present but empty). This means there is no existing `main` session to inspect for key-naming
conventions — we cannot observe a real example of a session `key` field from this agent. Any
key-format assumptions in later tasks must be treated as unverified until a session is actually
created and re-listed. The store path itself is confirmed:
`/home/jitesh/.openclaw/agents/cipher/sessions/sessions.json`.

The JSON shape returned by `sessions list --json` is: `path`, `count`, `totalCount`,
`limitApplied`, `hasMore`, `activeMinutes`, `sessions` (array, empty here). Field names for an
individual session object were **not observed** (no sessions existed to show one).

## Step 2: `openclaw config schema` for tool parameter shapes

Commands run:
```
openclaw config schema 2>/dev/null > /tmp/openclaw-schema.json
python3 -c "
import json
d = json.load(open('/tmp/openclaw-schema.json'))
print('agents' in d.get('properties', {}))
"
```

Output: `True` (i.e. `config schema`'s top-level `properties` does contain an `agents` key — this
is the *config* schema, e.g. `agents.defaults`, channel config, etc., not tool call parameter
schemas).

**Confirmed as expected in the brief:** `openclaw config schema` exposes the Gateway's
*configuration* schema (agents.yaml/openclaw.json shape), not the JSON-Schema/parameter shape of
in-agent tools like `sessions_send` or `sessions_spawn`. It is not useful for answering "what
parameters does `sessions_send` accept" — moved on to Step 3/4 to get that from a live probe and
from the installed package's compiled source instead.

## Step 3: CLI-level session creation

Commands run:
```
openclaw sessions --help
openclaw session --help
```

`openclaw sessions --help` output (abridged to the relevant parts):
```
Usage: openclaw sessions [options] [command]

List stored conversation sessions

Options:
  --active <minutes>  Only show sessions updated within the past N minutes
  --agent <id>        Agent id to inspect (default: configured default agent)
  --all-agents        Aggregate sessions across all configured agents (default: false)
  -h, --help          Display help for command
  --json              Output as JSON (default: false)
  --limit <count>     Max sessions to show (default: 100; use "all" for full output)
  --store <path>      Path to session store (default: resolved from config)
  --verbose           Verbose logging (default: false)

Commands:
  cleanup             Run session-store maintenance now
  compact             Compact a stored session transcript via the running gateway
  export-trajectory   Export a redacted trajectory bundle for a stored session
  list                List stored conversation sessions
  tail                Tail human-readable session trajectory progress
```

`openclaw session --help` (singular) errored:
```
[openclaw] Could not start the CLI.
[openclaw] Reason: Unknown command: openclaw session. No built-in command or plugin CLI metadata owns "session".
Did you mean this?
  openclaw sessions
[openclaw] Debug: set OPENCLAW_DEBUG=1 to include the stack trace.
```
(Also printed two unrelated plugin warnings about a `codex` plugin failing to register —
pre-existing/unrelated to this task, noted here for completeness, not investigated further.)

**Confirmed finding:** the `openclaw sessions` CLI subcommand group is **read/maintenance only**
(`list`, `cleanup`, `compact`, `export-trajectory`, `tail`). There is **no CLI-level
session-creation command** — no `openclaw sessions create`, `openclaw sessions spawn`, or
`openclaw sessions send`. Session creation and messaging (`sessions_spawn`, `sessions_send`,
`session_status`) are **in-agent tool calls only**, invoked by a model during an agent turn — they
are not exposed as top-level `openclaw` CLI verbs.

**Conclusion for Task 3:** the standing sessions with fixed keys must be created by having the
`cipher` agent itself call the `sessions_spawn` tool (or have `sessions_send` auto-create a
missing configured-agent main session — see Step 4) during a one-time interactive/setup turn, e.g.
via `openclaw tui --message "..."` or an equivalent ingress that drives a real agent turn. There is
no way to pre-create a session purely from the CLI without going through a live agent turn.

## Step 4: `sessions_send` parameter schema

Commands run:
```
openclaw --help 2>&1 | grep -i "sessions_send\|message send"
openclaw message send --help
```

`--help` grep matched only the unrelated `openclaw message send` CLI subcommand (channel
messaging — Telegram/WhatsApp/Discord/etc.), not the in-agent `sessions_send` tool. Full
`openclaw message send --help` output:
```
Usage: openclaw message send [options]

Send a message

Options:
  --account <id>         Channel account id (accountId)
  --channel <channel>    Channel: telegram|whatsapp|discord|irc|googlechat|slack|signal|imessage|feishu|nostr|msteams|mattermost|nextcloud-talk|matrix|raft|line|zalo|clickclack|zalouser|sms|synology-chat|tlon|qqbot|twitch
  --delivery <json>      Shared delivery preferences as JSON
  --dry-run              Print payload and skip sending (default: false)
  --force-document       Send media as document ...
  -h, --help             Display help for command
  --json                 Output result as JSON (default: false)
  -m, --message <text>   Message body (required unless --media is set)
  --media <path-or-url>  Attach media ...
  --pin                  Request that the delivered message be pinned when supported
  --presentation <json>  Shared presentation payload as JSON
  --reply-to <id>        Reply-to message id
  --silent               Send silently
  -t, --target <dest>    Recipient/channel: E.164 for WhatsApp/Signal, Telegram chat id/@username, Discord/Slack/Mattermost <channelId|user:ID|channel:ID>, or iMessage handle/chat_id
  --thread-id <id>       Thread id (Telegram forum thread)
  --verbose              Verbose logging (default: false)
```

**Important correction to the brief's assumption:** `openclaw message send` is a **channel
messaging CLI command** (sends to Telegram/WhatsApp/Discord/etc. recipients), and is **NOT** the
CLI surface for the in-agent `sessions_send` tool — there is no CLI equivalent of `sessions_send`
at all (consistent with Step 3's finding that all session tools are in-agent-only). Its `--target`
flag is a coincidental naming match with the docs' prose, not the same parameter.

The referenced doc `docs/concepts/session-tool.md` **does not exist in this repo** (searched the
whole worktree, not found) — so the brief's cross-reference target is itself unconfirmed/missing.
This should be flagged to whoever wrote the plan.

### Ground truth: `sessions_send` tool schema, read directly from compiled source

```
grep -rl "sessions_send" /home/jitesh/.hermes/node/lib/node_modules/openclaw/dist/*.js
```
returned 23 matching files. The tool's actual parameter schema (a TypeBox `Type.Object`, not the
"target"/"timeoutSeconds" shape assumed in the brief) was found in
`/home/jitesh/.hermes/node/lib/node_modules/openclaw/dist/openclaw-tools-KulZ1cdH.js`, at the
`sessions_send built-in tool` region:

```js
const SessionsSendToolSchema = Type.Object({
	sessionKey: Type.Optional(Type.String()),
	label: Type.Optional(Type.String({ minLength: 1, maxLength: 512 })),
	agentId: Type.Optional(Type.String({ minLength: 1, maxLength: 64 })),
	message: Type.String(),
	timeoutSeconds: Type.Optional(Type.Integer({ minimum: 0 }))
});
```

Confirmed exact parameter names, types, and required/optional status:
- `sessionKey` (string, optional) — target a session directly by its stored key.
- `label` (string, optional, 1-512 chars) — target a session by label instead of key.
- `agentId` (string, optional, 1-64 chars) — target a *configured agent's* main session by
  agent id. Per the tool's own description string (`describeSessionsSendTool()`):
  > "Send message to visible session by sessionKey/label, or configured agent by agentId;
  > sessionKey wins when redundant label metadata is present."
  > "Thread-scoped chats rejected; target parent channel session."
  > **"Creates missing configured-agent main session; waits for reply when available."**
- `message` (string, **required**) — the message body.
- `timeoutSeconds` (integer, optional, minimum 0) — wait timeout. Confirmed default when omitted:
  **`30`** (from execute handler: `readNonNegativeIntegerParam(params, "timeoutSeconds") ?? 30`).
  `timeoutSeconds: 0` is the fire-and-forget code path (skips waiting for a reply, still starts
  the run and can deliver an async announcement instead).

**There is no `target` parameter on `sessions_send`.** The brief's assumption that the confirmed
parameter names are "`target` and `timeoutSeconds`" is **wrong** — the correct targeting
parameters are `sessionKey`, `label`, and `agentId` (pick one), plus `message` (required) and
optional `timeoutSeconds`. This is a load-bearing correction for later tasks: any code/prompt that
assumes a `target` field on `sessions_send` needs to use `sessionKey`/`label`/`agentId` instead.

**Auto-creation confirmed:** the tool description explicitly states it "creates missing
configured-agent main session" when targeted by `agentId` — i.e. calling `sessions_send` with
`agentId: "<some-configured-agent>"` and no existing main session for that agent will create one
on the fly and then send the message to it. This directly answers part (a) of the deliverable: a
"fixed, rediscoverable key" is most reliably obtained via `sessions_spawn` (see below) using a
stable `taskName`, or implicitly via `sessions_send agentId:<id>` auto-creating that agent's main
session — not through any CLI command.

### Related: `sessions_spawn` schema (for creating a *standing* session with a fixed key/model)

Also found in the same file, useful for Task 3 since `sessions_send` alone only *messages*
existing/main sessions — `sessions_spawn` is what actually creates a new session and lets you pin
identifying/model info:

```js
function createSessionsSpawnToolSchema(params) {
  const schema = {
    task: Type.String(),
    taskName: Type.Optional(Type.String({
      description: "Stable alias for later targeting; lowercase letters/digits/underscores/hyphens, starts letter."
    })),
    label: Type.Optional(Type.String()),
    runtime: /* enum: "subagent" | "acp" */,
    agentId: Type.Optional(Type.String()),
    model: Type.Optional(Type.String()),
    thinking: Type.Optional(Type.String()),
    cwd: Type.Optional(Type.String()),
    thread: Type.Optional(Type.Boolean(/* only if threadAvailable */)),
    mode: /* enum from SUBAGENT_SPAWN_MODES, e.g. "run" | "session" */,
    cleanup: /* enum: "delete" | "keep" */,
    sandbox: /* enum: "inherit" | "require" */,
    context: /* enum SUBAGENT_SPAWN_CONTEXT_MODES, e.g. "isolated" | "fork" */,
    lightContext: Type.Optional(Type.Boolean()),
    attachments: Type.Optional(Type.Array(...)),
    // ...ACP-only fields when acpAvailable: resumeSessionId, streamTo, etc.
  };
}
```

Key fields for "standing session with a fixed, rediscoverable key pinned to a specific model":
- `taskName` — the stable alias to use as the rediscoverable key/handle for later `sessions_send`
  calls (via `label`, most likely — `sessions_spawn`'s `taskName` doc string explicitly says
  "Stable alias for later targeting").
- `model` — pins the spawned session to a specific model.
- `mode: "session"` (only available when `thread`/session mode is supported) vs `mode: "run"`
  (one-shot). A **standing** session needs `mode: "session"`.
- `cleanup: "keep"` — needed so a standing session is not auto-deleted after use (the alternative,
  `"delete"`, is presumably the default cleanup behavior for ephemeral spawns — not independently
  confirmed here, flag for Task 3 to verify against real spawn output).

This was **not exercised live** (no `sessions_spawn` call was made — that would mutate state,
which Step 3/this task's constraints prohibit). The schema above is read directly from the
installed package's compiled JS, not observed via a live tool call. Task 3 should do a real,
minimal `sessions_spawn` call (in an actual agent turn) and re-list sessions to confirm the
resulting `key`/label conventions before relying on this further.

## Step 5: file locations used

- Tool schema source (ground truth for `sessions_send`/`sessions_spawn` parameters):
  `/home/jitesh/.hermes/node/lib/node_modules/openclaw/dist/openclaw-tools-KulZ1cdH.js`
- Session store for `cipher` agent (currently empty):
  `/home/jitesh/.openclaw/agents/cipher/sessions/sessions.json`

## Summary / answers to the three questions posed by the task

**(a) How to create a standing session with a fixed key, pinned to a specific model:**
No CLI-level session-creation command exists (confirmed in Step 3). It must be done via a live
agent turn where the `cipher` agent calls the `sessions_spawn` tool with `taskName: "<fixed-key>"`,
`model: "<model-id>"`, `mode: "session"`, and `cleanup: "keep"`. This has not been exercised live
in this task (would mutate state); Task 3 must actually perform this call and confirm the
resulting session's `key`/label match `taskName` as expected.

**(b) Confirmed `sessions_send` parameter schema:**
```
sessionKey?: string
label?: string (1-512 chars)
agentId?: string (1-64 chars)
message: string          // required
timeoutSeconds?: integer (>= 0)   // default 30 if omitted; 0 = fire-and-forget
```
Read directly from the TypeBox schema `SessionsSendToolSchema` in
`openclaw-tools-KulZ1cdH.js`. **There is no `target` parameter** — this corrects the brief's
assumption. Use `sessionKey` or `label` (whichever the standing session was created/labeled with)
or `agentId` (which also auto-creates a missing main session for that agent) to target it.

**(c) Does a CLI-level session-creation command exist, or must it go through a live agent turn:**
Confirmed: **no CLI-level command exists.** `openclaw sessions` is list/maintenance-only
(`list`, `cleanup`, `compact`, `export-trajectory`, `tail`); `openclaw session` (singular) does not
exist at all. Session creation is only reachable through the in-agent `sessions_spawn` tool (or
implicitly via `sessions_send agentId:<id>` auto-creating a missing main session), both of which
require a live agent turn — e.g. via `openclaw tui --message "..."` or equivalent ingress — not a
direct CLI invocation.

## Caveats / things not verified live (flag for later tasks)

- No session currently exists for the `cipher` agent, so the actual shape of a session `key`
  string, and whether `sessions_spawn`'s `taskName` produces exactly that key or some derived
  form, was **not observed**. Task 3 must create one and re-run `sessions list --json` to confirm.
- `sessions_spawn`'s `cleanup` default (`"delete"` vs `"keep"`) was read from an enum definition,
  not confirmed as to which is the schema's default value.
- The interactive-input constraint noted in this task's instructions did not block any step —
  every command above ran non-interactively to completion.
