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

`benchmarks/fixtures/tool_search_queries.json` 提供 20 条人工标注查询。基准逐条调用真实 `ToolSearch.execute()`；其中标为准确名称的查询使用了 `select:`，尚不能证明默认检索的准确名称处理效果。JSON 的 baseline 实现并非历史原算法，不能据此声称命中率从 6/17 提升到 17/17。

当前结果见 `benchmarks/results/tool_discovery.json`：17/17 条有目标查询命中，3 条无匹配查询中 1 条误激活、2 条正确拒绝。全量 schema 为 25,545 bytes；人工拼装的“目录 + ToolSearch + 已激活 schema”字段为 10,813–11,275 bytes。统计排除了消息体及 ToolSearch 发现结果消息中的 schema，不代表完整请求或完整发现流程。报告保留的字节/4 字段不代表 provider Token、费用或耗时。

### 多 Agent 隔离

Coordinator 管理 Team、任务和通知。每名 teammate 使用独立 Git Worktree；其文件工具的根目录和 PathSandbox 都绑定到自己的 Worktree，不能读写兄弟 Worktree。

## 安装与启动

从仓库根目录运行。源码已整理为标准 `novacore/` 包；测试、模块启动和安装后的终端命令使用同一导入路径。

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m novacore --help
.\.venv\Scripts\novacore.exe --help
~~~

帮助、参数检查和以下离线示例不需要 API 密钥。正常模型运行仍需要你自行配置 `DASHSCOPE_API_KEY`；本项目不自动读取 `.env`。不要将真实密钥写入源码、文档或 Git。

## 快速验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m novacore.examples.offline_smoke
.\.venv\Scripts\python.exe -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --queries benchmarks/fixtures/tool_search_queries.json --output .pytest-tmp/toolsearch.json
.\.venv\Scripts\python.exe -m json.tool .pytest-tmp/toolsearch.json
```

测试和基准均离线运行，不访问真实模型、MCP 服务或 API 密钥。依赖安装需要访问包源；安装完成后，上述验证本身无需联网。

`offline_smoke` 用已有 FakeClient 驱动真实 Agent、ReadFile 和 Session：在临时目录创建样本，执行两轮模型模拟交互，再校验会话恢复后的调用/结果配对。它验证运行链路，不验证在线模型效果；临时文件和会话在结束后清理。

输出目录 `.pytest-tmp/` 被 Git 忽略，下一次 pytest 可能清理它；需长期保存时请将基准输出放在仓库外。最新入口验证见 [启动与离线交互验证](docs/verification-startup.md)。

基准统一使用 `python -m benchmarks.tool_discovery` 模块入口；未安装项目的源码环境不支持直接执行 `python benchmarks/tool_discovery.py`。

## 已知边界

- 当前只支持 DashScope 的 OpenAI-compatible 接口；未实现 Anthropic 协议适配。
- 自动记忆使用关键词敏感信息过滤，不等同于完整的数据脱敏方案。
- 危险命令检测为规则防线，不是操作系统级安全沙箱。
- ToolSearch 当前是固定目录上的可解释词法检索，不等同于通用语义检索；`no-match-rocket` 仍会把 `send` 误激活到 `SendEmail`。
- 字节/4 不是账单 Token；本项目没有据此推导费用、耗时或任务成功率收益。
- 帮助与离线链路已验证；无窗口 TUI 使用模拟模型验证，不代表在线模型、真实 MCP 服务或完整生产运行已验证。
