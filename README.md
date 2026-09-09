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

`benchmarks/fixtures/tool_search_queries.json` 提供 20 条人工标注查询，覆盖准确名称、关键词、同义表达、模糊描述、无匹配和精确选择。基准逐条调用真实 `ToolSearch.execute()`，先报告旧词法策略失败案例，再报告大小写/分隔符/词形/有限同义词归一化后的结果。

完整请求载荷边界明确拆分为：100 个完整 schema、工具目录、`ToolSearch` schema、以及实际发现并激活的 schema；消息体不计入字节指标。当前结果见 `benchmarks/results/tool_discovery.json`：改进策略 20 条查询命中 17 条目标、1 条误激活失败案例、2 条正确无匹配；全量 schema 为 25,545 bytes，按需请求（目录 + ToolSearch + 发现结果）为 10,813–11,275 bytes。字节除以 4 只是近似值，不是 provider Token、费用或耗时测量。

### 多 Agent 隔离

Coordinator 管理 Team、任务和通知。每名 teammate 使用独立 Git Worktree；其文件工具的根目录和 PathSandbox 都绑定到自己的 Worktree，不能读写兄弟 Worktree。

## 快速验证

```powershell
python -m pytest tests -q
python -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --queries benchmarks/fixtures/tool_search_queries.json --output benchmarks/results/tool_discovery.json
python -m json.tool benchmarks/results/tool_discovery.json
```

开发环境安装：

```powershell
python -m pip install -r requirements-dev.txt
```

测试和基准均离线运行，不访问真实模型、MCP 服务或 API 密钥。

## 已知边界

- 当前只支持 DashScope 的 OpenAI-compatible 接口；未实现 Anthropic 协议适配。
- 自动记忆使用关键词敏感信息过滤，不等同于完整的数据脱敏方案。
- 危险命令检测为规则防线，不是操作系统级安全沙箱。
- ToolSearch 当前是固定目录上的可解释词法检索，不等同于通用语义检索；`no-match-rocket` 仍会把 `send` 误激活到 `SendEmail`。
- 字节/4 不是账单 Token；本项目没有据此推导费用、耗时或任务成功率收益。
- 当前基线保留扁平包布局；从仓库根目录直接执行 `python -m novacore` 的导入限制不属于本次证据修复范围。
