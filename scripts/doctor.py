#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
results: list[tuple[str, str, str]] = []


def result(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


def command(*args: str, timeout: int = 10) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - callers provide fixed operator commands
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def check_base() -> None:
    if platform.system() == "Linux":
        result("PASS", "OS supported", platform.platform())
    else:
        result("FAIL", "OS supported", "Cipher targets Linux/Ubuntu")
    if sys.version_info >= (3, 11):  # noqa: UP036 - doctor diagnoses pre-project Pythons
        result("PASS", "Python", platform.python_version())
    else:
        result("FAIL", "Python", f"{platform.python_version()} is too old; Python 3.11+ required")
    missing = [
        name
        for name in ("fastapi", "httpx", "mcp", "psutil", "yaml")
        if not importlib.util.find_spec(name)
    ]
    if missing:
        result("FAIL", "Python dependencies", f"missing: {', '.join(missing)}; run ./cipher setup")
    else:
        result("PASS", "Python dependencies", "installed")
    if shutil.which("openclaw"):
        version = command("openclaw", "--version")
        result("PASS", "OpenClaw installed", (version.stdout if version else "installed").strip())
    else:
        result("FAIL", "OpenClaw installed", "run ./cipher setup")


def check_openclaw() -> None:
    agent_id = os.getenv("OPENCLAW_AGENT_ID", "cipher")
    status = command("openclaw", "status")
    if status and status.returncode == 0:
        result("PASS", "OpenClaw Gateway", "running")
    else:
        result("SETUP", "OpenClaw Gateway", "run ./cipher up; inspect ./cipher logs")
    agents = command("openclaw", "agents", "list")
    agent_pattern = rf"(^|\s){re.escape(agent_id)}(\s|$)"
    if agents and re.search(agent_pattern, agents.stdout, re.IGNORECASE | re.MULTILINE):
        result("PASS", "Cipher agent", f"{agent_id} is registered")
    else:
        result("SETUP", "Cipher agent", "run ./cipher configure")
    plugins = command("openclaw", "plugins", "list")
    plugin_text = (
        (plugins.stdout if plugins else "") + (plugins.stderr if plugins else "")
    ).lower()
    if "codex" in plugin_text:
        result("PASS", "Codex harness", "plugin present; guardian mode is repository policy")
    else:
        result("SETUP", "Codex harness", "run ./cipher configure")
    mcp = command("openclaw", "mcp", "doctor", "cipher-tools", "--probe", timeout=20)
    if mcp and mcp.returncode == 0:
        result("PASS", "Cipher MCP server", "live probe succeeded")
    else:
        result("SETUP", "Cipher MCP server", "run ./cipher configure; test scripts/run-mcp.sh")
    expected_runtime = os.getenv("CIPHER_PRIMARY_RUNTIME", "codex")
    # OpenClaw keys agents by array index (agents.list[N].models), not by id
    # map, so the agent's index has to be resolved before reading its models.
    agent_list = command("openclaw", "agents", "list", "--json")
    runtime_config: dict = {}
    live_primary_model = None
    try:
        agents_config = (
            json.loads(agent_list.stdout) if agent_list and agent_list.returncode == 0 else []
        )
        agent_index = next(
            (i for i, entry in enumerate(agents_config) if entry.get("id") == agent_id), None
        )
        if agent_index is not None:
            # Live source of truth for which model is actually primary right
            # now - deliberately not CIPHER_PRIMARY_MODEL from .env, which can
            # drift from the live agent config (e.g. someone runs `openclaw
            # config set agents.list[N].model` directly). Falling back to the
            # env var only when the live value is unavailable keeps the check
            # honest about what OpenClaw will really route to.
            live_primary_model = agents_config[agent_index].get("model")
            models_path = f"agents.list[{agent_index}].models"
            runtime = command("openclaw", "config", "get", models_path, "--json")
            runtime_config = (
                json.loads(runtime.stdout) if runtime and runtime.returncode == 0 else {}
            )
    except (AttributeError, json.JSONDecodeError, StopIteration):
        runtime_config = {}
        live_primary_model = None
    # This wildcard mapping is what the delegated Codex specialist session runs
    # under, not the primary model (see the next check). It stays named around
    # "openai/*" -> CIPHER_PRIMARY_RUNTIME because that is genuinely what it
    # tests: is the Codex harness reachable at all for openai/* models.
    wildcard_runtime_id = runtime_config.get("openai/*", {}).get("agentRuntime", {}).get("id")
    if wildcard_runtime_id == expected_runtime:
        result(
            "PASS",
            "Codex harness runtime",
            f"openai/* is explicit and agent-scoped ({expected_runtime})",
        )
    else:
        result("SETUP", "Codex harness runtime", "run ./cipher configure")
    # Security-critical, separate from the check above: the PRIMARY model must
    # carry its own explicit agentRuntime.id="openclaw" override so it runs on
    # OpenClaw's embedded runtime, where tools.allow/tools.deny are enforced.
    # Codex's own app-server harness exposes native tools (e.g. bash) that
    # bypass tools.deny entirely (group:fs/group:runtime only cover OpenClaw's
    # generic tool names) - confirmed live: /etc/passwd was readable through it
    # before this override existed. An *empty* models[<id>] override is NOT
    # enough; it must be the explicit string "openclaw" (see
    # docs/ARCHITECTURE.md's decision record and commit a2db3f4). This does
    # NOT cover the standing `cipher-specialist-codex` session, which is
    # intentionally still on the real Codex runtime and still has this gap -
    # that is a known, accepted, open risk, not something this check can pass.
    primary_model = live_primary_model or os.getenv("CIPHER_PRIMARY_MODEL", "")
    # An EMPTY primary model is not a safe "not yet configured" state - it is
    # the shipped .env.example default, and scripts/configure-openclaw.sh's
    # security override only fires for a non-empty openai/* id, so an empty
    # primary model leaves OpenClaw/Codex's own discovery to pick some
    # openai/* model, which then matches the openai/* -> CIPHER_PRIMARY_RUNTIME
    # wildcard mapping checked above. When that wildcard is "codex" (the
    # script's own default), this is the exact bash-tool-bypass vulnerability
    # commit a2db3f4 fixed - so this must FAIL, not SETUP, same as an
    # explicit-but-wrong override. A primary model that isn't openai/* at all
    # (e.g. a future local/non-OpenAI model) never matches this wildcard and
    # was never exposed to this specific Codex-harness issue, so it stays
    # non-failing.
    matches_openai_wildcard = primary_model == "" or primary_model.startswith("openai/")
    if not matches_openai_wildcard:
        result(
            "SETUP",
            "Primary model runtime (security)",
            f"{primary_model} is not an openai/* model; the Codex-harness-bypass "
            "check does not apply to it",
        )
    else:
        if primary_model:
            # Explicit model: its own models[<id>] override wins if present,
            # otherwise it falls through to the openai/* wildcard mapping.
            primary_runtime_id = (
                runtime_config.get(primary_model, {}).get("agentRuntime", {}).get("id")
                or wildcard_runtime_id
            )
            label = primary_model
        else:
            # Empty CIPHER_PRIMARY_MODEL: discovery picks some openai/* model,
            # which is governed entirely by the wildcard mapping above.
            primary_runtime_id = wildcard_runtime_id
            label = "(empty CIPHER_PRIMARY_MODEL; openai/* discovery applies)"
        if primary_runtime_id == "openclaw":
            result(
                "PASS",
                "Primary model runtime (security)",
                f"{label} is pinned to the embedded openclaw runtime",
            )
        else:
            result(
                "FAIL",
                "Primary model runtime (security)",
                f"{label} lacks an explicit agentRuntime.id=openclaw override; "
                "it may be exposed to Codex-native tools bypassing tools.deny - "
                "set a non-empty CIPHER_PRIMARY_MODEL and run ./cipher configure",
            )
    auth = command("openclaw", "models", "status", "--agent", agent_id, "--json")
    auth_text = ((auth.stdout if auth else "") + (auth.stderr if auth else "")).lower()
    if auth and auth.returncode == 0 and "openai" in auth_text:
        result("PASS", "Codex authentication", "OpenAI profile detected")
    else:
        result("SETUP", "Codex authentication", "run ./cipher auth codex")


def check_claude() -> None:
    if not shutil.which("claude"):
        result("OPTIONAL", "Claude Code", "not installed; run ./cipher auth claude")
        return
    auth = command("claude", "auth", "status", "--text")
    if auth and auth.returncode == 0:
        result("PASS", "Claude authentication", "authenticated")
    else:
        result("SETUP", "Claude authentication", "run ./cipher auth claude")
    acp = command("openclaw", "acp", "doctor", timeout=30)
    if acp and acp.returncode == 0:
        result("PASS", "Claude ACP", "acpx probe succeeded")
    else:
        result("OPTIONAL", "Claude ACP", "run /acp doctor in OpenClaw after Claude auth")


def url_check(url: str, token: str | None = None) -> tuple[int | None, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        request = urllib.request.Request(url, headers=headers)  # noqa: S310
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            return response.status, response.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError):
        return None, ""


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_integrations() -> None:
    ha_token = os.getenv("HOME_ASSISTANT_TOKEN", "")
    ha_url = os.getenv("HOME_ASSISTANT_URL", "http://127.0.0.1:8123").rstrip("/")
    if not ha_token:
        result("SETUP", "Home Assistant", "set HOME_ASSISTANT_TOKEN in .env")
    else:
        status, _ = url_check(f"{ha_url}/api/", ha_token)
        if status == 200:
            result("PASS", "Home Assistant", "API and token are valid")
        elif status == 401:
            result("FAIL", "Home Assistant", "configured token was rejected")
        else:
            result("SETUP", "Home Assistant", "API is unreachable")
    bridge_port = os.getenv("ALEXA_BRIDGE_PORT", "8787")
    status, _ = url_check(f"http://127.0.0.1:{bridge_port}/readyz")
    if status == 200:
        result("PASS", "Alexa Bridge", "ready on loopback")
    elif status == 503:
        result("SETUP", "Alexa Bridge", "running but required secrets are missing")
    else:
        result("SETUP", "Alexa Bridge", "run ./cipher up")
    if shutil.which("tailscale"):
        funnel = command("tailscale", "funnel", "status")
        if funnel and funnel.returncode == 0 and bridge_port in funnel.stdout:
            result("PASS", "Alexa ingress", "Tailscale Funnel is serving the bridge port")
        else:
            result("SETUP", "Alexa ingress", f"run: sudo tailscale funnel {bridge_port}")
    else:
        result("SETUP", "Alexa ingress", "install Tailscale; see docs/ALEXA.md")
    base = urlparse(os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789"))
    if is_loopback_host(base.hostname):
        result("PASS", "Gateway exposure", "configured for loopback only")
    else:
        result("FAIL", "Gateway exposure", "OPENCLAW_BASE_URL is not loopback")
    gateway_bind = command("openclaw", "config", "get", "gateway.bind")
    if gateway_bind and gateway_bind.returncode == 0:
        bind = gateway_bind.stdout.strip().strip('"').lower()
        if bind == "loopback":
            result("PASS", "Gateway binding", "OpenClaw binds to loopback")
        else:
            result("FAIL", "Gateway binding", f"OpenClaw gateway.bind is {bind or 'unset'}")
    else:
        result("SETUP", "Gateway binding", "run ./cipher configure")

def main() -> int:
    component = sys.argv[1] if len(sys.argv) > 1 else None
    check_base()
    if shutil.which("openclaw"):
        check_openclaw()
    if component in (None, "claude"):
        check_claude()
    if component is None:
        check_integrations()
    widths = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        print(f"{status:<8} {name:<{widths}}  {detail}")
    return 1 if any(status == "FAIL" for status, _, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
