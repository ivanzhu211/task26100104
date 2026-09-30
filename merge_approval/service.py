"""批准后合并的执行服务。"""

from __future__ import annotations

from typing import Callable, List, Optional

from . import gitops
from .models import (
    PHASE_ADVANCED,
    PHASE_ADVANCING,
    PHASE_REGISTERED,
    STATUS_APPROVED,
    STATUS_CONFLICT,
    STATUS_MERGED,
    TERMINAL_STATUSES,
    MergeRequest,
    MergeResult,
)
from .store import ExecutionStore


class MergeService:
    """接收已批准的合并请求并执行快进合并。

    执行记录保存在 SQLite，分支推进通过 git update-ref 的
    compare-and-swap 语义完成，保证只在分支仍指向预期旧提交时
    推进到获批新提交。
    """

    def __init__(
        self,
        db_path: str,
        after_advance_hook: Optional[Callable[[], None]] = None,
    ) -> None:
        self._store = ExecutionStore(db_path)
        # 测试钩子：在本请求实际推进分支、阶段标记落库之后、
        # 终态结果落库之前调用，用于模拟中断。
        self._after_advance_hook = after_advance_hook

    def submit(self, request: MergeRequest) -> MergeResult:
        """接收已批准的合并请求（接收即授权执行），幂等。"""
        if self._store.get(request.request_id) is None:
            self._validate(request)
        result = self._store.register(request)
        return self._execute(result)

    def get_result(self, request_id: str) -> Optional[MergeResult]:
        """查询请求结果。"""
        return self._store.get(request_id)

    def resume(self, request_id: Optional[str] = None) -> List[MergeResult]:
        """恢复处理已登记但未完成的请求。"""
        if request_id is not None:
            result = self._store.get(request_id)
            targets = [result] if result is not None else []
        else:
            targets = self._store.list_unfinished()
        return [self._execute(t) for t in targets]

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "MergeService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _validate(request: MergeRequest) -> None:
        if gitops.resolve_ref(request.repo_path, request.target_branch) is None:
            raise ValueError(
                f"target branch {request.target_branch!r} not found in {request.repo_path}"
            )
        for commit in (request.expected_old_commit, request.approved_new_commit):
            if not gitops.commit_exists(request.repo_path, commit):
                raise ValueError(f"commit {commit} not found in {request.repo_path}")
        if request.expected_old_commit == request.approved_new_commit:
            raise ValueError("expected old commit must differ from approved new commit")
        if not gitops.is_ancestor(
            request.repo_path, request.expected_old_commit, request.approved_new_commit
        ):
            raise ValueError("expected old commit must be a strict ancestor of approved new commit")

    def _execute(self, result: MergeResult) -> MergeResult:
        if result.status in TERMINAL_STATUSES:
            return result
        request_id = result.request_id
        phase = self._store.get_phase(request_id)

        if phase == PHASE_REGISTERED:
            current = gitops.resolve_ref(result.repo_path, result.target_branch)
            if current != result.expected_old_commit:
                self._store.finish(
                    request_id,
                    STATUS_CONFLICT,
                    f"target branch is at {current}, expected {result.expected_old_commit}",
                )
                return self._store.get(request_id)
            self._store.set_phase(request_id, PHASE_ADVANCING)
            phase = PHASE_ADVANCING

        if phase == PHASE_ADVANCING:
            phase = self._advance(result)
            if phase != PHASE_ADVANCED:
                return self._store.get(request_id)

        if phase == PHASE_ADVANCED:
            # 本请求已实际推进过分支，无论分支此后被谁移动，
            # 都认定为 Merged 且不再触碰分支。
            self._store.finish(request_id, STATUS_MERGED, "branch advanced by this request")
        return self._store.get(request_id)

    def _advance(self, result: MergeResult) -> str:
        """处理 advancing 阶段，返回推进后的阶段标记。"""
        request_id = result.request_id
        repo = result.repo_path
        branch = result.target_branch
        old = result.expected_old_commit
        new = result.approved_new_commit

        current = gitops.resolve_ref(repo, branch)
        if current == old:
            if not gitops.compare_and_swap_ref(repo, branch, new, old):
                current = gitops.resolve_ref(repo, branch)
                self._store.finish(
                    request_id,
                    STATUS_CONFLICT,
                    f"target branch moved to {current} before advance",
                )
                return self._store.get_phase(request_id)
            self._store.set_phase(request_id, PHASE_ADVANCED)
            if self._after_advance_hook is not None:
                self._after_advance_hook()
        elif current == new or (current is not None and gitops.is_ancestor(repo, new, current)):
            # 恢复场景：中断发生在 update-ref 成功之后、阶段落库之前，
            # 或本请求推进后分支又被他人前移。认定本请求已完成推进。
            self._store.set_phase(request_id, PHASE_ADVANCED)
        else:
            self._store.finish(
                request_id,
                STATUS_CONFLICT,
                f"target branch is at {current}, expected {old}",
            )
        return self._store.get_phase(request_id)
