import pytest

from merge_approval import (
    STATUS_APPROVED,
    STATUS_CONFLICT,
    STATUS_MERGED,
    MergeRequest,
    MergeService,
    RequestConflictError,
)


def make_request(repo, request_id, old, new, branch="main"):
    return MergeRequest(
        request_id=request_id,
        repo_path=repo.bare,
        target_branch=branch,
        expected_old_commit=old,
        approved_new_commit=new,
    )


def test_submit_fast_forward_merges(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    with MergeService(db_path) as svc:
        result = svc.submit(make_request(repo, "req-1", old, new))

    assert result.status == STATUS_MERGED
    assert repo.branch_head() == new


def test_submit_is_idempotent_and_does_not_readvance(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    with MergeService(db_path) as svc:
        first = svc.submit(make_request(repo, "req-1", old, new))
        assert first.status == STATUS_MERGED

        # 分支之后被别人退回，重试不得再次推进
        repo.set_branch(old)
        again = svc.submit(make_request(repo, "req-1", old, new))
        assert again.status == STATUS_MERGED
        assert repo.branch_head() == old


def test_submit_same_id_with_different_content_raises(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    with MergeService(db_path) as svc:
        svc.submit(make_request(repo, "req-1", old, new))
        with pytest.raises(RequestConflictError):
            svc.submit(make_request(repo, "req-1", old, new, branch="other"))


def test_conflict_when_branch_moved_to_unexpected_commit(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")
    other = repo.commit("other.txt", "x", "c3")
    repo.set_branch(other)

    with MergeService(db_path) as svc:
        result = svc.submit(make_request(repo, "req-1", old, new))

    assert result.status == STATUS_CONFLICT
    assert repo.branch_head() == other


def test_conflict_when_other_tool_advanced_to_same_approved_commit(repo, db_path):
    """其他工具先把分支推进到同一个获批提交，本请求必须为 Conflict。"""
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")
    repo.push_main()  # 其他工具把 main 推进到获批提交
    assert repo.branch_head() == new

    with MergeService(db_path) as svc:
        result = svc.submit(make_request(repo, "req-1", old, new))

    assert result.status == STATUS_CONFLICT
    assert repo.branch_head() == new


def test_crash_after_advance_then_branch_moved_forward(repo, db_path):
    """推进后结果未落库即中断，分支又被别人前移：恢复后为 Merged 且保留分支位置。"""
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    def crash():
        raise RuntimeError("simulated crash after advance")

    svc = MergeService(db_path, after_advance_hook=crash)
    with pytest.raises(RuntimeError):
        svc.submit(make_request(repo, "req-1", old, new))
    svc.close()

    # 中断现场：分支已被本请求推进，但结果未落库
    assert repo.branch_head() == new
    with MergeService(db_path) as check:
        assert check.get_result("req-1").status == STATUS_APPROVED

    # 其他工具把分支继续前移
    later = repo.commit("file.txt", "v3", "c3")
    repo.push_main()
    assert repo.branch_head() == later

    with MergeService(db_path) as svc2:
        results = svc2.resume()
        assert [r.status for r in results] == [STATUS_MERGED]
        assert svc2.get_result("req-1").status == STATUS_MERGED
        # 保留别人的分支位置
        assert repo.branch_head() == later

        # 再次重试不得推进分支
        retry = svc2.submit(make_request(repo, "req-1", old, new))
        assert retry.status == STATUS_MERGED
        assert repo.branch_head() == later


def test_crash_after_advance_then_branch_rewound(repo, db_path):
    """推进后结果未落库即中断，分支又被别人退回：恢复后为 Merged 且保留分支位置。"""
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    def crash():
        raise RuntimeError("simulated crash after advance")

    svc = MergeService(db_path, after_advance_hook=crash)
    with pytest.raises(RuntimeError):
        svc.submit(make_request(repo, "req-1", old, new))
    svc.close()
    assert repo.branch_head() == new

    # 其他工具把分支退回旧提交
    repo.set_branch(old)
    assert repo.branch_head() == old

    with MergeService(db_path) as svc2:
        results = svc2.resume("req-1")
        assert [r.status for r in results] == [STATUS_MERGED]
        assert repo.branch_head() == old

        retry = svc2.submit(make_request(repo, "req-1", old, new))
        assert retry.status == STATUS_MERGED
        assert repo.branch_head() == old


def test_resume_without_request_id_processes_all_unfinished(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    def crash():
        raise RuntimeError("simulated crash")

    svc = MergeService(db_path, after_advance_hook=crash)
    with pytest.raises(RuntimeError):
        svc.submit(make_request(repo, "req-a", old, new))
    svc.close()

    with MergeService(db_path) as svc2:
        results = svc2.resume()
        assert len(results) == 1
        assert results[0].request_id == "req-a"
        assert results[0].status == STATUS_MERGED
        assert repo.branch_head() == new


def test_get_result_unknown_returns_none(repo, db_path):
    with MergeService(db_path) as svc:
        assert svc.get_result("missing") is None


def test_rejects_non_fast_forward_request(repo, db_path):
    old = repo.head()
    new = repo.commit("file.txt", "v2", "c2")

    with MergeService(db_path) as svc:
        # 新提交不是旧提交的后代
        with pytest.raises(ValueError):
            svc.submit(make_request(repo, "req-bad", new, old))
        # 两提交相同
        with pytest.raises(ValueError):
            svc.submit(make_request(repo, "req-bad-2", old, old))
        # 目标分支不存在
        with pytest.raises(ValueError):
            svc.submit(make_request(repo, "req-bad-3", old, new, branch="nope"))
