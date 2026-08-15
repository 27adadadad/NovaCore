# 验证报告

日期：2026-08-15  
分支：`feat/agent-resume-alignment`

## 命令与结果

```text
python -m pytest tests -q
15 passed in 1.48s
```

覆盖范围：自动记忆候选过滤与幂等写入、后台调度、配置开关、上下文工具调用配对、延迟工具发现 payload、危险命令、严格路径沙箱和 Worktree 隔离。

```text
100 工具 fixture，发现 3 工具
全量 schema：32,701 bytes / 8,175 近似 Token
已发现 schema：982 bytes / 246 近似 Token
节省比例：97.0%
```

Token 为 UTF-8 字节数除以 4 的近似值，并非 API 的实际账单 Token。

## 简历可用表述

- 自动记忆：任务完成后异步提取稳定信息；候选经 JSON 校验、敏感信息过滤和标题幂等更新后，写入用户/项目双作用域长期记忆。
- 延迟工具发现：固定 100 工具基准中，激活 3 工具时 schema payload 由约 8.2k 降至约 0.25k 近似 Token。
- 上下文压缩：历史摘要压缩并保留近期消息，且测试验证工具调用与工具结果不会被拆开。
- 多 Agent：teammate 在独立 Git Worktree 内运行，严格路径沙箱拒绝访问兄弟 Worktree。

## 不应写入简历的表述

- 不支持 Anthropic 协议，不应写多供应商协议适配。
- 未实现显式 Plan Mode，不应写 Plan → Execute 双模式。
- 当前压缩不是“已验证的两层压缩”，不应写两层渐进式压缩。
- 未完成端到端吞吐压测，不应写“效率成倍提升”或“突破单 Agent 上下文窗口”。

