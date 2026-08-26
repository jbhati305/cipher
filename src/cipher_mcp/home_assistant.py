from __future__ import annotations

from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import RuntimeConfig
from .policy import PolicyDenied, validate_action, validate_entity_id


class HomeAssistantError(ToolError, RuntimeError):
    pass


class HomeAssistantClient:
    def __init__(self, config: RuntimeConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.config.ha_token:
            raise HomeAssistantError("Home Assistant token is not configured")
        return {
            "Authorization": f"Bearer {self.config.ha_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(
                base_url=self.config.ha_url,
                headers=self._headers(),
                timeout=self.config.ha_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise HomeAssistantError("Home Assistant request timed out") from exc
        except httpx.RequestError as exc:
            raise HomeAssistantError("Home Assistant is unreachable") from exc
        if response.status_code == 401:
            raise HomeAssistantError("Home Assistant rejected the configured token")
        if response.status_code >= 400:
            raise HomeAssistantError(f"Home Assistant returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise HomeAssistantError("Home Assistant returned invalid JSON") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/")

    def get_state(self, entity_id: str) -> dict[str, Any]:
        domain, _ = validate_entity_id(entity_id)
        if domain in self.config.ha_deny_domains or domain not in self.config.ha_read_domains:
            raise PolicyDenied(f"reading Home Assistant domain '{domain}' is not allowed")
        return self._request("GET", f"/api/states/{entity_id}")

    def list_entities(self, domain: str | None = None) -> dict[str, Any]:
        if domain is not None:
            validate_action(domain, "domain")
            if domain in self.config.ha_deny_domains or domain not in self.config.ha_read_domains:
                raise PolicyDenied(f"reading Home Assistant domain '{domain}' is not allowed")
        states = self._request("GET", "/api/states")
        visible = []
        for item in states:
            entity_id = item.get("entity_id", "")
            item_domain = entity_id.partition(".")[0]
            is_readable = item_domain in self.config.ha_read_domains
            is_denied = item_domain in self.config.ha_deny_domains
            if is_readable and not is_denied:
                if domain is None or item_domain == domain:
                    visible.append(item)
        return {"entities": visible}

    def call_service(
        self, domain: str, service: str, entity_id: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        validate_action(domain, "domain")
        validate_action(service, "service")
        entity_domain, _ = validate_entity_id(entity_id)
        if domain != entity_domain:
            raise PolicyDenied("service domain must match the entity domain")
        if domain in self.config.ha_deny_domains:
            raise PolicyDenied(f"Home Assistant domain '{domain}' is denied")
        if entity_id not in self.config.ha_control_entities:
            raise PolicyDenied(f"control is not allowed for entity '{entity_id}'")
        if service not in self.config.ha_control_services.get(domain, frozenset()):
            raise PolicyDenied(f"service '{domain}.{service}' is not allowed")
        payload = dict(data or {})
        payload["entity_id"] = entity_id
        result = self._request("POST", f"/api/services/{domain}/{service}", json=payload)
        return {
            "ok": True,
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "changed_states": result,
        }
