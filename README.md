# NovaCore

面向代码任务的终端 AI Agent。项目基于 OpenAI-compatible API，提供工具调用、MCP 扩展、会话恢复、上下文压缩、长期记忆和基于 Git Worktree 的多 Agent 协作。

## 设计目标

- 工具很多时，按需暴露 schema，降低每轮模型请求的上下文占用。
- 长会话接近上下文窗口时，摘要早期消息并保留近期消息与完整工具调用配对。
- 将稳定的用户偏好和项目约束沉淀为长期记忆，且不阻塞主任务。
- 让多 Agent 在独立 Worktree 中执行，并对文件访问施加路径沙箱。

## 核心能力

### 自动长期记忆

任务成功后可异步提取稳定信息。提取请求不携带工具 schema；模型只返回受限 JSON。候选在写入前会经过字段校验、长度限制和敏感信息过滤，并按标题幂等更新。

默认关闭。启用：

```powershell
$env:AUTO_MEMORY_ENABLED = "true"
$env:AUTO_MEMORY_MAX_CANDIDATES = "3"
```

### 延迟工具发现

MCP 和扩展工具可先以 deferred 状态注册。模型通过 `ToolSearch` 检索相关工具后，注册表才会激活相应 schema；已发现的工具会随会话恢复再次激活。

固定 100 工具基准中，仅激活 3 个工具时，schema payload 由约 8,175 降至约 246 近似 Token，节省约 97.0%。该结果使用 UTF-8 字节数除以 4 估算 Token，详细输入和结果见 `benchmarks/`。

### 多 Agent 隔离

Coordinator 管理 Team、任务和通知。每名 teammate 使用独立 Git Worktree；其文件工具的根目录和 PathSandbox 都绑定到自己的 Worktree，不能读写兄弟 Worktree。

## 快速验证

```powershell
python -m pytest tests -q
python -c "from benchmarks.tool_discovery import run_fixture; print(run_fixture('benchmarks/fixtures/tools_100.json', 'benchmarks/results/tool_discovery.json'))"
```

测试均离线运行，不访问真实模型或 MCP 服务。

## 已知边界

- 当前只支持 DashScope 的 OpenAI-compatible 接口；未实现 Anthropic 协议适配。
- 自动记忆使用关键词敏感信息过滤，不等同于完整的数据脱敏方案。
- 危险命令检测为规则防线，不是操作系统级安全沙箱。
- 97.0% 是固定 fixture 的 schema payload 结果，实际收益取决于工具复杂度与已激活工具数量。
