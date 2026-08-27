from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_AGENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_valid_bind_host(host: str | None) -> bool:
    # "0.0.0.0" is accepted only for the bridge's own bind address: a container's port publish
    # (see docker-compose.yml) is what actually restricts external exposure to loopback, since a
    # process bound to 127.0.0.1 inside a container is unreachable through Docker's port
    # publishing. This does NOT apply to OPENCLAW_BASE_URL, which must stay strictly loopback.
    if host == "0.0.0.0":  # noqa: S104
        return True
    return _is_loopback_host(host)


@dataclass(frozen=True)
class BridgeSettings:
    id_hmac_secret: str
    skill_id: str
    host: str
    port: int
    max_body_bytes: int
    signature_max_age_seconds: int
    rate_limit_per_minute: int
    sync_budget_seconds: float
    openclaw_timeout_seconds: float
    openclaw_base_url: str
    openclaw_gateway_token: str
    openclaw_agent_id: str
    state_dir: Path
    log_level: str
    verbose_request_logging: bool
    home_assistant_url: str = ""
    home_assistant_token: str = ""
    home_assistant_timeout_seconds: float = 5
    proactive_announce_enabled: bool = True
    alexa_notify_service: str = ""
    alexa_dnd_entity: str = ""

    @classmethod
    def from_env(cls) -> BridgeSettings:
        return cls(
            id_hmac_secret=os.getenv("ALEXA_ID_HMAC_SECRET", ""),
            skill_id=os.getenv("ALEXA_SKILL_ID", ""),
            host=os.getenv("ALEXA_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.getenv("ALEXA_BRIDGE_PORT", "8787")),
            max_body_bytes=int(os.getenv("ALEXA_REQUEST_MAX_BYTES", "16384")),
            signature_max_age_seconds=int(os.getenv("ALEXA_SIGNATURE_MAX_AGE_SECONDS", "150")),
            rate_limit_per_minute=int(os.getenv("ALEXA_RATE_LIMIT_PER_MINUTE", "20")),
            sync_budget_seconds=float(os.getenv("ALEXA_SYNC_BUDGET_SECONDS", "6")),
            openclaw_timeout_seconds=float(os.getenv("ALEXA_OPENCLAW_TIMEOUT_SECONDS", "120")),
            openclaw_base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/"),
            openclaw_gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", ""),
            openclaw_agent_id=os.getenv("OPENCLAW_AGENT_ID", "cipher"),
            state_dir=Path(os.getenv("CIPHER_STATE_DIR", "state")).resolve(),
            log_level=os.getenv("CIPHER_LOG_LEVEL", "INFO"),
            verbose_request_logging=os.getenv("CIPHER_VERBOSE_REQUEST_LOGGING", "false").lower()
            in {"1", "true", "yes"},
            home_assistant_url=os.getenv("HOME_ASSISTANT_URL", "").rstrip("/"),
            home_assistant_token=os.getenv("HOME_ASSISTANT_TOKEN", ""),
            home_assistant_timeout_seconds=float(
                os.getenv("HOME_ASSISTANT_TIMEOUT_SECONDS", "5")
            ),
            proactive_announce_enabled=os.getenv(
                "ALEXA_PROACTIVE_ANNOUNCE_ENABLED", "true"
            ).lower()
            in {"1", "true", "yes"},
            alexa_notify_service=os.getenv("HOME_ASSISTANT_ALEXA_NOTIFY_SERVICE", ""),
            alexa_dnd_entity=os.getenv("HOME_ASSISTANT_ALEXA_DND_ENTITY", ""),
        )

    def validate(self, *, require_secrets: bool = True) -> None:
        if require_secrets and len(self.id_hmac_secret) < 32:
            raise ValueError("ALEXA_ID_HMAC_SECRET must contain at least 32 characters")
        if require_secrets and not self.skill_id:
            raise ValueError("ALEXA_SKILL_ID is required")
        if not (1024 <= self.max_body_bytes <= 1_048_576):
            raise ValueError("ALEXA_REQUEST_MAX_BYTES is outside the safe range")
        if not (1 <= self.port <= 65535):
            raise ValueError("ALEXA_BRIDGE_PORT is invalid")
        if not (1 <= self.signature_max_age_seconds <= 3600):
            raise ValueError("ALEXA_SIGNATURE_MAX_AGE_SECONDS is outside the safe range")
        if not (1 <= self.rate_limit_per_minute <= 10_000):
            raise ValueError("ALEXA_RATE_LIMIT_PER_MINUTE is outside the safe range")
        if not (0 < self.sync_budget_seconds <= self.openclaw_timeout_seconds <= 3600):
            raise ValueError("Alexa/OpenClaw timeouts are invalid")
        if not _AGENT_ID_RE.fullmatch(self.openclaw_agent_id):
            raise ValueError("OPENCLAW_AGENT_ID is invalid")
        if not _is_valid_bind_host(self.host):
            raise ValueError("ALEXA_BRIDGE_HOST must be loopback (or 0.0.0.0 for container use)")
        parsed = urlparse(self.openclaw_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("OPENCLAW_BASE_URL is invalid")
        if not _is_loopback_host(parsed.hostname):
            raise ValueError("OPENCLAW_BASE_URL must use a loopback host")
        if self.home_assistant_url:
            ha_parsed = urlparse(self.home_assistant_url)
            if (
                ha_parsed.scheme not in {"http", "https"}
                or not ha_parsed.hostname
                or ha_parsed.username is not None
                or ha_parsed.password is not None
            ):
                raise ValueError("HOME_ASSISTANT_URL is invalid")
            if not _is_loopback_host(ha_parsed.hostname):
                raise ValueError("HOME_ASSISTANT_URL must use a loopback host")
        if self.alexa_notify_service and "." not in self.alexa_notify_service:
            raise ValueError("HOME_ASSISTANT_ALEXA_NOTIFY_SERVICE must be 'domain.service'")
