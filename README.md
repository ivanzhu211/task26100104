# task26100104
# 批准后合并模块（merge_approval）

离线代码评审流程中，上层完成审批并固定获批提交后，由本库把获批提交
快进合入目标分支。执行记录保存在 SQLite，代码与分支保存在本地裸
Git 仓库，不依赖任何外部服务。

## 能力

- `submit`：接收已批准合并请求（接收即授权执行）；同一请求标识重复
  提交相同内容时复用原结果，内容不同则抛 `DuplicateRequestError`。
- `get`：按请求标识查询结果。
- `resume` / `resume_all`：恢复已登记但未完成（状态仍为 Approved）
  的请求，进程在任意点中断后均可安全续跑。

## 状态与保证

- 状态：`Approved`（进行中）→ `Merged` / `Conflict`（终态，不可变）。
- 仅支持快进合并：目标分支仍指向预期旧提交时，原子推进至获批新提交；
  否则记为 `Conflict`，分支保持不变。
- 分支推进与“本请求已执行”标记在同一 `git update-ref` 事务中提交，
  因此只有本请求实际完成推进才会记为 `Merged`；分支恰好等于获批提交
  不构成成功证据。推进后结果未落库即中断的，恢复时凭标记认定为
  `Merged`，且不再次触碰分支（保留其他工具的后续改动）。

## 用法

```python
from merge_approval import MergeRequest, MergeService

service = MergeService("/path/to/merge.db")

result = service.submit(MergeRequest(
    request_id="mr-42",
    repo_path="/path/to/repo.git",   # 本地裸仓库
    target_branch="main",
    expected_old="<old-sha>",        # 审批时目标分支指向
    approved_new="<new-sha>",        # 获批提交，old 的严格后代
))
print(result.state)                  # MergeState.MERGED / CONFLICT

service.get("mr-42")                 # 查询结果
service.resume("mr-42")              # 恢复单个未完成请求
service.resume_all()                 # 恢复全部未完成请求
```

## 测试

```sh
python3 -m pytest tests -q
```

测试使用真实裸 Git 仓库与 SQLite 文件，覆盖：正常快进、重复提交复用、
分支被改动（含被其他工具推进到同一获批提交）导致的 Conflict、推进后
中断且分支被前移/退回时的恢复语义、终态不可变等场景。
