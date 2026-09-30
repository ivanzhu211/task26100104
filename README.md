# task26100104

## merge_approval：批准后合并模块

离线代码评审流程中，上层完成审批并固定获批提交后，本库负责把获批提交
快进合入目标分支。执行记录保存在 SQLite，代码与分支保存在本地裸 Git 仓库。

### 能力

- `submit(request)`：接收已批准的合并请求（接收即授权执行），同一请求标识
  重复提交相同内容时复用原结果，内容不同则抛 `RequestConflictError`。
- `get_result(request_id)`：查询请求结果，未知标识返回 `None`。
- `resume(request_id=None)`：恢复处理已登记但未完成（仍为 `Approved`）的请求。

### 语义保证

- 仅支持快进合并：目标分支已存在，预期旧提交是获批新提交的严格祖先，
  不生成合并提交，不跟随来源分支后续变化。
- 分支推进使用 `git update-ref` 的 compare-and-swap：分支必须仍指向预期
  旧提交，且只能推进到获批新提交，否则记为终态 `Conflict` 且不改动分支。
- 只有本请求实际完成推进才记为终态 `Merged`；此后分支被他人前移或退回
  都不改变结果，重试也不会再次推进。
- 推进完成后、结果落库前发生中断的，恢复（`resume`）后仍认定为 `Merged`，
  且保留他人对分支的改动。

### 用法

```python
from merge_approval import MergeRequest, MergeService

request = MergeRequest(
    request_id="mr-42",
    repo_path="/srv/repos/project.git",   # 本地裸仓库
    target_branch="main",
    expected_old_commit="<base-sha>",     # 审批时目标分支的位置
    approved_new_commit="<approved-sha>", # 获批提交
)

with MergeService("executions.db") as svc:
    result = svc.submit(request)      # 状态为 Approved / Merged / Conflict
    print(result.status, result.detail)

    # 进程重启后恢复未完成的请求
    for r in svc.resume():
        print(r.request_id, r.status)
```

### 测试

```sh
python3 -m pytest tests/ -v
```

测试使用真实裸 Git 仓库与 SQLite 文件，覆盖快进合并、幂等重试、
冲突检测（含他人先把分支推进到同一获批提交）、以及推进后中断
再被别人前移/退回分支的恢复场景。
