from __future__ import annotations

import httpx
import pytest

from cipher_mcp.home_assistant import HomeAssistantClient, HomeAssistantError
from cipher_mcp.policy import PolicyDenied


def test_read_allowed_entity(runtime_config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/api/states/sensor.room_temperature"
        return httpx.Response(200, json={"entity_id": "sensor.room_temperature", "state": "23"})

    client = HomeAssistantClient(runtime_config, httpx.MockTransport(handler))
    assert client.get_state("sensor.room_temperature")["state"] == "23"


def test_call_allowed_service(runtime_config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/services/light/turn_off"
        assert b'"entity_id":"light.office"' in request.content
        return httpx.Response(200, json=[{"entity_id": "light.office", "state": "off"}])

    client = HomeAssistantClient(runtime_config, httpx.MockTransport(handler))
    result = client.call_service("light", "turn_off", "light.office")
    assert result["ok"] is True


@pytest.mark.parametrize(
    ("domain", "service", "entity"),
    [
        ("lock", "unlock", "lock.front_door"),
        ("light", "turn_off", "light.unlisted"),
        ("light", "delete", "light.office"),
    ],
)
def test_reject_denied_or_unlisted_control(runtime_config, domain, service, entity):
    client = HomeAssistantClient(
        runtime_config, httpx.MockTransport(lambda _request: httpx.Response(500))
    )
    with pytest.raises(PolicyDenied):
        client.call_service(domain, service, entity)


def test_invalid_token_is_actionable(runtime_config):
    client = HomeAssistantClient(
        runtime_config, httpx.MockTransport(lambda _request: httpx.Response(401))
    )
    with pytest.raises(HomeAssistantError, match="rejected"):
        client.get_state("sensor.room_temperature")


def test_unreachable_home_assistant(runtime_config):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = HomeAssistantClient(runtime_config, httpx.MockTransport(handler))
    with pytest.raises(HomeAssistantError, match="unreachable"):
        client.get_state("sensor.room_temperature")
