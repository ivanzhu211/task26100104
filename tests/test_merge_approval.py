import pytest

from merge_approval import MergeRequest, MergeService, MergeState
from merge_approval.gitops import GitOps
from merge_approval.store import DuplicateRequestError, RecordStore

from tests.conftest import git


def make_request(env, request_id="req-1"):
    return MergeRequest(
        request_id=request_id,
        repo_path=str(env.bare),
        target_branch=env.branch,
        expected_old=env.old,
        approved_new=env.new,
    )


def branch_head(env):
    return git(env.bare, "rev-parse", "refs/heads/main")


def test_submit_fast_forward_merge(env):
    service = MergeService(env.db)
    result = service.submit(make_request(env))
    assert result.state is MergeState.MERGED
    assert branch_head(env) == env.new
    assert service.get("req-1").state is MergeState.MERGED


def test_duplicate_submit_reuses_result(env):
    service = MergeService(env.db)
    first = service.submit(make_request(env))
    # 分支被其他工具前移后，重复提交仍复用原结果且不推进分支
    other = env.make_commit("c.txt", "c\n", "other")
    git(env.bare, "update-ref", "refs/heads/main", other)
    second = service.submit(make_request(env))
    assert second.state is MergeState.MERGED
    assert first == second
    assert branch_head(env) == other


def test_duplicate_submit_with_different_content_rejected(env):
    service = MergeService(env.db)
    service.submit(make_request(env))
    changed = MergeRequest(
        request_id="req-1",
        repo_path=str(env.bare),
        target_branch=env.branch,
        expected_old=env.old,
        approved_new=env.old,
    )
    with pytest.raises(DuplicateRequestError):
        service.submit(changed)


def test_conflict_when_branch_moved_elsewhere(env):
    other = env.make_commit("c.txt", "c\n", "other")
    git(env.bare, "update-ref", "refs/heads/main", other)
    service = MergeService(env.db)
    result = service.submit(make_request(env))
    assert result.state is MergeState.CONFLICT
    assert branch_head(env) == other


def test_conflict_when_other_tool_advanced_to_same_commit(env):
    """其他工具先把分支推进到同一个获批提交：本请求必须为 Conflict。"""
    git(env.bare, "update-ref", "refs/heads/main", env.new, env.old)
    assert branch_head(env) == env.new
    service = MergeService(env.db)
    result = service.submit(make_request(env))
    assert result.state is MergeState.CONFLICT
    assert branch_head(env) == env.new


def simulate_crash_after_advance(env, request_id="req-1"):
    """登记请求并完成分支推进，但不落库结果，模拟中断。"""
    store = RecordStore(env.db)
    request = make_request(env, request_id)
    store.register(request)
    advanced = GitOps(str(env.bare)).advance_branch(
        env.branch, env.old, env.new, request_id
    )
    assert advanced
    assert branch_head(env) == env.new
    assert store.get(request_id).state is MergeState.APPROVED
    return request


def test_resume_after_crash_branch_moved_forward_by_others(env):
    """推进后中断，分支被别人前移：恢复为 Merged 且保留别人位置。"""
    request = simulate_crash_after_advance(env)
    other = env.make_commit("c.txt", "c\n", "other")
    git(env.bare, "update-ref", "refs/heads/main", other)

    service = MergeService(env.db)
    result = service.resume(request.request_id)
    assert result.state is MergeState.MERGED
    assert branch_head(env) == other

    # 再次重试不得推进分支
    again = service.submit(request)
    assert again.state is MergeState.MERGED
    assert branch_head(env) == other


def test_resume_after_crash_branch_reset_back_by_others(env):
    """推进后中断，分支被别人退回：恢复为 Merged 且保留退回位置。"""
    request = simulate_crash_after_advance(env)
    git(env.bare, "update-ref", "refs/heads/main", env.old)
    assert branch_head(env) == env.old

    service = MergeService(env.db)
    result = service.resume(request.request_id)
    assert result.state is MergeState.MERGED
    assert branch_head(env) == env.old

    again = service.resume(request.request_id)
    assert again.state is MergeState.MERGED
    assert branch_head(env) == env.old


def test_merged_state_survives_later_branch_changes(env):
    service = MergeService(env.db)
    request = make_request(env)
    assert service.submit(request).state is MergeState.MERGED

    # 成功后被退回再前移，状态保持 Merged，重试不再推进
    git(env.bare, "update-ref", "refs/heads/main", env.old)
    assert service.get(request.request_id).state is MergeState.MERGED
    assert service.submit(request).state is MergeState.MERGED
    assert branch_head(env) == env.old


def test_resume_all_processes_pending(env):
    store = RecordStore(env.db)
    req1 = make_request(env, "req-a")
    store.register(req1)
    req2 = MergeRequest(
        request_id="req-b",
        repo_path=str(env.bare),
        target_branch=env.branch,
        expected_old=env.old,
        approved_new=env.new,
    )
    # req-b 与 req-a 内容冲突（同一分支同一 old），先登记者胜出
    store.register(req2)

    service = MergeService(env.db)
    results = {r.request_id: r for r in service.resume_all()}
    assert results["req-a"].state is MergeState.MERGED
    assert results["req-b"].state is MergeState.CONFLICT
    assert branch_head(env) == env.new


def test_resume_unknown_request(env):
    service = MergeService(env.db)
    with pytest.raises(KeyError):
        service.resume("nope")
    assert service.get("nope") is None
