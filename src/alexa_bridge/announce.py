from __future__ import annotations

import logging

import httpx

LOGGER = logging.getLogger("cipher.alexa_bridge.announce")

_MAX_MESSAGE_CHARS = 750
_TRUNCATION_SUFFIX = "...and more -- ask me for the full result."
_PREFIX = "Cipher here -- "


def build_announcement_message(result_text: str) -> str:
    """Format a background task's result for an unsolicited spoken announcement.

    Prefixed so it's unambiguous this wasn't spoken in response to a live question, and
    truncated defensively -- the full, untruncated text always remains available via the
    existing "ask me for the result" pending-task pattern regardless of this truncation.
    """
    text = f"{_PREFIX}{result_text}"
    if len(text) <= _MAX_MESSAGE_CHARS:
        return text
    cutoff = _MAX_MESSAGE_CHARS - len(_TRUNCATION_SUFFIX) - 1
    return text[:cutoff].rstrip() + " " + _TRUNCATION_SUFFIX


async def maybe_announce(
    *,
    enabled: bool,
    ha_url: str,
    ha_token: str,
    notify_service: str,
    dnd_entity: str,
    result_text: str,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Best-effort proactive spoken announcement of a background task's result.

    This is deliberately a side channel, never a dependency: any failure here (Home
    Assistant unreachable, Amazon API error, misconfiguration) is caught and logged, never
    raised. The task's result is always already durably stored via TaskStore before this is
    called -- callers must not rely on this function for correctness, only as a convenience.
    """
    if not enabled or not ha_url or not ha_token or not notify_service or not dnd_entity:
        return
    domain, _, service = notify_service.partition(".")
    if not domain or not service:
        LOGGER.warning(
            "proactive announcement skipped: invalid notify_service %r",
            notify_service,
            extra={"operation": "proactive_announce", "status": "skipped"},
        )
        return
    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            base_url=ha_url, timeout=timeout_seconds, transport=transport
        ) as client:
            dnd_response = await client.get(f"/api/states/{dnd_entity}", headers=headers)
            dnd_response.raise_for_status()
            if dnd_response.json().get("state") == "on":
                LOGGER.info(
                    "proactive announcement skipped: do not disturb is on",
                    extra={"operation": "proactive_announce", "status": "skipped"},
                )
                return
            message = build_announcement_message(result_text)
            notify_response = await client.post(
                f"/api/services/{domain}/{service}",
                headers=headers,
                json={"message": message},
            )
            notify_response.raise_for_status()
        LOGGER.info(
            "proactive announcement sent",
            extra={"operation": "proactive_announce", "status": "sent"},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort side channel, must never raise
        LOGGER.warning(
            "proactive announcement failed: %s",
            exc,
            extra={"operation": "proactive_announce", "status": "failed"},
        )
