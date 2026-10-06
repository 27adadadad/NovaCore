# NovaCore 启动入口修复设计

## 范围与约束
用户已确认修复启动入口并开展离线交互验证，并要求默认采用推荐操作；问答阶段保持暂停。
复用干净的 codex/novacore-evidence worktree，不修改其他分支，不推送或合并。
不读取密钥，不调用付费模型，不改模型协议、Agent 工具循环、检索算法或会话格式。

## 方案选择
推荐标准包目录：把现有业务模块与子包原样移动到 novacore/，保留 benchmarks/ 和 tests/ 在仓库根。
替代方案是根目录导入壳（保留特殊导入路径）或仅安装旧平铺映射（源码直接启动仍不统一），均不采用。
源码重定位必须保持未改业务文件的字节一致；模块名称 novacore.* 不变。
删除测试和基准手动伪装包的逻辑，以真实源码包运行。构建配置仅发现 novacore 包，保留内置 Agent Markdown 和示例资源。

## 命令入口
保留 async main() 的现有业务，新增 def cli(): asyncio.run(main())；模块启动与终端脚本都进入 cli。
--help、非法参数和缺少密钥三个场景分别验证：正常帮助退出 0、参数错误退出 2、缺少配置时输出不含 traceback 的错误并退出 1。
缺少密钥校验只在 normal run 路径发生，离线示例不得调用 load_config。

## 离线交互
增加独立示例模块，使用已有 FakeClient、真实 Agent/ReadFile/ConversationManager/SessionManager 和 TemporaryDirectory。
流程是模型模拟请求 → 真工具读取临时样本 → 结果反馈 → 最终回答 → 会话落盘与恢复配对校验。
示例不是在线效果评测，不宣称真实模型理解或计费指标。

## 验收
先观察新子进程测试因找不到 novacore 失败，再修复；现有 23 项测试保持通过。
验证仓库根 python -m novacore --help、离线示例、wheel 构建及隔离环境已安装脚本帮助。
对实际测试条目计数，不人为凑数量；ToolSearch 现有评测口径缺陷保留为已知限制。
