# Operations

```bash
./cipher up
./cipher down
./cipher restart
./cipher status
./cipher doctor
./cipher logs --lines 200
./cipher logs --follow
```

The Gateway and Alexa Bridge are systemd user services with automatic restart. The bridge writes
narrow SQLite state under `state/`. Back up `.env` and active `config/*.yaml` to an encrypted secret
store; they are intentionally not Git content. OpenClaw owns its own session/memory backup process.

Health endpoints:

```text
http://127.0.0.1:8787/healthz  process alive
http://127.0.0.1:8787/readyz   local secret/config readiness
```

`./cipher update` refuses a dirty worktree, fast-forwards Git, refreshes pinned Python packages,
uses official OpenClaw/Claude update commands when installed, then runs lint, tests, and doctor. It
does not reset, discard, or auto-merge local changes.

Python dependencies are exact-pinned. OpenClaw's stable installer/plugin manager owns a compatible
Codex app-server version. Claude's native installer follows its configured stable/latest channel;
choose stable in Claude settings if immediate automatic updates are undesirable.
