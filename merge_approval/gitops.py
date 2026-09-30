"""对本地裸 Git 仓库的分支推进操作。

分支推进与“本请求已执行”的标记引用在同一个 git update-ref
事务中提交：要么同时生效，要么同时失败。恢复流程据此判断
中断前本请求是否真正完成过推进，而不依赖分支当前指向。
"""
from __future__ import annotations

import hashlib
import subprocess

_MARKER_PREFIX = "refs/merge-exec/"


class GitError(RuntimeError):
    """底层 git 命令执行失败。"""


def _marker_ref(request_id: str) -> str:
    digest = hashlib.sha1(request_id.encode("utf-8")).hexdigest()
    return f"{_MARKER_PREFIX}{digest}"


class GitOps:
    """封装对单个裸仓库的原子分支推进与标记读取。"""

    def __init__(self, repo_path: str) -> None:
        self._repo_path = repo_path

    def _run(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", f"--git-dir={self._repo_path}", *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )

    def _verify_ref(self, ref: str) -> str | None:
        proc = self._run("rev-parse", "--verify", "--quiet", ref)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def current_branch_commit(self, branch: str) -> str | None:
        """目标分支当前指向的提交；分支不存在时返回 None。"""
        return self._verify_ref(f"refs/heads/{branch}")

    def has_execution_marker(self, request_id: str) -> bool:
        """本请求的执行标记是否存在（存在即本请求完成过推进）。"""
        return self._verify_ref(_marker_ref(request_id)) is not None

    def advance_branch(
        self, branch: str, expected_old: str, approved_new: str, request_id: str
    ) -> bool:
        """把分支从 expected_old 原子推进到 approved_new，并写入执行标记。

        仅当分支当前仍指向 expected_old 时成功；返回是否实际推进。
        """
        branch_ref = f"refs/heads/{branch}"
        check = self._run("check-ref-format", branch_ref)
        if check.returncode != 0:
            raise GitError(f"invalid branch name: {branch!r}")
        commands = (
            "start\n"
            f"update {branch_ref} {approved_new} {expected_old}\n"
            f"create {_marker_ref(request_id)} {approved_new}\n"
            "prepare\n"
            "commit\n"
        )
        proc = self._run("update-ref", "--stdin", input_text=commands)
        if proc.returncode == 0:
            return True
        if self.has_execution_marker(request_id):
            return True
        return False
