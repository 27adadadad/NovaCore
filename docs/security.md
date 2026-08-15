# 工具治理边界

NovaCore 在工具执行前依次经过 Hook、危险命令检测、路径沙箱和权限模式判断。

| 层 | 作用 | 边界 |
|---|---|---|
| Hook | 在调用前后执行自定义规则；可拒绝调用 | Hook 规则由宿主配置，不是强制 OS 隔离 |
| 危险命令检测 | 拦截已知高风险命令模式 | 正则规则不能覆盖所有危险命令组合 |
| PathSandbox | 将读写路径解析后限制到项目根目录 | 仅保护接入该检查器的文件工具 |
| PermissionMode | 按 read/write/command 返回 allow、ask、deny | `bypassPermissions` 应只用于受控环境 |
| 交互确认 | 对 ask 的调用要求用户批准 | 非交互模式无法批准，会拒绝该调用 |

Team teammate 强制设置 `enforce_sandbox=True`，因此即使采用 `acceptEdits`，也不能写入主仓库外或兄弟 Worktree。

这是一组应用层防线，不替代容器、虚拟机或操作系统级沙箱。
