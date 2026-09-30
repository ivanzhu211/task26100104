"""SQLite 执行记录存储。"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from .models import (
    PHASE_REGISTERED,
    STATUS_APPROVED,
    MergeRequest,
    MergeResult,
)


class RequestConflictError(Exception):
    """同一请求标识提交了不同内容。"""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS merge_requests (
    request_id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    target_branch TEXT NOT NULL,
    expected_old_commit TEXT NOT NULL,
    approved_new_commit TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class ExecutionStore:
    """合并请求的持久化记录（SQLite）。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def register(self, request: MergeRequest) -> MergeResult:
        """登记请求；同标识同内容复用原记录，同标识不同内容抛错。"""
        existing = self.get(request.request_id)
        if existing is not None:
            same = (
                existing.repo_path == request.repo_path
                and existing.target_branch == request.target_branch
                and existing.expected_old_commit == request.expected_old_commit
                and existing.approved_new_commit == request.approved_new_commit
            )
            if not same:
                raise RequestConflictError(
                    f"request {request.request_id!r} already registered with different content"
                )
            return existing
        self._conn.execute(
            "INSERT INTO merge_requests "
            "(request_id, repo_path, target_branch, expected_old_commit, "
            " approved_new_commit, status, phase) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request.request_id,
                request.repo_path,
                request.target_branch,
                request.expected_old_commit,
                request.approved_new_commit,
                STATUS_APPROVED,
                PHASE_REGISTERED,
            ),
        )
        self._conn.commit()
        return self.get(request.request_id)

    def get(self, request_id: str) -> Optional[MergeResult]:
        """按标识查询请求结果。"""
        row = self._conn.execute(
            "SELECT * FROM merge_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return self._to_result(row) if row else None

    def list_unfinished(self) -> List[MergeResult]:
        """列出所有仍处于 Approved 状态的请求。"""
        rows = self._conn.execute(
            "SELECT * FROM merge_requests WHERE status = ? ORDER BY created_at, request_id",
            (STATUS_APPROVED,),
        ).fetchall()
        return [self._to_result(r) for r in rows]

    def get_phase(self, request_id: str) -> Optional[str]:
        """读取请求当前的执行阶段标记。"""
        row = self._conn.execute(
            "SELECT phase FROM merge_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return row["phase"] if row else None

    def set_phase(self, request_id: str, phase: str) -> None:
        """推进执行阶段标记并立即落库。"""
        self._conn.execute(
            "UPDATE merge_requests SET phase = ?, updated_at = datetime('now') "
            "WHERE request_id = ?",
            (phase, request_id),
        )
        self._conn.commit()

    def finish(self, request_id: str, status: str, detail: Optional[str] = None) -> None:
        """写入终态结果（Merged/Conflict）并立即落库。"""
        self._conn.execute(
            "UPDATE merge_requests SET status = ?, detail = ?, "
            "updated_at = datetime('now') WHERE request_id = ? AND status = ?",
            (status, detail, request_id, STATUS_APPROVED),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _to_result(row: sqlite3.Row) -> MergeResult:
        return MergeResult(
            request_id=row["request_id"],
            repo_path=row["repo_path"],
            target_branch=row["target_branch"],
            expected_old_commit=row["expected_old_commit"],
            approved_new_commit=row["approved_new_commit"],
            status=row["status"],
            detail=row["detail"],
        )
