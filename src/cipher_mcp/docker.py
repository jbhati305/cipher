from __future__ import annotations

import json
from typing import Any

from .config import RuntimeConfig
from .policy import require_allowed
from .runner import CommandRunner


class DockerTools:
    def __init__(self, config: RuntimeConfig, runner: CommandRunner | None = None) -> None:
        self.config = config
        self.runner = runner or CommandRunner(config.command_timeout_seconds)

    def list_containers(self) -> dict[str, Any]:
        allowed = self.config.docker_readable | self.config.docker_controllable
        if not allowed:
            return {"containers": []}
        result = self.runner.run([self.config.docker_binary, "ps", "-a", "--format", "{{json .}}"])
        containers = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            item = json.loads(line)
            name = item.get("Names")
            if name in allowed:
                containers.append(
                    {
                        "name": name,
                        "state": item.get("State"),
                        "status": item.get("Status"),
                        "image": item.get("Image"),
                    }
                )
        return {"containers": containers}

    def status(self, name: str) -> dict[str, Any]:
        require_allowed(
            name,
            self.config.docker_readable | self.config.docker_controllable,
            "container",
            "read",
        )
        result = self.runner.run([self.config.docker_binary, "inspect", name])
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("Docker returned an invalid inspect response")
        data = payload[0]
        state = data.get("State", {})
        health = state.get("Health", {})
        stats = self._stats(name)
        return {
            "name": name,
            "running": bool(state.get("Running")),
            "status": state.get("Status"),
            "health": health.get("Status", "unavailable"),
            "started_at": state.get("StartedAt"),
            "restart_count": data.get("RestartCount"),
            "memory_usage": stats,
        }

    def logs(self, name: str, lines: int = 100) -> dict[str, Any]:
        require_allowed(
            name,
            self.config.docker_readable | self.config.docker_controllable,
            "container",
            "read logs from",
        )
        if not isinstance(lines, int) or lines < 1 or lines > self.config.max_log_lines:
            raise ValueError(f"lines must be between 1 and {self.config.max_log_lines}")
        result = self.runner.run(
            [self.config.docker_binary, "logs", "--tail", str(lines), name], check=False
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout)[:500])
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return {"name": name, "requested_lines": lines, "logs": combined}

    def mutate(self, action: str, name: str) -> dict[str, Any]:
        if action not in {"restart", "start", "stop"}:
            raise ValueError("unsupported container action")
        require_allowed(name, self.config.docker_controllable, "container", action)
        self.runner.run([self.config.docker_binary, action, name])
        return {"ok": True, "action": action, "name": name, "status": self.status(name)}

    def _stats(self, name: str) -> dict[str, Any] | None:
        result = self.runner.run(
            [
                self.config.docker_binary,
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                name,
            ],
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        try:
            item = json.loads(result.stdout.splitlines()[0])
        except (json.JSONDecodeError, IndexError):
            return None
        return {"memory": item.get("MemUsage"), "memory_percent": item.get("MemPerc")}
