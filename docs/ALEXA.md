# Alexa Custom Skill

Cipher is an Alexa Custom Skill. It does not alter Amazon's built-in intents or smart-home routing.

```text
Alexa + ordinary request          -> normal Alexa
Alexa, Cipher                     -> launches the Cipher skill
Alexa, ask Cipher to <request>    -> one-shot Cipher request where recognition matches
```

`Cipher` alone is not a supported hardware wake word on ordinary Echo devices. Replacing the wake
word requires future custom voice hardware or Home Assistant voice satellites.

## Interaction model

The `en-US` and `en-IN` models each use one `CipherQueryIntent` with one `AMAZON.SearchQuery` slot.
Amazon requires a carrier phrase in intent samples, so examples use `ask`, `do`, `check`, `tell me`,
`find out`, or `to`. This supports phrases such as "Alexa, ask Cipher to check my server health."
After a launch, recognition works best when the next phrase starts with one of those carriers.
Alexa free-form recognition is inherently imperfect, and an empty slot gets a gentle retry prompt.

Yes and No are forwarded into the same stable OpenClaw conversation so an exact pending action can
continue. Stop and Cancel end only the custom skill session.

## Connect your laptop

No AWS account or Lambda function is needed — Alexa calls the Cipher Bridge on your laptop
directly over a [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel) HTTPS
URL, which Amazon accepts as a self-hosted web-service endpoint as long as it presents a
publicly-trusted certificate (Funnel's `*.ts.net` certificate, issued by Let's Encrypt, qualifies)
and verifies the request signature itself — which the bridge now does
(`src/alexa_bridge/alexa_signature.py`).

1. Install Tailscale on the laptop and sign in: `sudo tailscale up`.
2. In the Tailscale admin console, enable HTTPS certificates and Funnel for this tailnet (Funnel
   is off by default).
3. Start the bridge (`./cipher up`), then expose it: `sudo tailscale funnel 8787`. Tailscale
   prints a public URL such as `https://<device-name>.<tailnet-name>.ts.net`.
4. In the Alexa Developer Console, create a **Custom** skill named Cipher with invocation name
   `cipher`. Enable `en-US` and `en-IN`.
5. Copy the skill ID to `ALEXA_SKILL_ID` in `.env`, and generate `ALEXA_ID_HMAC_SECRET` (see
   `./cipher setup`, which generates it automatically).
6. Set the skill's endpoint to the Funnel URL from step 3, path `/alexa/query`
   (`https://<device-name>.<tailnet-name>.ts.net/alexa/query`), and choose "My development
   endpoint has a certificate from a trusted certificate authority."
7. Run `./cipher alexa package` and import/build `alexa/interaction-models/en-US.json` and
   `en-IN.json` in their locales from the generated `dist/alexa/` assets.
8. Test `LaunchRequest`, a query, and Yes/No confirmation in the Alexa simulator before trying a
   real Echo device.

The bridge verifies every request's Alexa signature and checks `applicationId` against
`ALEXA_SKILL_ID` before doing anything else — an unsigned or mis-addressed request never reaches
intent handling. It HMAC-hashes the raw Alexa user ID immediately on receipt and never logs it.

`./cipher tunnel setup` runs `tailscale up` and prints the exact next steps; `./cipher tunnel
status` runs `tailscale funnel status`.

Official references reviewed 2026-08-27:
[custom skill invocation](https://developer.amazon.com/en-US/docs/alexa/custom-skills/understanding-how-users-invoke-custom-skills.html),
[`AMAZON.SearchQuery`](https://developer.amazon.com/en-GB/docs/alexa/custom-skills/slot-type-reference.html),
[hosting a custom skill as a web service](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html),
and [request handling](https://developer.amazon.com/en-US/docs/alexa/custom-skills/handle-requests-sent-by-alexa.html).
