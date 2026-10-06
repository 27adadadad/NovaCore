# 启动与离线交互验证

日期：2026-10-06。分支：codex/novacore-evidence；修复前代码基线：dc1f10d。

## 原问题与处理

仓库平铺业务模块，而 tests/conftest.py 与基准用手工加载模拟 novacore 包，导致 23 项旧测试通过但普通模块启动失败。终端脚本还指向 async main，安装后不会自动执行协程。

将 61 个已跟踪业务/资源文件移动到标准 novacore/ 目录，搬移时逐项核对 SHA-256 不变；只有入口逻辑随后作必要修改。测试和基准改用真实包导入。同步 cli 调用 asyncio.run(main())，模块和终端脚本共享入口。只对配置错误作无 traceback 的提示，不吞掉 Agent 的运行异常。帮助和参数检查在配置读取前完成；界面与 MCP 模块在实际运行时加载。

setuptools 是已有构建工具：它按包发现配置生成 wheel，并把内置 Agent Markdown 与示例资源一起安装，不改变模型通信或 Agent 工具循环。源码位置变化是这次兼容性代价，导入名 novacore.*、运行数据路径和会话格式不变。

## 实际验证

- 新入口测试先观察到 4 项因找不到模块而失败，再修复至通过；离线示例测试先因缺少示例模块失败，再通过。
- 原有 23 项 + 新增 5 项 = 28 项测试实际通过。5 项新增用例覆盖模块帮助、终端入口函数帮助、非法参数、缺少密钥和离线交互。
- 基础环境：Python 3.13.12；28 passed in 11.21s。
- 项目 .venv（复用系统已有依赖）安装原有锁定版本后：28 passed in 11.35s。版本为 openai 2.46.0、pydantic 2.13.4、textual 8.2.8、mcp 1.28.1、PyYAML 6.0.3。全局环境未被修改。
- wheel 离线构建成功；在仓库目录外验证已安装 python -m novacore --help、novacore --help、离线示例和内置资源，均通过。不是仅依靠源码当前目录导入。
- 离线示例真实执行 ReadFile，两轮 FakeClient 调用后生成最终回答，保存和恢复 Session 后调用/结果 ID 配对一致。
- 独立无窗口 Textual 验证：/status 模型调用为 0；模拟流式工具交互为 2 轮，真实 ReadFile 结果显示，结束后输入框重新可用。使用 FakeClient 的测试适配器，不是在线服务。
- compileall 成功。
- 同一版本 ToolSearch 基准仍为 20 条查询、17/17 条目标命中、1 条误激活、2 条正确无匹配；本次没有改检索逻辑或修复其评测算法。

## 复现

在仓库根目录，按照 README 创建环境和安装，然后运行：

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m novacore --help
.\.venv\Scripts\novacore.exe --help
.\.venv\Scripts\python.exe -m novacore.examples.offline_smoke
~~~

本次机器结果保存在仓库外：
C:\Users\Administrator\Desktop\nova\test-results\novacore-startup-20261006-160801。
其中有 pytest.xml、pytest-pinned.xml、toolsearch.json、wheel/ 和独立 tui_smoke.py。
无窗口界面验证可用 .venv 的 Python 从仓库外执行该 tui_smoke.py。

## 限制

独立只读审查未发现 Critical / Important 阻塞问题；确认一项兼容性限制：未安装项目时，直接运行 benchmarks/tool_discovery.py 不再有旧版手动导入适配。README 明确采用已验证的模块入口 python -m benchmarks.tool_discovery。

未调用付费模型，未读取真实密钥；未验证在线模型质量、真实网络断流、真实 MCP 服务或完整生产运行。
当前 ToolSearch baseline 仍不是历史原算法，不能根据其中的 6/17 推导命中率提升。载荷模拟字段排除了消息体，不代表完整请求、Token、费用或时间收益。
中文检索、重复发现状态、工具异常后配对、完整压缩—保存—恢复链路的已知缺口未在本次修复。
本次修复只在本地独立分支实施，不自动推送、合并或清理 worktree。
