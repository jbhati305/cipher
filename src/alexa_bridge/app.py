from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .alexa_signature import AlexaSignatureError, verify_alexa_signature
from .announce import maybe_announce
from .logging import configure_logging
from .openclaw import OpenClawClient
from .security import RateLimiter, ReplayStore
from .settings import BridgeSettings
from .tasks import TaskStore

LOGGER = logging.getLogger("cipher.alexa_bridge")
_LAST_RESULT_QUERIES = {
    "what is the result of my last task",
    "what's the result of my last task",
    "whats the result of my last task",
    "get the result of my last task",
    "my last task",
}


class _Slot(BaseModel):
    value: str | None = None


class _Intent(BaseModel):
    name: str
    slots: dict[str, _Slot] = Field(default_factory=dict)


class _AlexaRequestBody(BaseModel):
    type: str
    requestId: str
    timestamp: str
    intent: _Intent | None = None


class _User(BaseModel):
    userId: str


class _Application(BaseModel):
    applicationId: str


class _SessionSection(BaseModel):
    application: _Application | None = None
    user: _User | None = None


class _System(BaseModel):
    application: _Application
    user: _User | None = None


class _ContextSection(BaseModel):
    System: _System


class AlexaRequestEnvelope(BaseModel):
    version: str
    session: _SessionSection | None = None
    context: _ContextSection | None = None
    request: _AlexaRequestBody

    @property
    def application_id(self) -> str:
        if self.session and self.session.application:
            return self.session.application.applicationId
        if self.context:
            return self.context.System.application.applicationId
        return ""

    @property
    def raw_user_id(self) -> str:
        if self.session and self.session.user:
            return self.session.user.userId
        if self.context and self.context.System.user:
            return self.context.System.user.userId
        return ""


def _normalize_query(value: str) -> str:
    return " ".join(value.strip().lower().rstrip(".?!").split())


def _latest_result_response(store: TaskStore, requester_hash: str) -> str:
    task = store.latest(requester_hash)
    if not task:
        return "You don't have a recent Cipher task."
    if task["status"] == "completed":
        return str(task["result"])
    if task["status"] == "running":
        return "I'm still working on your last task. Ask me again in a moment."
    if task["status"] == "interrupted":
        return "Your last task was interrupted when the Cipher bridge restarted. Please ask again."
    return "Your last task failed. Please try again or check Cipher's private logs."


def _alexa_response(
    text: str, *, end_session: bool, reprompt: str | None = None
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": end_session,
    }
    if reprompt:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return {"version": "1.0", "sessionAttributes": {}, "response": response}


def create_app(
    settings: BridgeSettings | None = None,
    *,
    openclaw_client: OpenClawClient | None = None,
    replay_store: ReplayStore | None = None,
    task_store: TaskStore | None = None,
    announce_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = settings or BridgeSettings.from_env()
    config.validate(require_secrets=False)
    configure_logging(config.log_level)
    replay = replay_store or ReplayStore(config.state_dir / "alexa-replay.sqlite3")
    tasks = task_store or TaskStore(config.state_dir / "alexa-tasks.sqlite3")
    rate_limiter = RateLimiter(config.rate_limit_per_minute)
    client = openclaw_client or OpenClawClient(
        base_url=config.openclaw_base_url,
        token=config.openclaw_gateway_token,
        agent_id=config.openclaw_agent_id,
        timeout_seconds=config.openclaw_timeout_seconds,
    )
    app = FastAPI(title="Cipher Alexa Bridge", docs_url=None, redoc_url=None)
    app.state.background_tasks = set()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        try:
            config.validate(require_secrets=True)
        except ValueError as exc:
            return JSONResponse({"status": "not_ready", "reason": str(exc)}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.post("/alexa/query")
    async def alexa_query(request: Request) -> JSONResponse:
        started = time.monotonic()
        correlation_id = str(uuid.uuid4())
        try:
            config.validate(require_secrets=True)
        except ValueError:
            return JSONResponse({"error": "not_ready"}, status_code=503)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.max_body_bytes:
                    return JSONResponse({"error": "request_too_large"}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "invalid_content_length"}, status_code=400)
        body = await request.body()
        if len(body) > config.max_body_bytes:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        try:
            raw = json.loads(body)
            envelope = AlexaRequestEnvelope.model_validate(raw)
        except (json.JSONDecodeError, ValidationError):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            await asyncio.to_thread(
                verify_alexa_signature,
                body,
                request.headers,
                envelope.request.timestamp,
                config.signature_max_age_seconds,
            )
        except AlexaSignatureError as exc:
            LOGGER.warning(
                "alexa signature rejected: %s",
                exc,
                extra={
                    "request_id": correlation_id,
                    "channel": "alexa",
                    "operation": "authenticate",
                    "status": "rejected",
                },
            )
            return JSONResponse({"error": "invalid_signature"}, status_code=400)
        if envelope.application_id != config.skill_id:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not replay.accept_once(
            envelope.request.requestId, int(time.time()) + config.signature_max_age_seconds
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        raw_user_id = envelope.raw_user_id
        if not raw_user_id:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        user_hash = hmac.new(
            config.id_hmac_secret.encode("utf-8"), raw_user_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        req = envelope.request
        if req.type == "LaunchRequest":
            return JSONResponse(
                _alexa_response(
                    "Cipher online. What do you need?",
                    end_session=False,
                    reprompt="What do you need?",
                )
            )
        if req.type == "SessionEndedRequest":
            return JSONResponse({})
        if req.type != "IntentRequest" or req.intent is None:
            return JSONResponse(
                _alexa_response(
                    "I didn't understand that request. Please try again.", end_session=False
                )
            )
        name = req.intent.name
        if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return JSONResponse(_alexa_response("Cipher offline.", end_session=True))
        if name == "AMAZON.HelpIntent":
            return JSONResponse(
                _alexa_response(
                    "Ask me a question or give me a task. For example, say check my server "
                    "health.",
                    end_session=False,
                    reprompt="What should Cipher do?",
                )
            )
        if name == "CipherQueryIntent":
            slot = req.intent.slots.get("Query")
            query = (slot.value or "").strip() if slot else ""
        elif name == "AMAZON.YesIntent":
            query = "yes"
        elif name == "AMAZON.NoIntent":
            query = "no"
        else:
            return JSONResponse(
                _alexa_response(
                    "I can't handle that Alexa intent. Try asking Cipher directly.",
                    end_session=False,
                )
            )
        if not query:
            return JSONResponse(
                _alexa_response(
                    "I didn't catch the request. Please say it again.",
                    end_session=False,
                    reprompt="What do you need?",
                )
            )
        if not config.openclaw_gateway_token:
            return JSONResponse(
                _alexa_response(
                    f"Cipher heard you say: {query}. The full assistant isn't connected yet.",
                    end_session=False,
                )
            )
        if not rate_limiter.allow(user_hash):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        if _normalize_query(query) in _LAST_RESULT_QUERIES:
            answer = _latest_result_response(tasks, user_hash)
            return JSONResponse(
                _alexa_response(answer, end_session=False, reprompt="Anything else?")
            )

        task_id = tasks.create(user_hash)

        async def _announce_if_late(result_text: str) -> None:
            # Only announce work that actually missed the sync budget: a task that finished
            # in time was already spoken live in this same response, and announcing it again
            # would be a confusing duplicate.
            if time.monotonic() - started <= config.sync_budget_seconds:
                return
            await maybe_announce(
                enabled=config.proactive_announce_enabled,
                ha_url=config.home_assistant_url,
                ha_token=config.home_assistant_token,
                notify_service=config.alexa_notify_service,
                dnd_entity=config.alexa_dnd_entity,
                result_text=result_text,
                timeout_seconds=config.home_assistant_timeout_seconds,
                transport=announce_transport,
            )

        async def run_task() -> str:
            try:
                answer = await client.ask(query, user_hash, correlation_id)
            except Exception as exc:
                tasks.fail(task_id, type(exc).__name__)
                await _announce_if_late(
                    "Your last Cipher task failed. Ask me for details."
                )
                raise
            tasks.complete(task_id, answer)
            await _announce_if_late(answer)
            return answer

        running = asyncio.create_task(run_task(), name=f"cipher-alexa-{task_id}")
        app.state.background_tasks.add(running)
        running.add_done_callback(app.state.background_tasks.discard)
        try:
            answer = await asyncio.wait_for(
                asyncio.shield(running), timeout=config.sync_budget_seconds
            )
            status = "completed"
            speech, reprompt = answer, "Anything else?"
        except TimeoutError:
            status = "pending"
            speech = "I'm still working on that. Ask me for the result in a moment."
            reprompt = None
        except Exception:
            status = "failed"
            speech = "I couldn't reach Cipher safely. Please try again in a moment."
            reprompt = None
        LOGGER.info(
            "request completed",
            extra={
                "request_id": correlation_id,
                "channel": "alexa",
                "operation": "openclaw_response",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "status": status,
            },
        )
        return JSONResponse(_alexa_response(speech, end_session=False, reprompt=reprompt))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = BridgeSettings.from_env()
    settings.validate(require_secrets=True)
    uvicorn.run("alexa_bridge.app:app", host=settings.host, port=settings.port, proxy_headers=False)


if __name__ == "__main__":
    main()
