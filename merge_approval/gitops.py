"""对本地裸 Git 仓库的只读/写操作封装。"""

from __future__ import annotations

import subprocess
from typing import Optional


class GitError(Exception):
    """Git 命令执行失败。"""


def _run_git(repo_path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", f"--git-dir={repo_path}", *args],
        capture_output=True,
        text=True,
    )


def _ref_name(branch: str) -> str:
    if branch.startswith("refs/"):
        return branch
    return f"refs/heads/{branch}"


def resolve_ref(repo_path: str, branch: str) -> Optional[str]:
    """返回分支当前指向的提交；分支不存在时返回 None。"""
    proc = _run_git(repo_path, "rev-parse", "--verify", "--quiet", _ref_name(branch))
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def commit_exists(repo_path: str, commit: str) -> bool:
    """判断提交是否存在于仓库中。"""
    proc = _run_git(repo_path, "cat-file", "-e", f"{commit}^{{commit}}")
    return proc.returncode == 0


def is_ancestor(repo_path: str, old: str, new: str) -> bool:
    """判断 old 是否为 new 的祖先（含相等）。"""
    proc = _run_git(repo_path, "merge-base", "--is-ancestor", old, new)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise GitError(proc.stderr.strip() or "git merge-base failed")


def compare_and_swap_ref(repo_path: str, branch: str, new: str, old: str) -> bool:
    """仅当分支仍指向 old 时将其推进到 new，返回是否成功。"""
    proc = _run_git(repo_path, "update-ref", _ref_name(branch), new, old)
    if proc.returncode == 0:
        return True
    # update-ref 在校验旧值不匹配时以非零退出
    return False
