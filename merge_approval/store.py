"""SQLite 执行记录存储。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from merge_approval.models import MergeRequest, MergeResult, MergeState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id    TEXT PRIMARY KEY,
    repo_path     TEXT NOT NULL,
    target_branch TEXT NOT NULL,
    expected_old  TEXT NOT NULL,
    approved_new  TEXT NOT NULL,
    state         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""

_CONTENT_COLUMNS = ("repo_path", "target_branch", "expected_old", "approved_new")


class DuplicateRequestError(ValueError):
    """同一请求标识提交了不同内容。"""


class RecordStore:
    """负责请求登记、状态查询与终态落库。

    终态（Merged/Conflict）不可改变：finalize 只在当前状态为
    Approved 时生效。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_result(row: sqlite3.Row) -> MergeResult:
        return MergeResult(
            request_id=row["request_id"], state=MergeState(row["state"])
        )

    @staticmethod
    def _to_request(row: sqlite3.Row) -> MergeRequest:
        return MergeRequest(
            request_id=row["request_id"],
            repo_path=row["repo_path"],
            target_branch=row["target_branch"],
            expected_old=row["expected_old"],
            approved_new=row["approved_new"],
        )

    def get(self, request_id: str) -> MergeResult | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._to_result(row) if row else None

    def get_request(self, request_id: str) -> MergeRequest | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._to_request(row) if row else None

    def register(self, request: MergeRequest) -> MergeResult:
        """登记新请求；同标识同内容复用原结果，同标识不同内容报错。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?", (request.request_id,)
            ).fetchone()
            if row is not None:
                for col in _CONTENT_COLUMNS:
                    if row[col] != getattr(request, col):
                        raise DuplicateRequestError(
                            f"request {request.request_id!r} already exists "
                            f"with different content"
                        )
                return self._to_result(row)
            now = self._now()
            conn.execute(
                "INSERT INTO requests (request_id, repo_path, target_branch,"
                " expected_old, approved_new, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.request_id,
                    request.repo_path,
                    request.target_branch,
                    request.expected_old,
                    request.approved_new,
                    MergeState.APPROVED.value,
                    now,
                    now,
                ),
            )
        return MergeResult(request.request_id, MergeState.APPROVED)

    def finalize(self, request_id: str, result: MergeResult) -> MergeResult:
        """写入终态；若已是终态则保留原终态并返回实际存储的结果。"""
        if not result.state.is_terminal:
            raise ValueError("finalize requires a terminal state")
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE requests SET state = ?, updated_at = ?"
                " WHERE request_id = ? AND state = ?",
                (
                    result.state.value,
                    self._now(),
                    request_id,
                    MergeState.APPROVED.value,
                ),
            )
            row = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown request {request_id!r}")
        return self._to_result(row)

    def pending_requests(self) -> list[MergeRequest]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE state = ? ORDER BY created_at",
                (MergeState.APPROVED.value,),
            ).fetchall()
        return [self._to_request(row) for row in rows]
