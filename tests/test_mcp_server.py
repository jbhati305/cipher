from __future__ import annotations

import asyncio
import os
import sys

from mcp import Client, StdioServerParameters


def server_parameters(runtime_config) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "cipher_mcp.server"],
        env={
            "CIPHER_CONFIG_DIR": str(runtime_config.config_dir),
            "CIPHER_STATE_DIR": str(runtime_config.state_dir),
            "HOME_ASSISTANT_TOKEN": "test-token",
            "HOME_ASSISTANT_URL": "http://127.0.0.1:9",
            "PATH": os.environ.get("PATH", ""),
        },
    )


def test_mcp_exposes_expected_typed_surface(runtime_config):
    async def list_tools():
        async with Client(server_parameters(runtime_config), read_timeout_seconds=10) as client:
            return (await client.list_tools()).tools

    listed = asyncio.run(list_tools())
    by_name = {tool.name: tool for tool in listed}
    names = set(by_name)
    assert {
        "server_health_summary",
        "server_disk_usage",
        "docker_container_status",
        "docker_restart_container",
        "service_status",
        "service_restart",
        "ha_get_state",
        "ha_call_service",
    } <= names
    assert not {"shell", "exec", "docker_exec", "docker_run"} & names
    assert by_name["server_health_summary"].annotations.read_only_hint is True
    assert by_name["server_health_summary"].annotations.destructive_hint is False
    assert by_name["docker_restart_container"].annotations.destructive_hint is True
    assert by_name["ha_get_state"].annotations.open_world_hint is True


def test_mcp_call_tool_returns_structured_health_summary(runtime_config):
    async def call_tool():
        async with Client(server_parameters(runtime_config), read_timeout_seconds=10) as client:
            return await client.call_tool("server_health_summary", {})

    result = asyncio.run(call_tool())
    assert result.structured_content is not None
    assert result.structured_content["status"] in {"healthy", "warning"}
    assert 0 <= result.structured_content["cpu"]["percent"] <= 100


def test_mcp_call_tool_rejects_non_allowlisted_container(runtime_config):
    async def call_tool():
        async with Client(server_parameters(runtime_config), read_timeout_seconds=10) as client:
            return await client.call_tool("docker_container_status", {"name": "not-allowlisted"})

    result = asyncio.run(call_tool())
    assert result.is_error is True
    assert "not allowed" in result.content[0].text
