# Security and threat model

## Invariants

1. The LLM may select a typed capability; it may not select a raw privileged command.
2. External text is data, never authority. This includes Alexa speech, websites, logs, container
   metadata, service output, and Home Assistant names/attributes.
3. The public path terminates at a narrow bridge. The Gateway and infrastructure APIs stay private.
4. Authorization is enforced in code and allowlists, not only in prompts.

## Threats and controls

| Threat | Primary controls |
| --- | --- |
| Malicious/replayed Alexa request | Bridge verifies Alexa's request signature and certificate chain directly; `applicationId` checked against `ALEXA_SKILL_ID`; 150-second freshness; one-time replay database keyed on Alexa's `requestId`; size and rate limits |
| Stolen `ALEXA_ID_HMAC_SECRET` | Rotate in `.env` and restart the bridge; an attacker still cannot forge a valid Alexa request signature, since that key never leaves Amazon |
| Exposed Tailscale Funnel URL | Funnel forwards exactly one local port (the bridge); Gateway/Codex/Claude/MCP/Home Assistant ports are never funneled; bridge authentication (Alexa signature + `applicationId` check) still applies |
| Prompt injection from websites/logs | Agent instruction marks content untrusted; typed tools; no raw command tool; bounded log output |
| Malicious container/service name | strict grammar, exact allowlist, fixed argv, `shell=False`; injection regression tests |
| Tool argument injection | Pydantic/MCP schemas, identifier validation, action enums, maximums, exact HA entity/service policy, explicit MCP safety annotations |
| Compromised Home Assistant token | token in environment only; local endpoint; HA-side least privilege; separate entity control allowlist; sensitive domains denied |
| Compromised Codex/Claude session | guardian/approve-reads policies; workspace boundary; no bypass flags; dedicated agent workspace; Gateway/Brave credentials use file SecretRefs instead of inherited `.env`. **Only covers Cipher's primary model, which is pinned off the Codex app-server harness (see the residual-risk note below) — it does not cover the delegated Codex specialist session, which is unprotected by this row's controls.** |
| Arbitrary shell/Docker escalation | no generic shell MCP tool, no Docker exec/run, no socket handed to the model, no sudo; MCP service user must remain unprivileged — true for Cipher's own MCP tool surface, but **the delegated Codex specialist session can still reach Codex's own native `bash` tool, which is outside this control** (see the residual-risk note below) |
| Leaked repository secrets | comprehensive `.gitignore`; generated `.env` mode 0600; CI never needs real credentials; doctor/logging redact by omission |

## Residual risk: the delegated Codex specialist session is not hardened (open, accepted)

Codex's own app-server harness exposes native tools (notably `bash`) that bypass OpenClaw's
`tools.deny` entirely — the `group:fs`/`group:runtime` deny entries only cover OpenClaw's generic
tool names, not Codex-native ones. This was empirically confirmed, not theorized: with
`appServer.sandbox="read-only"` and `approvalsReviewer="user"` set, a live probe could still read
`/etc/passwd` through this path.

Cipher's primary model is hardened against this: it carries an explicit
`agentRuntime.id: "openclaw"` override that routes it through OpenClaw's embedded runtime instead of
the Codex app-server harness, where `tools.allow`/`tools.deny` is correctly enforced (re-verified
live after the fix: the same `/etc/passwd` read is refused, and the primary model has no bash/exec
tool at all).

**The standing `cipher-specialist-codex` session is intentionally NOT hardened the same way** — it
stays on the real Codex app-server runtime, for the reasoning quality that runtime provides — and so
it retains the exact same `tools.deny` bypass, unpatched. Cipher's own `tools.allow` permits calling
`sessions_send`, so this session is currently reachable from ordinary delegated requests. The
operator was asked explicitly whether to cut off delegation until this is resolved, and chose to
accept the risk short-term rather than lose delegation. This is a known, open, accepted gap, not a
resolved one — no narrower Codex sandbox that actually confines reads (not just writes) is known to
exist yet. See `docs/ARCHITECTURE.md`'s decision record for the full router design this sits inside.

## Confirmation semantics

Container and service mutations create a cryptographically random token in local SQLite. The stored
record hashes both token and requester, records exact action/target/arguments, has a short TTL, and
is atomically one-time. A different requester, target, action, expired token, or replay is rejected.

MCP does not itself authenticate end-user channel identities. The current agent supplies the stable
requester ID from its OpenClaw session. Consequently, keep the MCP server available only to the
dedicated Cipher agent (the repository restricts its Codex projection and tool policy) and preserve
OpenClaw's channel/session authentication. A future OpenClaw MCP
context feature that cryptographically conveys session subject should replace this trust handoff
when available.

## Secrets and logs

Structured bridge logs include UTC timestamp, correlation ID, channel, operation, duration, and
status. They omit raw voice text, Alexa user IDs, authorization headers, and tokens. Verbose request
logging is reserved but remains off by default. OpenClaw receives narrow file SecretRefs rather
than the whole application `.env`, and fixed host commands run with an environment allowlist that
omits application secrets. Do not paste `.env`, Codex `auth.json`, Claude credentials, tunnel JSON,
or full debug logs into tickets.

If a secret is suspected leaked: remove public ingress, rotate the bridge and ID-HMAC secrets,
rotate the Gateway and Home Assistant tokens, revoke Codex/Claude sessions as needed, and review
private journal logs by correlation ID.
