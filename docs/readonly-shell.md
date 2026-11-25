# 只读能力与 Shell 授权边界

分析Issue/PR时以 `python -m novacore --read-only` 启动。默认普通编码模式保持可用，
不会仅凭用户自然语言自动切换；需要重启以选择只读能力集。

只读模式不注册Bash、WriteFile、Remember、RunProposalReview、Agent和Team工具，
不是仅隐藏schema；ToolSearch也无法重新激活未注册的工具。
保留项目内ReadFile/Glob/Grep、记忆读取、LoadSkill、证据采集/节点读取/引用校验。
Skill文本不能添加执行能力，旧会话的历史调用也不会恢复不存在的工具。
只读模式拒绝--mcp-config，避免把外部服务器自行声明的read类别误认为可靠安全约束。
自动长期记忆写入关闭；/team带参数的操作拒绝，避免通过恢复团队重新启动写入任务。
会话日志、证据包及登记表仍可由宿主保存，“只读”不是磁盘零写入。

普通模式仍提供Bash，但在PermissionChecker中始终返回ask；default、acceptEdits、
bypassPermissions均不能自动批准。执行前继续保留危险命令规则。界面显示命令、实际
Shell、cwd，并提示可访问项目外文件、网络和进程；交互确认仅对本次调用有效。
交互入口使用请求参数的深拷贝，避免等待确认期间被调用方替换命令。
非交互Agent路径遇到ask直接拒绝；需要执行Shell时改用交互式入口确认，不使用
bypassPermissions逃过授权。本次不新增预授权令牌或“以后全部允许”。

兼容性：工具协议不变，create_default_registry新增可选read_only参数；
既有依赖bypassPermissions自动执行Bash的脚本会变为拒绝，需要调整操作方式。
直接调用Bash.execute或ToolRegistry.execute的宿主代码不经过Agent权限检查，
它们不是不可信调用接口，不代表可以宣称全局进程级保护。

重要限制：本次是运行时能力移除和授权修复，不是操作系统沙箱。用户批准后，
Shell仍以当前账号权限运行，cwd不约束文件访问。未增加进程树强杀、网络隔离、
容器、通用长输出配额或副作用回滚。这些需要后续独立设计，不能靠路径正则替代。
