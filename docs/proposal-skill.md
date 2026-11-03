# 对话中使用 Proposer / Reviewer

启动 NovaCore 后，直接输入：

```text
加载 proposal-review Skill。修复 metrics.py 中空列表导致的除零错误，
只允许修改 metrics.py，先生成候选，再独立审核。
```

`LoadSkill` 的目录包含内置 `proposal-review`。主 Agent 根据需求调用
`RunProposalReview(task, allow_files)`，不需要用户填写解释器、输出目录或子流程命令。
当前项目由启动目录绑定；最多允许 5 个已提交 UTF-8 普通非可执行文件，总计 64 KiB。
允许文件有未提交编辑时拒绝，不会悄悄忽略这些编辑。Windows 的 CRLF/LF 换行差异可接受。

默认权限模式可能先询问是否允许工具操作。随后会单独展示需求、范围、源提交和任务目录：

```text
本次同意请输入 RUN，其他输入取消：
```

这是用户在终端的实际输入，不是发给模型的聊天消息。每个 Agent 最多 5 轮，
共享最多 10 次**额外模型请求**，主对话的模型请求另计。
即使主程序使用 `acceptEdits` 或 `bypassPermissions`，这个付费确认也不会跳过。
非交互输入不运行双 Agent；拒绝后不会自动重试。不要在命令或聊天中填写密钥。

任务保存在用户目录的 `.novacore/proposals/proposal-<随机标识>`，不写入产品仓库。
同一个入口运行时不并行启动第二项任务。两角色共享本次候选文件，不共享消息历史。

返回值提供任务目录、`changes.patch`、`agent-review.json` 和两个角色的 JSONL 对话记录。
审查完整结束后才有审查报告；失败时查看返回状态及已有轨迹，不应假定报告存在。
日志经过尽力脱敏，但并非完备的敏感信息检测；分享前自行检查。

- `reviewed_no_findings`：本轮未发现问题，不保证业务正确。
- `awaiting_human_selection`：审核发现问题，等待用户决定。
- `proposal_inconclusive` / `review_inconclusive`：本轮无法得出有效结论。
- `authorization_denied` / `authorization_unavailable`：未取得宿主授权，未请求子 Agent。
- `uncommitted_allowed_files`：允许文件和已提交版本不同，应先处理现有改动。

只生成独立候选，不覆盖原件，不自动提交、推送、合并或再次付费修订。
检查仅为语法/JSON检查，不执行项目代码、业务用例或任意Shell命令。
自然语言能否选中 Skill 和正确填写参数仍取决于主模型；需要确定性入口时可继续使用
原有 `python -m novacore.proposal_agents`。
