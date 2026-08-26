from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError


class ConfirmationError(ToolError, ValueError):
    pass


class ConfirmationStore:
    def __init__(self, path: Path, ttl_seconds: int = 120) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmations (
                    token_hash TEXT PRIMARY KEY,
                    requester_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                )
                """
            )

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create(
        self, requester_id: str, action: str, target: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if not requester_id or len(requester_id) > 256:
            raise ConfirmationError("a valid requester_id is required")
        token = secrets.token_urlsafe(24)
        expires_at = int(time.time()) + self.ttl_seconds
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM confirmations WHERE expires_at < ?", (int(time.time()),)
            )
            connection.execute(
                """
                INSERT INTO confirmations
                (token_hash, requester_hash, action, target, arguments_json, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self._hash(token),
                    self._hash(requester_id),
                    action,
                    target,
                    json.dumps(arguments, sort_keys=True, separators=(",", ":")),
                    expires_at,
                ),
            )
        return {
            "confirmation_required": True,
            "confirmation_token": token,
            "action": action,
            "target": target,
            "expires_at": expires_at,
        }

    def consume(self, token: str, requester_id: str, action: str, target: str) -> dict[str, Any]:
        now = int(time.time())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT requester_hash, action, target, arguments_json, expires_at, used_at
                FROM confirmations WHERE token_hash = ?
                """,
                (self._hash(token),),
            ).fetchone()
            if row is None:
                raise ConfirmationError("confirmation is invalid")
            requester_hash, stored_action, stored_target, arguments_json, expires_at, used_at = row
            if used_at is not None:
                raise ConfirmationError("confirmation has already been used")
            if expires_at < now:
                raise ConfirmationError("confirmation has expired")
            if requester_hash != self._hash(requester_id):
                raise ConfirmationError("confirmation belongs to a different requester")
            if stored_action != action or stored_target != target:
                raise ConfirmationError("confirmation does not match this exact action")
            connection.execute(
                "UPDATE confirmations SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (now, self._hash(token)),
            )
        return json.loads(arguments_json)
