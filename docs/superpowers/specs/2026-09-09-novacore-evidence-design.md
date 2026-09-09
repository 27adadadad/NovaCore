# NovaCore 简历证据可复现性设计

## 目标

在 `feat/agent-resume-alignment` 的代码边界内，为 ToolSearch、流式 Function Calling、上下文与会话管理建立可离线复现的代码、测试、基准和结果文件。保留 DashScope 的 OpenAI-compatible 协议，不新增显式 Plan→Execute、多 Agent、自动记忆或向量数据库能力。

## 方案

创建固定 100 工具目录与约 20 条人工标注查询。每条查询都用 deferred `ToolRegistry` 注册 fixture 工具，并调用真实 `ToolSearch.execute()` 得到发现结果；标注仅用于事后计算命中、误激活和无匹配处理。基准先运行当前词法策略并输出失败案例，再运行小幅文本归一化/有限同义词策略，两个结果并列保存。

完整请求载荷拆分为工具目录、ToolSearch schema、实际发现 schema；100 个全量 schema 作为对照。消息体不计入该字节指标，并在 JSON 中明确记录边界。字节除以 4 只作为近似值，不声称 provider Token、费用或耗时收益。

## 关键验证

- 使用 Fake SDK chunk 验证多个 tool-call index 交错、参数分片、非法/截断 JSON 和 id/name 缺失。
- 使用 FakeClient 验证 ToolSearch 激活后下一轮才暴露目标 schema。
- 使用临时目录验证上下文压缩不拆开 tool use/result，Session 保存恢复保留配对并恢复 deferred 激活状态。
- 使用声明的 pytest/pytest-asyncio 开发依赖，移除 worktree 内固定 basetemp，确保 README 命令可运行。

## 限制

评测是固定目录上的离线词法评测，不代表通用语义检索。选定基线的扁平包布局及从仓库根目录执行 `python -m novacore` 的导入限制不在本次范围内。
