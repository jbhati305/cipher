from __future__ import annotations

import time

import pytest

from cipher_mcp.confirmations import ConfirmationError, ConfirmationStore


def test_confirmation_is_requester_action_target_bound_and_one_time(tmp_path):
    store = ConfirmationStore(tmp_path / "confirm.sqlite3", ttl_seconds=30)
    pending = store.create("alice", "docker.restart", "jellyfin", {"reason": "unhealthy"})
    token = pending["confirmation_token"]
    with pytest.raises(ConfirmationError, match="different requester"):
        store.consume(token, "bob", "docker.restart", "jellyfin")
    with pytest.raises(ConfirmationError, match="exact action"):
        store.consume(token, "alice", "docker.stop", "jellyfin")
    assert store.consume(token, "alice", "docker.restart", "jellyfin") == {"reason": "unhealthy"}
    with pytest.raises(ConfirmationError, match="already been used"):
        store.consume(token, "alice", "docker.restart", "jellyfin")


def test_expired_confirmation_is_rejected(tmp_path, monkeypatch):
    store = ConfirmationStore(tmp_path / "confirm.sqlite3", ttl_seconds=1)
    pending = store.create("alice", "service.restart", "safe-service", {})
    monkeypatch.setattr(time, "time", lambda: pending["expires_at"] + 1)
    with pytest.raises(ConfirmationError, match="expired"):
        store.consume(pending["confirmation_token"], "alice", "service.restart", "safe-service")
