# Central secrets and config

This server keeps secrets and shared config in two files at `$HOME`, outside any git repo:

- `~/.auth_keys.sh` — actual secrets/credentials (tokens, keys). `chmod 600`.
- `~/.env_vars.sh` — non-secret config (URLs, ports, log levels). `chmod 600` too — hostnames and
  ports are still useful recon for an attacker even if not "secret" on their own.

Both are plain bash, one `export KEY="value"` per line, grouped by service with a `# --- <service>
---` comment header. A variable a second service wants to reuse (e.g. a shared search API key) is
just defined once and both services' sync step reads the same name — there's no per-service
namespacing on the variable names themselves, so pick names that won't collide across services
before adding a new one.

**Never commit these files anywhere, and never print their contents in a way that could end up in
a log, a shared terminal, or a paste.**

## Why `.env` still exists

Cipher's systemd unit uses `EnvironmentFile=.env`, and `EnvironmentFile` only accepts a plain
`KEY=VALUE` file — it can't `source` a bash script. So `.env` isn't going away; it's a *generated
artifact* now, not something to hand-edit. The two central files are the actual source of truth.

`./cipher sync-env` sources both central files and regenerates `.env` from them (see
`scripts/sync-env.sh`). Run it after changing a value in either central file, then
`./cipher restart` to pick it up. `./cipher setup` still works standalone (generates its own
random secrets into `.env` on first run per the original bootstrap flow) if you're setting up
without the central files present, but once they exist, `sync-env` is the source of truth going
forward.

## Adding a new service to this convention

1. Add its secrets to `~/.auth_keys.sh` and non-secret config to `~/.env_vars.sh`, under a new
   `# --- <service> ---` section.
2. Give that service its own equivalent of `sync-env.sh` — source both central files, write out
   whatever env-file format that service actually needs (a `.env`, a systemd drop-in, etc.),
   `chmod 600` the result.
3. Do not point a service directly at `~/.auth_keys.sh` as its `EnvironmentFile` — systemd doesn't
   execute it as a script, so exported values won't parse the way you'd expect.
