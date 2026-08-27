from __future__ import annotations

import httpx
import pytest

from alexa_bridge.announce import build_announcement_message, maybe_announce


def test_build_announcement_message_prefixes_short_text():
    message = build_announcement_message("Server is healthy.")
    assert message == "Cipher here -- Server is healthy."


def test_build_announcement_message_truncates_long_text():
    long_text = "x" * 1000
    message = build_announcement_message(long_text)
    assert len(message) <= 750
    assert message.endswith("...and more -- ask me for the full result.")


@pytest.mark.asyncio
async def test_skips_when_disabled():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    await maybe_announce(
        enabled=False,
        ha_url="http://127.0.0.1:8123",
        ha_token="token",
        notify_service="notify.alexa_media_test",
        dnd_entity="switch.test_dnd",
        result_text="done",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert calls == []


@pytest.mark.parametrize(
    ("ha_url", "ha_token", "notify_service", "dnd_entity"),
    [
        ("", "token", "notify.alexa_media_test", "switch.test_dnd"),
        ("http://127.0.0.1:8123", "", "notify.alexa_media_test", "switch.test_dnd"),
        ("http://127.0.0.1:8123", "token", "", "switch.test_dnd"),
        ("http://127.0.0.1:8123", "token", "notify.alexa_media_test", ""),
    ],
)
@pytest.mark.asyncio
async def test_skips_when_unconfigured(ha_url, ha_token, notify_service, dnd_entity):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    await maybe_announce(
        enabled=True,
        ha_url=ha_url,
        ha_token=ha_token,
        notify_service=notify_service,
        dnd_entity=dnd_entity,
        result_text="done",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert calls == []


@pytest.mark.asyncio
async def test_skips_notify_when_dnd_is_on():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/states/switch.test_dnd":
            return httpx.Response(200, json={"state": "on"})
        raise AssertionError("notify service should not be called when DND is on")

    await maybe_announce(
        enabled=True,
        ha_url="http://127.0.0.1:8123",
        ha_token="token",
        notify_service="notify.alexa_media_test",
        dnd_entity="switch.test_dnd",
        result_text="done",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_calls_notify_service_when_dnd_is_off():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/states/switch.test_dnd":
            return httpx.Response(200, json={"state": "off"})
        assert request.url.path == "/api/services/notify/alexa_media_test"
        return httpx.Response(200, json=[])

    await maybe_announce(
        enabled=True,
        ha_url="http://127.0.0.1:8123",
        ha_token="token",
        notify_service="notify.alexa_media_test",
        dnd_entity="switch.test_dnd",
        result_text="Server is healthy.",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert len(calls) == 2
    import json

    body = json.loads(calls[1].content)
    assert body == {"message": "Cipher here -- Server is healthy."}


@pytest.mark.asyncio
async def test_never_raises_on_ha_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    await maybe_announce(
        enabled=True,
        ha_url="http://127.0.0.1:8123",
        ha_token="token",
        notify_service="notify.alexa_media_test",
        dnd_entity="switch.test_dnd",
        result_text="done",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_never_raises_on_notify_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/states/switch.test_dnd":
            return httpx.Response(200, json={"state": "off"})
        return httpx.Response(500)

    await maybe_announce(
        enabled=True,
        ha_url="http://127.0.0.1:8123",
        ha_token="token",
        notify_service="notify.alexa_media_test",
        dnd_entity="switch.test_dnd",
        result_text="done",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
