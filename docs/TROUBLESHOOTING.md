# Troubleshooting

## Doctor reports setup required

This is expected before real credentials exist. Follow the actionable line, then rerun the scoped
check. Missing optional Claude or Cloudflare components do not make core read-only tests fail.

## OpenClaw is not using Codex

Run `./cipher configure`, authenticate, restart, and start a new OpenClaw conversation. `/status`
should identify the OpenAI Codex runtime. Do not use legacy `codex/gpt-*` refs. Leave the model empty
or choose an exact `openai/<id>` returned by current discovery.

## Cipher MCP probe fails

Run `scripts/run-mcp.sh` from the repository. It should remain quiet on stdio waiting for MCP input.
Then run `openclaw mcp doctor cipher-tools --probe`. Check that `.venv` exists and the Gateway user
can read the repository/config and write `state/`.

## Docker permission denied

Confirm the service user can run the exact read-only Docker CLI call manually. Do not solve this by
giving the LLM a socket mount or root. Prefer a dedicated least-privilege helper in a future version
if local Docker group membership is too broad for the host's risk profile.

## Alexa says it could not reach Cipher

Check, in order: `./cipher status`, `/readyz`, `tailscale funnel status`, that `ALEXA_SKILL_ID` in
`.env` matches the Developer Console exactly, and that the console's endpoint path is
`/alexa/query`. Signature and application-ID failures intentionally return only
`invalid_signature`/`invalid_request`; use the bridge's correlation-ID logs without enabling raw
request logging.

## Alexa misses a free-form request

Use a carrier phrase: "Alexa, ask Cipher to check ..." or, after launch, start with "check", "ask",
"do", "tell me", or "find out". `AMAZON.SearchQuery` is broad but not dictation-quality speech
recognition.

## Slow result never finishes

Ask "what's the result of my last task?" If the bridge restarted, the task is marked interrupted and
must be resubmitted. Check OpenClaw private task/session status for work that outlived the HTTP edge.
