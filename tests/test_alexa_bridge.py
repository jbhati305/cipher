from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_module
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

import alexa_bridge.app as app_module
from alexa_bridge.alexa_signature import AlexaSignatureError
from alexa_bridge.app import create_app
from alexa_bridge.security import ReplayStore
from alexa_bridge.settings import BridgeSettings
from alexa_bridge.tasks import TaskStore

SKILL_ID = "amzn1.ask.skill.test"
RAW_USER_ID = "amzn1.ask.account.test-user"
ID_HMAC_SECRET = "i" * 64


class FakeOpenClaw:
    def __init__(self, answer: str = "All healthy.", delay: float = 0) -> None:
        self.answer = answer
        self.delay = delay
        self.calls = []

    async def ask(self, query, requester_hash, correlation_id):  # noqa: ANN001, ANN201
        self.calls.append((query, requester_hash, correlation_id))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.answer


def settings(
    tmp_path: Path, *, budget: float = 1, openclaw_token: str = "gateway-token"
) -> BridgeSettings:
    return BridgeSettings(
        id_hmac_secret=ID_HMAC_SECRET,
        skill_id=SKILL_ID,
        host="127.0.0.1",
        port=8787,
        max_body_bytes=4096,
        signature_max_age_seconds=150,
        rate_limit_per_minute=20,
        sync_budget_seconds=budget,
        openclaw_timeout_seconds=5,
        openclaw_base_url="http://127.0.0.1:18789",
        openclaw_gateway_token=openclaw_token,
        openclaw_agent_id="cipher",
        state_dir=tmp_path,
        log_level="CRITICAL",
        verbose_request_logging=False,
    )


def envelope(
    *,
    request_type: str = "IntentRequest",
    intent_name: str = "CipherQueryIntent",
    query: str | None = "check my server",
    request_id: str | None = None,
) -> dict:
    body: dict = {
        "version": "1.0",
        "session": {
            "application": {"applicationId": SKILL_ID},
            "user": {"userId": RAW_USER_ID},
        },
        "request": {
            "type": request_type,
            "requestId": request_id or f"amzn1.echo-api.request.{uuid.uuid4()}",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }
    if request_type == "IntentRequest":
        body["request"]["intent"] = {"name": intent_name, "slots": {}}
        if intent_name == "CipherQueryIntent" and query is not None:
            body["request"]["intent"]["slots"] = {"Query": {"value": query}}
    return body


def make_app(
    tmp_path: Path, fake: FakeOpenClaw, *, budget: float = 1, openclaw_token: str = "gateway-token"
):
    config = settings(tmp_path, budget=budget, openclaw_token=openclaw_token)
    return create_app(
        config,
        openclaw_client=fake,
        replay_store=ReplayStore(tmp_path / "replay.sqlite3"),
        task_store=TaskStore(tmp_path / "tasks.sqlite3"),
    )


@pytest.fixture(autouse=True)
def _accept_signature(monkeypatch):
    monkeypatch.setattr(app_module, "verify_alexa_signature", lambda *a, **k: None)  # noqa: ARG005


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "10.0.0.5"),
        ("openclaw_base_url", "http://192.168.1.20:18789"),
        ("openclaw_base_url", "http://user:password@127.0.0.1:18789"),
    ],
)
def test_bridge_rejects_non_loopback_or_credentialed_endpoints(tmp_path, field, value):
    with pytest.raises(ValueError):
        replace(settings(tmp_path), **{field: value}).validate(require_secrets=True)


def test_bridge_accepts_zero_bind_host_for_container_use(tmp_path):
    replace(settings(tmp_path), host="0.0.0.0").validate(require_secrets=True)  # noqa: S104


@pytest.mark.asyncio
async def test_launch_request_greets(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(request_type="LaunchRequest"))
    assert response.status_code == 200
    assert "Cipher online" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_help_intent(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(intent_name="AMAZON.HelpIntent")
        )
    assert response.json()["response"]["shouldEndSession"] is False
    assert "Ask me a question" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_stop_intent_ends_session(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(intent_name="AMAZON.StopIntent")
        )
    assert response.json()["response"]["shouldEndSession"] is True


@pytest.mark.asyncio
async def test_query_intent_echoes_when_openclaw_not_configured(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw(), openclaw_token="")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query="check my server"))
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "Cipher heard you say: check my server" in text
    assert "isn't connected yet" in text


@pytest.mark.asyncio
async def test_query_intent_calls_openclaw_when_configured(tmp_path):
    fake = FakeOpenClaw()
    app = make_app(tmp_path, fake)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query="check my server"))
    assert response.json()["response"]["outputSpeech"]["text"] == "All healthy."
    expected_hash = hmac_module.new(
        ID_HMAC_SECRET.encode(), RAW_USER_ID.encode(), hashlib.sha256
    ).hexdigest()
    assert fake.calls[0] == ("check my server", expected_hash, fake.calls[0][2])


@pytest.mark.asyncio
async def test_empty_query_slot_reprompts(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query=""))
    assert "didn't catch" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_wrong_application_id_rejected(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    body = envelope()
    body["session"]["application"]["applicationId"] = "amzn1.ask.skill.someone-else"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=body)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_invalid_signature_returns_400(tmp_path, monkeypatch):
    def _raise(*_args, **_kwargs):
        raise AlexaSignatureError("bad signature")

    monkeypatch.setattr(app_module, "verify_alexa_signature", _raise)
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope())
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_signature"}


@pytest.mark.asyncio
async def test_replayed_request_id_rejected(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    body = envelope(request_id="amzn1.echo-api.request.fixed")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/alexa/query", json=body)
        second = await client.post("/alexa/query", json=body)
    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_unconfigured_bridge_refuses_queries(tmp_path):
    config = replace(settings(tmp_path), id_hmac_secret="")
    app = create_app(
        config,
        openclaw_client=FakeOpenClaw(),
        replay_store=ReplayStore(tmp_path / "replay.sqlite3"),
        task_store=TaskStore(tmp_path / "tasks.sqlite3"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope())
    assert response.status_code == 503
    assert response.json() == {"error": "not_ready"}


@pytest.mark.asyncio
async def test_malformed_body_returns_400(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", content=b"{not json", headers={"content-type": "application/json"}
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_timeout_returns_pending_without_cancelling_work(tmp_path):
    fake = FakeOpenClaw(answer="Analysis complete.", delay=0.1)
    app = make_app(tmp_path, fake, budget=0.001)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(query="analyze a large log")
        )
        await asyncio.sleep(0.12)
        result_response = await client.post(
            "/alexa/query",
            json=envelope(
                query="what's the result of my last task",
                request_id="amzn1.echo-api.request.result",
            ),
        )
    assert response.status_code == 200
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "still working" in text
    assert result_response.json()["response"]["outputSpeech"]["text"] == "Analysis complete."
