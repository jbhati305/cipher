from __future__ import annotations

from pathlib import Path

import pytest

from cipher_mcp.config import RuntimeConfig


@pytest.fixture
def runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        command_timeout_seconds=1,
        docker_binary="docker",
        systemctl_binary="systemctl",
        max_log_lines=200,
        docker_readable=frozenset({"jellyfin", "homeassistant"}),
        docker_controllable=frozenset({"jellyfin"}),
        service_readable=frozenset({"ssh", "docker"}),
        service_controllable=frozenset({"safe-service"}),
        ha_read_domains=frozenset({"sensor", "binary_sensor", "light", "switch"}),
        ha_control_entities=frozenset({"light.office", "switch.desk"}),
        ha_control_services={
            "light": frozenset({"turn_on", "turn_off"}),
            "switch": frozenset({"turn_on", "turn_off"}),
        },
        ha_deny_domains=frozenset({"lock", "alarm_control_panel", "cover"}),
        ha_url="http://homeassistant.local:8123",
        ha_token="test-token",
        ha_timeout_seconds=1,
        require_confirmation=True,
        confirmation_ttl_seconds=120,
    )
