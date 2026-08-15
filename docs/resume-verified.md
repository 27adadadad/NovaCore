# NovaCore Coding Agent｜终端 AI 编程助手

**技术栈：** Python、AsyncIO、OpenAI SDK、阿里云百炼（qwen-plus）、MCP、Pydantic、Textual、Git Worktree、Multi-Agent

## 项目介绍

独立开发的终端 Coding Agent，提供流式 Tool Calling、MCP 工具扩展、Skill 加载、会话持久化、长期记忆、上下文摘要压缩和多 Agent 协作。项目将交互、Agent 执行、工具注册、记忆/会话持久化及工具治理拆分为独立模块，并通过 Textual 提供终端 TUI。

## 个人职责

- 负责 Agent 执行循环、流式工具调用解析、工具注册表、会话持久化与终端交互等核心模块设计和实现。
- 实现项目级与用户级长期记忆，新增任务成功后的异步自动提取：候选经过 JSON 校验、敏感信息过滤和标题幂等更新后再持久化。
- 设计 MCP 延迟工具发现机制、多 Agent 的 Git Worktree 隔离机制，以及命令/路径/权限/Hook 组合的工具治理链路。

## 技术亮点

- **MCP 延迟工具发现：** 扩展工具以 deferred 状态注册，模型通过 `ToolSearch` 检索后才激活完整 schema。固定 100 工具基准中，激活 3 个工具时 schema payload 由约 8.2k 降至约 0.25k 近似 Token，减少约 97.0%（UTF-8 字节数/4 估算）。
- **流式 Function Calling：** 使用 AsyncOpenAI 对接 qwen-plus；按 tool call index 缓冲增量 name/arguments，完成 JSON 解析后再发出完整工具调用事件。
- **上下文压缩：** 对历史消息生成摘要并保留近期原文；压缩边界向前对齐，保证工具调用与工具结果成对保留。设置 20k 摘要输出预留和自动压缩安全边界。
- **长期记忆：** 用户与项目双作用域 `MEMORY.md` 随新会话注入；自动记忆后台运行，不阻塞主回答，提取或写入失败不影响任务结果。
- **Hook 与权限治理：** 支持 TURN_START、PRE_TOOL_USE、POST_TOOL_USE、TURN_END 四阶段 Hook；工具调用同时接受危险命令检测、路径沙箱、权限模式和交互确认约束。
- **多 Agent 隔离：** Coordinator 管理 teammate、任务和消息；每名 teammate 使用独立 Git Worktree，其路径沙箱拒绝访问兄弟工作区。

## 面试说明

项目当前支持 DashScope 的 OpenAI-compatible 接口；未实现 Anthropic 协议或显式 Plan Mode。性能数据、测试范围和已知边界见 `docs/verification-report.md`。
