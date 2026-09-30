"""数据模型与状态定义。"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class MergeState(enum.Enum):
    """请求状态。Approved 为进行中，Merged/Conflict 为终态。"""

    APPROVED = "Approved"
    MERGED = "Merged"
    CONFLICT = "Conflict"

    @property
    def is_terminal(self) -> bool:
        return self in (MergeState.MERGED, MergeState.CONFLICT)


@dataclass(frozen=True)
class MergeRequest:
    """一次已批准的合并请求。"""

    request_id: str
    repo_path: str
    target_branch: str
    expected_old: str
    approved_new: str


@dataclass(frozen=True)
class MergeResult:
    """请求当前的处理结果。"""

    request_id: str
    state: MergeState
