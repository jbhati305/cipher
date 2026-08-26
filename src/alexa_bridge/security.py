from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path


class AuthenticationError(ValueError):
    pass


class ReplayStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_keys (
                    signature_hash TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    def accept_once(self, signature: str, expires_at: int) -> bool:
        signature_hash = hashlib.sha256(signature.encode("ascii")).hexdigest()
        now = int(time.time())
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM replay_keys WHERE expires_at < ?", (now,))
            try:
                connection.execute(
                    "INSERT INTO replay_keys(signature_hash, expires_at) VALUES (?, ?)",
                    (signature_hash, expires_at),
                )
            except sqlite3.IntegrityError:
                return False
        return True


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and current - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(current)
            return True
