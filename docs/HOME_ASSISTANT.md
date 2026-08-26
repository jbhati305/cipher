# Home Assistant

Cipher talks directly to Home Assistant's local REST API, not through Alexa. Create a long-lived
access token in the Home Assistant profile and store it only in `.env`:

```env
HOME_ASSISTANT_URL=http://127.0.0.1:8123
HOME_ASSISTANT_TOKEN=<local-secret>
```

The MCP tools expose state reads, filtered entity listing, and service calls. Reads require an
allowlisted domain. Controls require all of:

- a valid `domain.object_id`;
- a domain not on the deny list;
- an exact entity in `control.entities`;
- an exact domain/service pair in `control.services`;
- the service domain matching the entity domain.

Locks, alarm control panels, and covers are denied by default. Add only low-risk entities you are
comfortable controlling without a separate confirmation. Use a dedicated Home Assistant user/token
with the least privileges practical and rotate it if the host or token is compromised.

Official references reviewed 2026-08-26:
[Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/) and
[authentication API](https://developers.home-assistant.io/docs/auth_api/).
