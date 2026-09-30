"""对外服务：接收、查询、恢复合并请求。"""
from __future__ import annotations

from merge_approval.gitops import GitOps
from merge_approval.models import MergeRequest, MergeResult, MergeState
from merge_approval.store import RecordStore


class MergeService:
    """批准后合并的执行入口，由上层调用。

    接收即授权执行；执行记录保存在 SQLite，分支推进通过
    裸仓库上的原子引用事务完成。进程在任意点中断后，可用
    resume/resume_all 继续处理已登记但未完成的请求。
    """

    def __init__(self, db_path: str) -> None:
        self._store = RecordStore(db_path)

    def submit(self, request: MergeRequest) -> MergeResult:
        """接收已批准请求并执行；重复提交相同内容复用原结果。"""
        result = self._store.register(request)
        if result.state.is_terminal:
            return result
        return self._execute(request)

    def get(self, request_id: str) -> MergeResult | None:
        """查询请求结果；未登记返回 None。"""
        return self._store.get(request_id)

    def resume(self, request_id: str) -> MergeResult:
        """恢复单个已登记但未完成的请求。"""
        result = self._store.get(request_id)
        if result is None:
            raise KeyError(f"unknown request {request_id!r}")
        if result.state.is_terminal:
            return result
        request = self._store.get_request(request_id)
        return self._execute(request)

    def resume_all(self) -> list[MergeResult]:
        """恢复所有已登记但未完成的请求。"""
        return [self._execute(req) for req in self._store.pending_requests()]

    def _execute(self, request: MergeRequest) -> MergeResult:
        git = GitOps(request.repo_path)
        # 中断恢复：本请求此前已推进过分支（标记存在），直接认定 Merged，
        # 不再触碰分支当前位置。
        if git.has_execution_marker(request.request_id):
            return self._store.finalize(
                request.request_id, MergeResult(request.request_id, MergeState.MERGED)
            )
        current = git.current_branch_commit(request.target_branch)
        if current != request.expected_old:
            return self._store.finalize(
                request.request_id,
                MergeResult(request.request_id, MergeState.CONFLICT),
            )
        advanced = git.advance_branch(
            request.target_branch,
            request.expected_old,
            request.approved_new,
            request.request_id,
        )
        state = MergeState.MERGED if advanced else MergeState.CONFLICT
        return self._store.finalize(
            request.request_id, MergeResult(request.request_id, state)
        )
