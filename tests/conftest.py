import os
import subprocess

import pytest


def run_git(*args, cwd=None):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="tester",
        GIT_AUTHOR_EMAIL="tester@example.com",
        GIT_COMMITTER_NAME="tester",
        GIT_COMMITTER_EMAIL="tester@example.com",
    )
    subprocess.run(["git", *args], check=True, capture_output=True, cwd=cwd, env=env)


class RepoFixture:
    """一个本地裸仓库 + 一个工作克隆，用于构造真实提交。"""

    def __init__(self, tmp_path):
        self.bare = str(tmp_path / "repo.git")
        self.work = str(tmp_path / "work")
        run_git("init", "--bare", self.bare)
        run_git("init", self.work)
        run_git("checkout", "-b", "main", cwd=self.work)

    def commit(self, name, content, message):
        path = os.path.join(self.work, name)
        with open(path, "w") as fh:
            fh.write(content)
        run_git("add", name, cwd=self.work)
        run_git("commit", "-m", message, cwd=self.work)
        # 把新提交的对象送入裸仓库（不动 main），模拟提交已存在于仓库中
        run_git("push", self.bare, "HEAD:refs/scratch/head", cwd=self.work)
        return self.head()

    def head(self):
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=self.work,
        )
        return out.stdout.strip()

    def push_main(self):
        run_git("push", self.bare, "HEAD:main", cwd=self.work)

    def branch_head(self, branch="main"):
        out = subprocess.run(
            ["git", f"--git-dir={self.bare}", "rev-parse", f"refs/heads/{branch}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def set_branch(self, commit, branch="main"):
        """模拟其他工具直接改写裸仓库分支。"""
        run_git(f"--git-dir={self.bare}", "update-ref", f"refs/heads/{branch}", commit)


@pytest.fixture
def repo(tmp_path):
    fixture = RepoFixture(tmp_path)
    fixture.commit("file.txt", "v1", "c1")
    fixture.push_main()
    return fixture


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "executions.db")
