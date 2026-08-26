from __future__ import annotations

from typing import Any

from .config import RuntimeConfig
from .policy import require_allowed
from .runner import CommandRunner


class ServiceTools:
    def __init__(self, config: RuntimeConfig, runner: CommandRunner | None = None) -> None:
        self.config = config
        self.runner = runner or CommandRunner(config.command_timeout_seconds)

    def status(self, name: str) -> dict[str, Any]:
        require_allowed(
            name,
            self.config.service_readable | self.config.service_controllable,
            "service",
            "read",
        )
        result = self.runner.run(
            [
                self.config.systemctl_binary,
                "show",
                name,
                "--no-page",
                "--property=Id,LoadState,ActiveState,SubState,UnitFileState",
            ],
            check=False,
        )
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                fields[key] = value
        if result.returncode != 0 or not fields:
            raise RuntimeError((result.stderr or "systemd service was not found")[:500])
        return {
            "name": name,
            "unit": fields.get("Id"),
            "loaded": fields.get("LoadState"),
            "active": fields.get("ActiveState"),
            "sub_state": fields.get("SubState"),
            "enabled": fields.get("UnitFileState"),
        }

    def mutate(self, action: str, name: str) -> dict[str, Any]:
        if action not in {"restart", "start", "stop"}:
            raise ValueError("unsupported service action")
        require_allowed(name, self.config.service_controllable, "service", action)
        self.runner.run([self.config.systemctl_binary, action, name])
        return {"ok": True, "action": action, "name": name, "status": self.status(name)}
