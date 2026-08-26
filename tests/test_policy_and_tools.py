from __future__ import annotations

import json
import os

import pytest

from cipher_mcp.docker import DockerTools
from cipher_mcp.policy import PolicyDenied
from cipher_mcp.runner import CommandResult, CommandRunner
from cipher_mcp.services import ServiceTools


class FakeRunner:
    def __init__(self, responses: list[CommandResult] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[list[str]] = []

    def run(self, argv, *, check=True):  # noqa: ANN001, ANN201
        self.calls.append(list(argv))
        if self.responses:
            return self.responses.pop(0)
        return CommandResult("", "", 0)


@pytest.mark.parametrize("value", ["jellyfin; rm -rf /", "../../etc/passwd", "$(reboot)"])
def test_container_injection_is_rejected_before_execution(runtime_config, value):
    runner = FakeRunner()
    tools = DockerTools(runtime_config, runner)
    with pytest.raises(PolicyDenied):
        tools.mutate("restart", value)
    assert runner.calls == []


def test_allowlisted_container_uses_fixed_argv(runtime_config):
    inspect = {
        "State": {"Running": True, "Status": "running", "StartedAt": "now"},
        "RestartCount": 0,
    }
    runner = FakeRunner(
        [
            CommandResult(json.dumps([inspect]), "", 0),
            CommandResult('{"MemUsage":"1MiB / 1GiB","MemPerc":"0.1%"}', "", 0),
        ]
    )
    result = DockerTools(runtime_config, runner).status("jellyfin")
    assert result["running"] is True
    assert runner.calls[0] == ["docker", "inspect", "jellyfin"]
    assert runner.calls[1][-1] == "jellyfin"


def test_unknown_container_rejected_for_mutation(runtime_config):
    runner = FakeRunner()
    with pytest.raises(PolicyDenied, match="not allowed"):
        DockerTools(runtime_config, runner).mutate("restart", "unknown")
    assert not runner.calls


@pytest.mark.parametrize("value", ["ssh;reboot", "../../etc/passwd", "$(reboot)"])
def test_arbitrary_service_rejected(runtime_config, value):
    runner = FakeRunner()
    with pytest.raises(PolicyDenied):
        ServiceTools(runtime_config, runner).status(value)
    assert not runner.calls


def test_allowlisted_service_uses_exact_systemctl_argv(runtime_config):
    runner = FakeRunner(
        [
            CommandResult(
                "Id=ssh.service\nLoadState=loaded\nActiveState=active\nSubState=running", "", 0
            )
        ]
    )
    result = ServiceTools(runtime_config, runner).status("ssh")
    assert result["active"] == "active"
    assert runner.calls == [
        [
            "systemctl",
            "show",
            "ssh",
            "--no-page",
            "--property=Id,LoadState,ActiveState,SubState,UnitFileState",
        ]
    ]


def test_command_runner_does_not_forward_application_secrets(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return type("Completed", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "must-not-leak")
    monkeypatch.setenv("ALEXA_ID_HMAC_SECRET", "must-not-leak")
    monkeypatch.setattr("cipher_mcp.runner.subprocess.run", fake_run)
    CommandRunner().run(["systemctl", "show", "ssh"])
    assert "HOME_ASSISTANT_TOKEN" not in captured["env"]
    assert "ALEXA_ID_HMAC_SECRET" not in captured["env"]
    assert captured["env"].get("PATH") == os.environ.get("PATH")
