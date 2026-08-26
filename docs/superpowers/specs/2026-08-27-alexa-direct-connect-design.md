# Alexa Direct-Connect (No Lambda) — Design

## Goal

Replace the Lambda-mediated Alexa architecture with a direct connection: Alexa calls the
laptop-hosted Cipher Bridge over a Tailscale Funnel HTTPS URL. First deployment proves only that
Echo Dot <-> laptop communication works — no OpenClaw call yet.

## Why

- User owns a laptop and wants to use it as the server directly; no interest in paying for /
  maintaining an AWS account and Lambda function just to relay a request Alexa could call directly.
- Alexa Custom Skills support a self-hosted HTTPS endpoint as an alternative to Lambda, as long as
  the endpoint presents an Amazon-trusted certificate and verifies the request signature itself
  (confirmed against current Alexa Skills Kit docs, reviewed 2026-08-27).
- Tailscale Funnel provides exactly that kind of publicly-trusted HTTPS URL (`*.ts.net`, backed by a
  real Let's Encrypt certificate) pointed at a local port, replacing Cloudflare Tunnel.
- First deployment must be minimal: prove the wiring works before adding OpenClaw/Codex, which
  isn't installed on the real target laptop yet.

## Architecture

```
Amazon Alexa (Echo Dot)
     |
     | HTTPS to https://<name>.ts.net/alexa/query
     v
Tailscale Funnel (on the laptop, terminates public TLS)
     |
     v
127.0.0.1:8787  Cipher Alexa Bridge (FastAPI, unchanged loopback binding)
     |
     v
Verify Alexa request signature -> parse intent -> build Alexa response JSON
(OpenClaw call path stays in the code, gated off until OPENCLAW_GATEWAY_TOKEN is configured)
```

No AWS account, no Lambda, no Cloudflare. `infra/aws/`, `infra/cloudflare/`, and `alexa/lambda/` are
deleted; there is nothing left for them to do once Alexa talks to the bridge directly.

## Components

### 1. `src/alexa_bridge/alexa_signature.py` (new)

Implements Amazon's documented self-hosted-webservice verification algorithm directly (no
dependency on the low-maintenance `ask-sdk-webservice-support` package — `cryptography`, already a
resolved dependency, becomes a direct pin):

- `verify_alexa_signature(body: bytes, headers: Mapping[str, str], max_age_seconds: int, now: int | None = None) -> None`
  raises `AlexaSignatureError` (subclass of the existing `security.AuthenticationError`) on any
  failure, else returns.
- Steps: validate `SignatureCertChainUrl` header (`https://s3.amazonaws.com/echo.api/...`, port
  443 if present); fetch the cert chain over HTTPS; validate not-before/not-after and
  `echo-api.amazon.com` in the leaf certificate's SAN; verify chain of trust; extract the leaf
  public key; base64-decode `Signature-256`; verify it against the SHA-256 digest of the exact raw
  request body; check the request's `timestamp` field is within `max_age_seconds` (150 per Amazon's
  guidance) of wall-clock time.
- A small in-memory cache (dict keyed by cert chain URL, value expires at the earlier of the cert's
  `notAfter` or one hour) avoids re-fetching/re-validating the same cert per request.
- The HTTP fetch of the cert chain uses `httpx` (already a dependency) with a short timeout.

### 2. `src/alexa_bridge/security.py`

- Remove `verify_hmac_request` (Lambda-specific, no longer called anywhere).
- Keep `AuthenticationError`, `ReplayStore`, `RateLimiter` — `ReplayStore.accept_once` is reused,
  now keyed on the Alexa request's `request.requestId` instead of a signature+timestamp pair.

### 3. `src/alexa_bridge/settings.py`

Field changes on `BridgeSettings`:
- Remove: `bridge_secret`, `hmac_max_age_seconds`.
- Add: `id_hmac_secret: str` (from `ALEXA_ID_HMAC_SECRET`, already in `.env.example` — previously
  only read by the now-deleted Lambda), `skill_id: str` (from `ALEXA_SKILL_ID`, same situation),
  `signature_max_age_seconds: int` (from `ALEXA_SIGNATURE_MAX_AGE_SECONDS`, default `150`).
- `validate(require_secrets=True)`: require `len(id_hmac_secret) >= 32` and non-empty `skill_id`
  instead of the old `bridge_secret` check. `OPENCLAW_GATEWAY_TOKEN` becomes NOT required (the
  bridge must work in echo-only mode without it) — `require_secrets` now only gates
  `id_hmac_secret`/`skill_id`.
- Fix the pre-existing bug: `_is_loopback_host` accepts a literal loopback address OR `0.0.0.0`
  (needed for the Docker Compose deployment added last session, where the app must bind all
  interfaces inside the container while the host-side port publish is what actually restricts
  exposure to `127.0.0.1` — a bound-to-127.0.0.1 process is unreachable through Docker's port
  publishing, a standard Docker networking limitation, not a Cipher-specific relaxation).

### 4. `src/alexa_bridge/app.py`

`/alexa/query` is rewritten to be the literal Alexa skill endpoint:

1. Read the raw body; enforce `max_body_bytes` as today.
2. Call `verify_alexa_signature(body, request.headers, config.signature_max_age_seconds)`; on
   `AlexaSignatureError`, log a warning (existing style, no raw body/signature logged) and return
   HTTP 400 (per Amazon's requirement — signature failures must be 400, not 401).
3. Parse the JSON body into a small `AlexaRequestEnvelope` pydantic model covering exactly the
   fields used: `request.type`, `request.requestId`, `request.timestamp`, `request.intent.name`,
   `request.intent.slots.Query.value`, `session.application.applicationId` (falling back to
   `context.System.application.applicationId`), and the raw Alexa user ID (same fallback path).
   Malformed bodies return 400.
4. Check `applicationId == config.skill_id`; mismatch returns 400 (defense in depth, mirrors what
   the Lambda used to do).
5. Reject a replayed `requestId` via `ReplayStore.accept_once` (expiry = now + signature_max_age);
   a repeat returns 400.
6. Derive `user_hash = hmac.new(config.id_hmac_secret, raw_user_id, sha256).hexdigest()` immediately;
   the raw ID is never logged or stored beyond this line (same guarantee as before, just moved from
   Lambda into this function).
7. Build the Alexa response JSON directly (`{"version": "1.0", "response": {"outputSpeech": ...,
   "shouldEndSession": ..., "reprompt": ...}}`), replacing the old `{"answer": ...}` shape used for
   the Lambda<->bridge protocol:
   - `LaunchRequest` -> "Cipher online. What do you need?" (`shouldEndSession=False`, reprompt same)
   - `SessionEndedRequest` -> `{}` (no response body needed)
   - `AMAZON.StopIntent` / `AMAZON.CancelIntent` -> "Cipher offline." (`shouldEndSession=True`)
   - `AMAZON.HelpIntent` -> help text (`shouldEndSession=False`, reprompt "What should Cipher do?")
   - `CipherQueryIntent` with an empty/missing `Query` slot -> "I didn't catch the request. Please
     say it again." (`shouldEndSession=False`, reprompt "What do you need?")
   - `CipherQueryIntent` with a query, **and `OPENCLAW_GATEWAY_TOKEN` unset** -> **"Cipher heard you
     say: `<query>`. The full assistant isn't connected yet."** (`shouldEndSession=False`) — this is
     the first-deployment proof-of-wiring path; no OpenClaw call, no task store.
   - `CipherQueryIntent` with a query, **and `OPENCLAW_GATEWAY_TOKEN` set** -> unchanged existing
     pipeline (rate limit -> task store -> OpenClaw call with sync budget -> pending/completed/failed
     shaped into the same Alexa response envelope instead of the old `{"answer": ...}` shape).
   - Any other intent name -> "I can't handle that Alexa intent. Try asking Cipher directly."
     (mirrors the Lambda's fallback)
8. `/healthz` and `/readyz` are unchanged.

### 5. Removed

- `alexa/lambda/` (`index.mjs`, `index.test.mjs`, `package.json`)
- `infra/aws/` (`template.yaml`)
- `infra/cloudflare/` (`config.example.yml`)
- SAM/Lambda-deploy sections of `docs/ALEXA.md` and `docs/INSTALL.md`
- `./cipher alexa deploy` (keep `./cipher alexa package`, repurposed to just validate/stage the
  interaction models and skill manifest — there is no Lambda zip to build anymore)
- `./cipher tunnel` is rewritten to wrap `tailscale up` / `tailscale funnel status` instead of
  `cloudflared`, keeping the same two-subcommand shape (`setup`, `status`) so the CLI surface stays
  consistent
- `ALEXA_BRIDGE_SECRET`, `ALEXA_HMAC_MAX_AGE_SECONDS`, `CIPHER_PUBLIC_URL`, `CLOUDFLARE_TUNNEL_ID`
  from `.env.example`, `scripts/bootstrap.sh`, `scripts/doctor.py`
- `ALEXA_SIGNATURE_MAX_AGE_SECONDS=150` added to `.env.example`

### 6. Docs

`docs/ALEXA.md` gains a short, copy-pasteable "Connect your laptop" section: install Tailscale,
`tailscale up`, enable HTTPS certs + Funnel for the tailnet in the admin console, `sudo tailscale
funnel 8787`, paste the printed `https://<name>.ts.net` URL into the Alexa Developer Console as the
skill's HTTPS endpoint (selecting "My development endpoint is a sub-domain of a domain that has a
wildcard certificate from a certificate authority" is NOT needed — Funnel's cert is a normal
single-host cert, so the plain "SSL certificate from a certificate authority" option applies).
No new automation beyond the existing `./cipher tunnel setup/status` wrapper — this is a one-time,
per-machine setup step.

`docs/ARCHITECTURE.md` decision record gets a short update: ingress is Tailscale Funnel, not
Cloudflare Tunnel; Alexa talks to the bridge directly, no Lambda hop.

## Testing

- `tests/test_alexa_signature.py` (new): valid request against a locally-generated test CA/leaf
  cert chain (fixture builds a throwaway cert chain, no network call in tests — the cert-chain
  fetch is mocked/injected); tampered body; expired timestamp; wrong `SignatureCertChainUrl` host;
  wrong SAN.
- `tests/test_alexa_bridge.py` (rewritten): replaces the old Lambda-HMAC-oriented tests with
  Alexa-envelope-oriented ones — `LaunchRequest`, `AMAZON.HelpIntent`, `AMAZON.StopIntent`,
  `CipherQueryIntent` echo response (no OpenClaw configured), `CipherQueryIntent` full pipeline
  (OpenClaw configured, reusing the existing `FakeOpenClaw`), replayed `requestId` rejected,
  wrong `applicationId` rejected, invalid signature rejected. Test helper builds signed requests
  using the same throwaway cert-chain fixture as the signature tests.
- `tests/test_policy_and_tools.py`: swap the `ALEXA_BRIDGE_SECRET` reference (env var being
  deleted) for `ALEXA_ID_HMAC_SECRET` in the "secrets never forwarded to a subprocess" test —
  same assertion, still-existing env var.

## Out of scope (explicitly, per user request)

- OpenClaw/Codex wiring verification — the echo-mode path exists precisely so this isn't required
  for the first deploy.
- `./cipher tunnel setup` automation beyond a thin wrapper — no ACL/admin-console automation
  (Tailscale doesn't expose that over a documented CLI-only flow suitable for scripting here).
- Any change to the MCP server, Home Assistant integration, confirmation policy, or Docker/uv work
  from the previous session — untouched.
