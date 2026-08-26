# Installation

## Requirements

- Ubuntu/Debian-class Linux with Python 3.11+, Git, curl, OpenSSL, and systemd user services.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for managing the pinned Python
  environment (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- OpenClaw's supported Node runtime. Its official installer provisions a supported version when the
  installed Node is too old.
- Docker CLI access for the unprivileged service account if Docker tools are wanted.
- Optional: Claude Code, Tailscale, and ASK CLI.

The setup command uses OpenClaw's official host installer with `--no-onboard`; it does not clone or
execute an unofficial fork.

```bash
./cipher setup
./cipher auth codex
./cipher auth claude       # optional
./cipher configure
```

`setup` runs `uv sync --extra dev` to create the `.venv` pinned by `uv.lock`, creates active
allowlist files from examples without overwriting existing files, generates secrets in `.env`,
installs/configures the native OpenClaw plugins, and installs user systemd units.

Edit these files before starting:

```text
.env
config/docker-allowlist.yaml
config/services-allowlist.yaml
config/home-assistant-allowlist.yaml
```

Then:

```bash
./cipher up
./cipher doctor
```

To start the user services at boot before an interactive login, run the one system-level command
shown by setup:

```bash
sudo loginctl enable-linger "$USER"
```

## Tailscale Funnel

See `docs/ALEXA.md`'s "Connect your laptop" section for the full walkthrough
(`tailscale up`, enabling Funnel, `sudo tailscale funnel 8787`, and configuring the Alexa skill
endpoint). `./cipher tunnel setup` runs `tailscale up` and prints the exact next steps;
`./cipher tunnel status` runs `tailscale funnel status`.

Official references reviewed 2026-08-27: [OpenClaw installation](https://docs.openclaw.ai/install)
and [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).
