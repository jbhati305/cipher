# Claude Code specialist

Claude Code is optional and used only for explicit or suitable coding/repository analysis tasks.

```bash
./cipher auth claude
./cipher doctor claude
```

The installer is Anthropic's official native Linux installer. Authentication uses the current
`claude auth login`; status uses `claude auth status`.

OpenClaw runs Claude through the official `@openclaw/acpx` backend with `allowedAgents=["claude"]`.
The repository keeps the conservative defaults explicit:

```text
permissionMode = approve-reads
nonInteractivePermissions = deny
pluginToolsMcpBridge = false
openClawToolsMcpBridge = false
```

This permits read-only specialist work and gracefully denies unattended write/exec prompts. Do not
change it to `approve-all` merely to avoid approval friction, and never add Claude's bypass flags.

Official references reviewed 2026-08-26:
[Claude Code setup](https://code.claude.com/docs/en/getting-started),
[Claude CLI auth](https://code.claude.com/docs/en/cli-usage), and
[OpenClaw ACP setup](https://docs.openclaw.ai/tools/acp-agents-setup).
