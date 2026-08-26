from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_mock_agent_executes_multiple_typed_tools_and_combines_response():
    calls: list[tuple[str, tuple]] = []

    async def call(name: str, *args):
        calls.append((name, args))
        values = {
            "server_disk_usage": {"percent": 42},
            "docker_container_status": {"running": True},
            "ha_call_service": {"ok": True},
            "web_search": {"summary": "One important AI update."},
        }
        return values[name]

    results = await asyncio.gather(
        call("server_disk_usage"),
        call("docker_container_status", "jellyfin"),
        call("ha_call_service", "light", "turn_off", "light.bedroom"),
        call("web_search", "important AI news today"),
    )
    answer = (
        f"Disk usage is {results[0]['percent']} percent. "
        f"Jellyfin is {'running' if results[1]['running'] else 'stopped'}. "
        f"The bedroom light was {'turned off' if results[2]['ok'] else 'not changed'}. "
        f"{results[3]['summary']}"
    )
    assert [name for name, _ in calls] == [
        "server_disk_usage",
        "docker_container_status",
        "ha_call_service",
        "web_search",
    ]
    assert "Disk usage is 42 percent" in answer
    assert "Jellyfin is running" in answer
    assert "bedroom light was turned off" in answer
