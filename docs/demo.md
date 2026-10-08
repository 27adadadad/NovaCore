# 使用说明

以下命令从仓库根目录运行，要求已安装项目。帮助入口不需要模型密钥；其他正常任务需先在环境中配置自己的 `DASHSCOPE_API_KEY`，并可能产生模型服务费用。

## 交互模式

```powershell
.\.venv\Scripts\python.exe -m novacore
```

输入任务后由 Agent 调用必要工具。对于需要确认的操作，应在界面中审阅后再批准。

## 单次任务与流式输出

```powershell
.\.venv\Scripts\python.exe -m novacore -p "解释 README 中的安装步骤"
.\.venv\Scripts\python.exe -m novacore --stream -p "梳理当前目录的代码结构"
```

`--stream` 必须与 `--prompt` 配合使用。

## 恢复会话

将下方占位符替换为已有会话 ID：

```powershell
.\.venv\Scripts\python.exe -m novacore --resume SESSION_ID
```

会话数据保存在项目的 `.novacore/` 下；请保留需要恢复的记录，避免将可能包含私有内容的会话文件提交到 Git。

## MCP 与权限

```powershell
.\.venv\Scripts\python.exe -m novacore --mcp-config novacore/examples/mcp.example.json
.\.venv\Scripts\python.exe -m novacore --help
```

MCP 示例配置需根据自己的服务地址与启动环境调整后使用。可选权限模式以帮助输出为准；不建议对不受信任的任务绕过权限确认。
