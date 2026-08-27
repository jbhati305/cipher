from __future__ import annotations

from typing import Any

import httpx


class OpenClawError(RuntimeError):
    pass


class OpenClawClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        agent_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self.agent_id = agent_id
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def ask(self, query: str, requester_hash: str, correlation_id: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": self.agent_id,
            # Must be prefixed with "agent:<agentId>:" -- OpenClaw's session-key
            # namespace determines routing. A bare "alexa:<hash>" key (no agent
            # prefix) silently routes the turn to OpenClaw's unrestricted default
            # "main" agent instead of "cipher", regardless of the
            # x-openclaw-agent-id header above. Verified live: this was a real,
            # long-standing bug -- every real Alexa request was reaching "main"
            # (no tools.deny, no cipher-tools__* MCP registration) rather than
            # the security-hardened "cipher" agent this project is built around.
            "x-openclaw-session-key": f"agent:{self.agent_id}:alexa:{requester_hash}",
            "x-openclaw-message-channel": "alexa",
            "x-cipher-correlation-id": correlation_id,
        }
        payload = {
            "model": f"openclaw/{self.agent_id}",
            "input": query,
            "instructions": (
                "Trusted channel metadata: for requester-bound Cipher MCP confirmation tools, "
                f"use requester_id 'alexa:{requester_hash}'. Never speak or expose this value."
            ),
            "user": f"alexa:{requester_hash}",
            "max_output_tokens": 500,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post("/v1/responses", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise OpenClawError("OpenClaw timed out") from exc
        except httpx.RequestError as exc:
            raise OpenClawError("OpenClaw is unreachable") from exc
        if response.status_code == 401:
            raise OpenClawError("OpenClaw authentication failed")
        if response.status_code >= 400:
            raise OpenClawError(f"OpenClaw returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise OpenClawError("OpenClaw returned invalid JSON") from exc
        answer = extract_output_text(data)
        if not answer:
            raise OpenClawError("OpenClaw returned no spoken answer")
        return answer


def extract_output_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text.strip())
    return " ".join(part for part in parts if part).strip()
