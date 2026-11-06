# 先提案，再审核

本文是保留兼容性的轻量双调用模式。需要模型自主选择工具、观察反馈并继续执行时，
使用[真正的 Proposer / Reviewer Agent](proposal-agents.md)，入口为 `novacore.proposal_agents`。

这是从需求开始的入口，不需要预先有审查问题：

```text
需求 + 固定来源提交 + 批准的文件范围
→ Proposer 生成初始候选
→ 程序校验、写入隔离副本、收集检查证据
→ 独立 Reviewer 审核新 diff 与证据
→ 无发现项 / 退回人工处理 / 无法确认
```

[已有 PR 审查](pr-review.md)接收别人已经完成的初稿；
[审查后修复](pr-proposer.md)处理已有问题。这三种入口不要混称。

## 准备需求与范围：不调用模型

从已安装 NovaCore 的环境运行，替换需求、仓库、文件和输出路径：

```powershell
python -m novacore.proposal_review --task "实现需求，保持无关行为不变" --repo C:\src\project --allow-file module.py --output C:\proposals\job-001
```

重复 `--allow-file` 可批准更多文件。起点是仓库已提交的 HEAD；原目录未提交
改动不会被读取、覆盖或自动纳入候选。不要重置自己的工作。输出必须是仓库外新目录。
第一版支持最多五个现存、非可执行普通 UTF-8 文件，总原始内容最多 64 KiB；
不支持新建、删除、重命名文件，不允许敏感路径或模型自行扩大范围。

检查 `snapshot.json` 与 `fix-report.json`：`selected_findings` 此时为空，
`job_kind` 是 `task_proposal`。文件名沿用底层引擎，不表示已经经过初审。

## 明确授权：先初始提案，再独立审核

```powershell
python -m novacore.proposal_review --run C:\proposals\job-001 --confirm-paid
```

此授权最多两次模型请求，每角色各一次：不同 Client、独立系统提示和消息数组。
各次 90 秒、2048 输出 tokens、SDK 不自动重试。较大文件可能无法在输出上限内
完整替换；非法或截断响应被拒绝，不作为候选。确认你有权把需求和代码发送给
当前配置的服务商，不要把密钥发到聊天中。

不带 `--confirm-paid` 的 `--run` 只显示状态。独占持久化 `pipeline.json`
防止重复与并发启动，失败后不要直接重复付费运行。

## 审核材料与实际证据

Proposer 收到需求和允许文件，没有虚构的 Reviewer 意见。程序检查路径、原始
SHA256、来源版本和并发改动后写入隔离工作树。提案或候选检查失败，不调用 Reviewer。

Reviewer 收到原始需求、初稿的新旧代码与 diff，以及程序针对候选重新生成的
语法/JSON 检查和实际字节哈希，不接收 Proposer 的完整对话或自我评价。
这些检查不导入、执行候选，不运行项目命令；它们只覆盖语法/JSON，
**不证明业务行为正确**。不支持的类型明确标记跳过。

输出：`changes.patch` 为候选改动；`local-snapshot.json` 包含候选与独立检查；
`local-review.json/.md` 是审核结果，范围为 `initial_task_candidate`；
`pipeline.json` 记录角色调用顺序、次数和状态。
`head_sha` 是来源提交，候选由 `candidate_hashes` 标识，并非已经提交。
不会自动提交、推送、创建 PR、评论或合并。

## 结果与边界

| 状态 | 含义 |
| --- | --- |
| `reviewed_no_findings` | 本轮未报告问题，不代表任务完成或允许合并。 |
| `awaiting_human_selection` | 审核要求修改，停止并等待人工检查。 |
| `proposal_not_ready` | 提案或候选检查失败，没有调用 Reviewer。 |
| `review_inconclusive` | 审核失败或无法判断，不默认放行。 |

对应退出码为 0、1、2、2。本版只做一轮初始提案和一轮审核；退回后不自动再次
调用 Proposer，本地任务尚未接入自动多轮修正。不能把本地任务报告直接传给旧
GitHub PR 修复入口，也不能伪造 GitHub 链接绕过远端校验。

稀疏 worktree 只物化批准的文件，不是完整应用环境。当前仍是两个受控模型角色，
不是书中具备完整工具循环的自主子 Agent；进一步扩展需要另行设计工具权限、
业务证据和有预算的多轮流程，不能只交换角色名称。
