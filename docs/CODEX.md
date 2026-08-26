# Codex runtime

Cipher uses OpenClaw's official `@openclaw/codex` plugin and managed app-server over stdio. It does
not invoke `codex exec` once per user request. Authentication is interactive:

```bash
./cipher auth codex
./cipher doctor codex
```

The auth command runs `openclaw models auth login --provider openai --agent cipher --set-default`,
which scopes the profile to Cipher, supports the Codex OAuth/subscription path, and selects
OpenClaw's current recommended account model without hardcoding it in this repository. For direct
Codex CLI use on a headless server, official OpenAI guidance also supports
`codex login --device-auth`.

`CIPHER_PRIMARY_MODEL` is empty by default. Empty means use the current OpenClaw/Codex account
configuration and app-server discovery; it never expands to a guessed `latest` identifier. To pin a
model that is actually visible to the authenticated account, set the complete OpenClaw model ref
and rerun configure:

```env
CIPHER_PRIMARY_MODEL=openai/<model-returned-by-current-discovery>
```

`CIPHER_PRIMARY_RUNTIME=codex` adds an agent-scoped `openai/*` runtime rule. This makes the native
Codex harness fail closed: an incompatible route or unavailable app-server fails the turn instead
of silently falling back to OpenClaw's embedded runtime. Set it to `openclaw` only when that fallback
is an intentional deployment choice.

The repository explicitly sets `plugins.entries.codex.config.appServer.mode=guardian` and
`tools.exec.mode=auto`. Current OpenClaw documentation says guardian resolves to on-request,
automatic review, and `workspace-write` when allowed. Native Codex apps and computer-use are off.
The repository never sets YOLO or bypass flags.

Useful private operator checks are `openclaw models status --json`, `/codex account`, `/codex mcp`,
and `/status` (which should report `Runtime: OpenAI Codex`).

Official references reviewed 2026-08-26:
[OpenAI Codex app-server](https://developers.openai.com/codex/app-server/),
[OpenAI authentication](https://developers.openai.com/codex/auth/), and
[OpenClaw Codex harness reference](https://docs.openclaw.ai/plugins/codex-harness-reference).
