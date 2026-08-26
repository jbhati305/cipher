from __future__ import annotations

from cipher_mcp.metrics import ServerMetrics


def test_server_metrics_return_real_bounded_values():
    metrics = ServerMetrics()
    cpu = metrics.cpu()
    memory = metrics.memory()
    disk = metrics.disk_usage()
    uptime = metrics.uptime()
    assert 0 <= cpu["percent"] <= 100
    assert 0 <= memory["percent"] <= 100
    assert 0 <= disk["percent"] <= 100
    assert uptime["seconds"] >= 0


def test_temperature_has_graceful_availability_shape():
    value = ServerMetrics().temperature()
    assert isinstance(value["available"], bool)
    assert isinstance(value["sensors"], list)
