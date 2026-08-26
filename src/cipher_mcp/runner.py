from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError


class CommandFailed(ToolError, RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Executes fixed argv vectors without a shell."""

    def __init__(self, timeout_seconds: float = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, argv: Sequence[str], *, check: bool = True) -> CommandResult:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise ValueError("argv must contain non-empty strings")
        try:
            child_env = {
                name: value
                for name in (
                    "DBUS_SESSION_BUS_ADDRESS",
                    "DOCKER_CERT_PATH",
                    "DOCKER_CONFIG",
                    "DOCKER_CONTEXT",
                    "DOCKER_HOST",
                    "DOCKER_TLS_VERIFY",
                    "HOME",
                    "LANG",
                    "LC_ALL",
                    "PATH",
                    "XDG_RUNTIME_DIR",
                )
                if (value := os.environ.get(name)) is not None
            }
            completed = subprocess.run(  # noqa: S603 - argv is fixed and validated by callers
                list(argv),
                capture_output=True,
                check=False,
                env=child_env,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CommandFailed(f"command is not installed: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandFailed(f"command timed out after {self.timeout_seconds:g}s") from exc
        result = CommandResult(
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            returncode=completed.returncode,
        )
        if check and result.returncode != 0:
            detail = result.stderr or result.stdout or f"exit status {result.returncode}"
            raise CommandFailed(detail[:500])
        return result
