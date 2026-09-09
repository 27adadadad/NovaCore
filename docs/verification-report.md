# 验证报告

日期：2026-09-09
分支：`codex/novacore-evidence`，基线为 `feat/agent-resume-alignment`

## 命令与结果

```text
python -m pytest tests -q
23 passed in 1.02s
```

测试全部离线执行，使用 Fake SDK/FakeClient 和 pytest 临时目录，覆盖：

- 多个流式 tool-call index 交错返回、名称/参数分片、非法/截断 JSON、缺少 id/name；
- ToolSearch 同义表达、发现后下一轮暴露 schema、无匹配处理；
- 上下文压缩后的 tool use/result 配对；
- Session 保存恢复与 deferred 工具恢复；
- 自动记忆、权限、危险命令、路径沙箱和 Worktree 隔离。

基准命令：

```text
python -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --queries benchmarks/fixtures/tool_search_queries.json --output benchmarks/results/tool_discovery.json
python -m json.tool benchmarks/results/tool_discovery.json
```

结果文件可解析。20 条查询的真实 `ToolSearch.execute()` 结果：

```text
baseline: target_hit=6, target_miss=11, false_activation_queries=0, correct_no_match=3, failures=11
improved: target_hit=17, target_miss=0, false_activation_queries=1, correct_no_match=2, failures=1
improved failure: no-match-rocket -> SendEmail was activated by the broad word "send"
```

载荷边界：

```text
full schemas: 25,545 bytes
full request wrapper: 25,555 bytes
tool catalog: 10,245 bytes
ToolSearch schema: 542 bytes
deferred request per query: 10,813–11,275 bytes, average 11,048.7 bytes
discovered schema per query: average 236.8 bytes
messages: excluded
```

字节/4 仅为近似 Token 展示，不是 provider 账单 Token，也没有推导费用、耗时或成功率收益。

## 当前限制

- ToolSearch 是固定目录上的词法检索和有限同义词归一化，不等同于向量或通用语义搜索。
- 仍保留 1 条可解释的误激活失败案例，评测结果没有把人工标注直接当作检索结果。
- 当前只支持 DashScope 的 OpenAI-compatible 接口；没有新增多供应商协议或显式 Plan→Execute 流程。
- 当前基线为扁平包布局；`python -m novacore` 从仓库根目录的导入限制未纳入本次修复。

## 可用于简历的表述

- 设计 deferred ToolSearch 评测链路：以 100 工具目录和 20 条人工标注查询为输入，调用真实 ToolSearch，统计命中、误激活、无匹配和按需载荷边界；改进策略命中 17/17 个有目标查询，并保留失败案例。
- 完善 AsyncOpenAI 流式 Function Calling 解析：按 tool-call index 缓冲交错 delta 和参数分片，在完整 JSON 后发出工具事件；离线测试覆盖非法/截断 JSON 与缺失 id/name。
- 完善上下文与会话管理验证：用临时目录测试压缩边界、tool use/result id 配对、Session JSONL 保存恢复和 deferred 工具恢复，完整测试集实际 `23 passed`。
