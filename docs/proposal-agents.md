# 真正的 Proposer / Reviewer Agent

此模式复用 NovaCore 的 `Agent.run_to_completion`。两个角色各有自己的
`ConversationManager`、系统提示、工具注册表和运行轨迹；模型可以选择工具、
观察返回值，再决定下一步。不再是固定两次文本生成。

```text
需求和批准范围 → Proposer Agent 工具循环
→ 程序固定候选、重新收集检查证据
→ Reviewer Agent 独立工具循环 → 人工决定后续操作
```

## 工具和权限

| 工具 | Proposer | Reviewer |
| --- | --- | --- |
| `ReadFile` | 读取批准文件的 base/candidate 版本 | 相同，只读 |
| `SearchFiles` | 在批准文件中做字面文本搜索 | 相同，只读 |
| `GetDiff` | 查看实际候选 diff | 相同，只读 |
| `CheckCandidate` | 检查候选语法/JSON | 相同，只读 |
| `WriteFile` | 仅替换批准的现存文件，返回诊断 | 不注册，权限层也拒绝 |

原文件、关联范围与版本在准备时固定。不会读取整个仓库、凭据文件或任意路径；
额外关联文件必须由用户明确批准。没有 Bash、网络工具、MCP、记忆、委托、
Git 推送或合并工具。检查器不导入或执行候选，不运行项目脚本；diff 在内存中
由实际文本生成，不调用 Git diff 的 clean/textconv 驱动。

Proposer 可以收到语法错误后继续调用 `WriteFile` 修正。只有它正常结束工具
循环、返回结构化完成、确有实际改动且安全检查无失败，程序才启动 Reviewer。
Reviewer 必须成功调用 `GetDiff` 和 `CheckCandidate`，才能提交有效结论；
有问题需提供真实改动行上的证据，不得把 Proposer 的自我评价当作结论。

## 使用方法

使用包含新模块的 checkout/环境；若使用旧 editable 安装，先将
`PYTHONPATH` 指向当前 checkout，避免导入另一个版本。

准备新任务，不调用模型：

```powershell
python -m novacore.proposal_agents --task "具体需求与验收要求" --repo C:\src\project --allow-file module.py --output C:\proposals\agent-job
```

最多批准五个现存、非可执行 UTF-8 普通文件，总原始内容 64 KiB。输入来自已
提交 HEAD，原目录未提交改动不纳入、也不覆盖。沿用隔离稀疏 worktree，
不支持新建、删除、重命名，不是完整可运行的应用副本。请检查准备文件后再授权。

明确授权 Agent 循环：

```powershell
python -m novacore.proposal_agents --run C:\proposals\agent-job --confirm-paid
```

**这是新预算：最多十次模型请求，不是轻量模式的两次。** 每角色最多五轮，
共享十次上限；每次 90 秒、2048 输出 tokens，SDK 无自动重试。每响应最多
八个工具调用，整体最多处理三十二个。额外上下文压缩请求在发出前阻断；超限
无法完成时返回无法确认，不默认放行。只有新的明确授权才可以开始下一次运行。

不带付费参数的 `--run` 只显示状态。持久化独占 `agent-run.json`、角色计数
和底层状态共同防止重复/并发启动；旧轻量任务已运行过时不能切换模式重新花费。
异常或取消保留预算与产物，不自动重跑。

## 观察实际对话

- `agent-run.json`：各角色调用次数、执行顺序、工具数量和状态。
- `proposer-transcript.jsonl`：Proposer 的请求消息、工具定义、解析的回复和工具调用。
- `reviewer-transcript.jsonl`：Reviewer 的独立轨迹，不混入 Proposer 对话。
- `agent-snapshot.json`：实际候选、diff、程序独立检查和哈希。
- `agent-review.json/.md`：经过结构和源码定位校验的审核结果。
- `changes.patch`、`worktree`：未提交候选。

这些是调用边界的实际消息记录，不是事后重建；回复使用 SDK 解析后的
assistant 文本和 tool calls，不是原始 HTTP 抓包。成功返回时记录请求/返回模型
标识；不记录 HTTP 头、凭据、SDK 原始异常或服务商 `reasoning_content`。
不会回填旧运行不存在的日志，也不展示未返回的模型内部推理。

日志会递归隐藏敏感字段和常见 Bearer/API key 字符串，但不是完整的秘密检测器。
源文件和需求也可能含秘密：不要授权包含凭据的材料，不要把日志未经检查公开。
对代码的读取和写入权限由工具实现检查，不能只依赖模型遵守提示。

## 结果和边界

`reviewed_no_findings` 只表示本轮未报告问题；`awaiting_human_selection`
表示需要人工检查。预算、格式、版本、证据不足或循环耗尽均不能批准候选。
业务行为验收仍需单独进行，语法检查不等于任务完成。

本版只自动执行一轮 Proposer Agent 任务和一轮 Reviewer Agent 审核；
每个角色内部可多次调用工具，但 Reviewer 退回后不自动回跳修正。
不提交、推送、创建 PR、评论或合并。路径和哈希检查不是对恶意本地进程的
操作系统级隔离。模型可能仍提出逻辑错误或有害改动，人工验收不可省略。

[轻量双调用模式](proposal-review.md)保留兼容性；
[已有 PR 审查](pr-review.md)和[审查后修复](pr-proposer.md)仍是单独入口。
不要把旧命令误认为已经换成工具型 Agent 循环。
