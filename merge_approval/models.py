"""数据模型与状态定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


STATUS_APPROVED = "Approved"
STATUS_MERGED = "Merged"
STATUS_CONFLICT = "Conflict"

TERMINAL_STATUSES = (STATUS_MERGED, STATUS_CONFLICT)

# 执行阶段（用于崩溃恢复的内部日志标记）
PHASE_REGISTERED = "registered"   # 已登记，尚未尝试推进分支
PHASE_ADVANCING = "advancing"     # 已校验分支位置，即将/正在推进
PHASE_ADVANCED = "advanced"       # 本请求已实际推进分支（结果尚未落库）


@dataclass(frozen=True)
class MergeRequest:
    """已批准的合并请求。"""

    request_id: str
    repo_path: str
    target_branch: str
    expected_old_commit: str
    approved_new_commit: str


@dataclass(frozen=True)
class MergeResult:
    """请求的执行结果记录。"""

    request_id: str
    repo_path: str
    target_branch: str
    expected_old_commit: str
    approved_new_commit: str
    status: str
    detail: Optional[str] = None
