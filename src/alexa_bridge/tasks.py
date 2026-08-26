from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class TaskStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    requester_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "UPDATE tasks SET status = 'interrupted', updated_at = ? WHERE status = 'running'",
                (int(time.time()),),
            )

    def create(self, requester_hash: str) -> str:
        task_id = str(uuid.uuid4())
        now = int(time.time())
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, requester_hash, status, created_at, updated_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (task_id, requester_hash, now, now),
            )
        return task_id

    def complete(self, task_id: str, result: str) -> None:
        self._update(task_id, "completed", result=result[:8000])

    def fail(self, task_id: str, error: str) -> None:
        self._update(task_id, "failed", error=error[:500])

    def _update(
        self, task_id: str, status: str, result: str | None = None, error: str | None = None
    ) -> None:
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                UPDATE tasks SET status = ?, result = ?, error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status, result, error, int(time.time()), task_id),
            )

    def latest(self, requester_hash: str) -> dict[str, Any] | None:
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT task_id, status, result, error, created_at, updated_at
                FROM tasks WHERE requester_hash = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (requester_hash,),
            ).fetchone()
        return dict(row) if row else None
