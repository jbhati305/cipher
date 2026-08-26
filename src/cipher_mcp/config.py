from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return data


def _config_path(config_dir: Path, name: str) -> Path:
    configured = config_dir / f"{name}.yaml"
    return configured if configured.exists() else config_dir / f"{name}.example.yaml"


@dataclass(frozen=True)
class RuntimeConfig:
    config_dir: Path
    state_dir: Path
    command_timeout_seconds: float
    docker_binary: str
    systemctl_binary: str
    max_log_lines: int
    docker_readable: frozenset[str]
    docker_controllable: frozenset[str]
    service_readable: frozenset[str]
    service_controllable: frozenset[str]
    ha_read_domains: frozenset[str]
    ha_control_entities: frozenset[str]
    ha_control_services: dict[str, frozenset[str]]
    ha_deny_domains: frozenset[str]
    ha_url: str
    ha_token: str
    ha_timeout_seconds: float
    require_confirmation: bool
    confirmation_ttl_seconds: int

    @classmethod
    def load(cls, config_dir: Path | None = None) -> RuntimeConfig:
        root = config_dir or Path(os.getenv("CIPHER_CONFIG_DIR", "config"))
        root = root.resolve()
        core = _load_yaml(_config_path(root, "cipher"))
        docker = _load_yaml(_config_path(root, "docker-allowlist")).get("docker", {})
        services = _load_yaml(_config_path(root, "services-allowlist")).get("services", {})
        ha = _load_yaml(_config_path(root, "home-assistant-allowlist"))
        server = core.get("server", {})
        dangerous = core.get("dangerous_operations", {})
        raw_service_map = ha.get("control", {}).get("services", {})
        service_map = {
            str(domain): frozenset(str(item) for item in actions)
            for domain, actions in raw_service_map.items()
            if isinstance(actions, list)
        }
        return cls(
            config_dir=root,
            state_dir=Path(os.getenv("CIPHER_STATE_DIR", "state")).resolve(),
            command_timeout_seconds=float(server.get("command_timeout_seconds", 8)),
            docker_binary=str(server.get("docker_binary", "docker")),
            systemctl_binary=str(server.get("systemctl_binary", "systemctl")),
            max_log_lines=int(server.get("max_log_lines", 500)),
            docker_readable=frozenset(str(x) for x in docker.get("readable", [])),
            docker_controllable=frozenset(str(x) for x in docker.get("controllable", [])),
            service_readable=frozenset(str(x) for x in services.get("readable", [])),
            service_controllable=frozenset(str(x) for x in services.get("controllable", [])),
            ha_read_domains=frozenset(str(x) for x in ha.get("read", {}).get("domains", [])),
            ha_control_entities=frozenset(
                str(x) for x in ha.get("control", {}).get("entities", [])
            ),
            ha_control_services=service_map,
            ha_deny_domains=frozenset(str(x) for x in ha.get("deny", {}).get("domains", [])),
            ha_url=os.getenv("HOME_ASSISTANT_URL", "http://127.0.0.1:8123").rstrip("/"),
            ha_token=os.getenv("HOME_ASSISTANT_TOKEN", ""),
            ha_timeout_seconds=float(os.getenv("HOME_ASSISTANT_TIMEOUT_SECONDS", "5")),
            require_confirmation=bool(dangerous.get("require_confirmation", True)),
            confirmation_ttl_seconds=int(dangerous.get("confirmation_ttl_seconds", 120)),
        )
