# NovaCore

面向代码任务的终端 AI Agent，基于 DashScope 的 OpenAI-compatible 接口，提供工具调用、MCP 扩展、会话恢复、上下文压缩和可选长期记忆。

## 核心能力

- **按需工具发现**：扩展工具可延迟注册，通过 `ToolSearch` 检索后再暴露对应 schema。采用词法匹配，不等同于通用语义检索。
- **流式工具调用**：解析文本增量与工具参数分片，完整参数组装后交由工具执行链路处理。
- **上下文管理**：摘要较早的消息，保留近期原文；压缩切分边界向前对齐，避免拆开工具调用及结果。
- **会话恢复**：保存消息历史，恢复时根据保留的历史工具调用激活相关工具。仅发现但未调用的工具、已被摘要移除的调用不保证恢复激活状态。
- **权限与隔离**：工具执行经过 Hook、危险命令检测、路径沙箱和权限模式判断；已有 Team 功能使用独立 Git Worktree。
- **可选长期记忆**：默认关闭，可通过 `AUTO_MEMORY_ENABLED=true` 开启稳定信息提取；候选经字段、长度和敏感信息过滤后写入。

## 安装

需要 Python 3.11 或更高版本。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m novacore --help
```

安装会从包源获取依赖。正常模型运行需要自行在环境中配置 `DASHSCOPE_API_KEY`；项目不会自动读取 `.env`。不要将真实密钥写入源码、文档或 Git。

## 使用

启动终端交互界面：

```powershell
.\.venv\Scripts\python.exe -m novacore
```

提交单次任务并流式显示：

```powershell
.\.venv\Scripts\python.exe -m novacore --stream -p "说明当前项目的主要模块和调用链"
```

安装后也可使用 `.\.venv\Scripts\novacore.exe`。会话恢复、权限模式与 MCP 配置示例见 [使用说明](docs/demo.md)。

## 文档与边界

- [架构说明](docs/architecture.md)
- [工具治理与安全边界](docs/security.md)

当前仅支持 DashScope 的 OpenAI-compatible 接口。危险命令检测与路径沙箱属于应用层防线，不替代操作系统隔离；长期记忆的关键词过滤也不等同于完整脱敏方案。按需加载不保证费用、耗时或任务成功率改善。
