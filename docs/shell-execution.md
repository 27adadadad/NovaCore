# 命令执行环境与反馈

为保持现有调用协议，命令工具仍名为 `Bash`，参数仍为 `command`、`timeout`。
这不表示它一定执行 Linux Bash。

工具 schema 的 description 提供宿主实际操作系统、Shell路径、工作目录、
Python解释器路径和版本。Windows 显式使用系统目录的 cmd.exe，POSIX 使用
/bin/sh；不能因为终端窗口是 PowerShell 就生成 PowerShell 语法。
每次命令都从工具绑定的工作目录启动，前一次 cd 不影响下一次命令。
路径是环境事实，不是用户提供的新指令；未收集时间戳、密钥或全部环境变量。

返回值为 JSON 字符串：

```json
{
  "status": "failed",
  "exit_code": 7,
  "stdout": "",
  "stderr": "",
  "cwd": "<working directory>",
  "shell": "<shell executable>",
  "operation_outcome": "process_exited",
  "reason": "Command returned nonzero exit status"
}
```

status 为 succeeded / failed / timed_out / spawn_error / execution_error。
非零退出码设置工具 is_error=true，因此现有任务计数能观察到失败，而不只依赖
模型从输出文字猜测。检查器的错误反馈和通用权限控制保持原状。
命令退出0只证明进程成功退出；例如 `missing-command || echo fallback` 的整体退出0
不表示前一个命令成功，stderr需同时阅读。调用方不能把工具正常返回当成业务验收通过。

取消时清理直属Shell并向Agent传播CancelledError，不伪造成功结果。
超时尝试保存已有stdout/stderr，结果标为unknown；清理只保证尝试停止直属Shell，
不保证其所有后代进程停止，不保证文件/网络副作用撤销。非幂等操作失败或超时需先核实结果，
不能因未达到重复失败阈值就自动原样重试。

兼容性：工具名称和输入schema不变，输出由普通文本变为JSON。
读取原始文本的脚本需解析stdout/stderr，不能再依赖旧的 `Exit code N` 文本后缀。
会话历史仍可读取，不会重写旧结果。需要重启NovaCore以加载新版代码。

限制：当前仍在内存中收集输出，尚未实现长输出受控落盘与读取；输出按UTF-8解码，
非UTF-8本地程序可能出现替代字符。环境事实帮助模型选命令，不保证模型一定遵守；
环境描述只在命令工具schema中，不是所有只读子Agent都拥有Shell工具。
