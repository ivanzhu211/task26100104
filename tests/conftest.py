import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", f"--git-dir={repo}", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def work_git(work: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(work), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture()
def env(tmp_path):
    """裸仓库 + 工作克隆：main 指向 old，new 是 old 的子提交且已在裸仓库中。"""
    bare = tmp_path / "repo.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    subprocess.run(["git", "clone", str(bare), str(work)], check=True,
                   capture_output=True)
    work_git(work, "config", "user.email", "t@example.com")
    work_git(work, "config", "user.name", "T")
    work_git(work, "checkout", "-b", "main")

    (work / "a.txt").write_text("a\n")
    work_git(work, "add", ".")
    work_git(work, "commit", "-m", "old")
    old = work_git(work, "rev-parse", "HEAD")
    work_git(work, "push", "origin", "main")

    (work / "b.txt").write_text("b\n")
    work_git(work, "add", ".")
    work_git(work, "commit", "-m", "new")
    new = work_git(work, "rev-parse", "HEAD")
    # 让获批提交存在于裸仓库，但 main 仍指向 old
    work_git(work, "push", "origin", "main:refs/keep/approved")

    class Env:
        pass

    env = Env()
    env.bare = bare
    env.work = work
    env.db = str(tmp_path / "merge.db")
    env.old = old
    env.new = new
    env.branch = "main"

    def make_commit(filename: str, content: str, message: str) -> str:
        (work / filename).write_text(content)
        work_git(work, "add", ".")
        work_git(work, "commit", "-m", message)
        sha = work_git(work, "rev-parse", "HEAD")
        work_git(work, "push", "origin", "main:refs/keep/extra")
        return sha

    env.make_commit = make_commit
    return env
