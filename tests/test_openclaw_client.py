from __future__ import annotations

import json

import httpx
import pytest

from alexa_bridge.openclaw import OpenClawClient, OpenClawError


@pytest.mark.asyncio
async def test_correct_agent_and_stable_session_identity_without_token_leak():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": [{"content": [{"type": "output_text", "text": "Jellyfin is healthy."}]}]
            },
        )

    client = OpenClawClient(
        base_url="http://127.0.0.1:18789",
        token="gateway-secret",
        agent_id="cipher",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    answer = await client.ask("check Jellyfin", "a" * 64, "request-1")
    assert answer == "Jellyfin is healthy."
    request = requests[0]
    assert request.headers["x-openclaw-agent-id"] == "cipher"
    # Must be prefixed with "agent:<agentId>:" -- OpenClaw routes by session-key
    # namespace, not solely by the x-openclaw-agent-id header. A bare "alexa:<hash>"
    # key silently routed real requests to the unrestricted default "main" agent
    # instead of "cipher" (verified live against the Gateway) -- this test
    # previously encoded that exact bug as if it were correct behavior.
    assert request.headers["x-openclaw-session-key"] == f"agent:cipher:alexa:{'a' * 64}"
    body = json.loads(request.content)
    assert body["user"] == f"alexa:{'a' * 64}"
    assert f"alexa:{'a' * 64}" in body["instructions"]
    assert "gateway-secret" not in json.dumps(body)
    assert "gateway-secret" not in answer


@pytest.mark.asyncio
async def test_openclaw_auth_error_is_sanitized():
    client = OpenClawClient(
        base_url="http://127.0.0.1:18789",
        token="gateway-secret",
        agent_id="cipher",
        timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(401)),
    )
    with pytest.raises(OpenClawError, match="authentication failed") as exc:
        await client.ask("hello", "a" * 64, "request-1")
    assert "gateway-secret" not in str(exc.value)
