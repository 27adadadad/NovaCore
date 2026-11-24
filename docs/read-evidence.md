# 按节点读取证据，不再整包打印

`CollectDevEvidence` 保存证据后返回 `artifact_id`。主CLI的采集工具和
`ReadEvidence` 共享绑定真实session_id的登记表。模型只传ID，不传文件路径。
`ReadFile` 的项目内路径限制不变，不应以Bash/type/cat绕过读取限制。

## 先列目录，再选择

```json
{"artifact_id":"artifact-<32位随机标识>","action":"list","offset":0,"limit":10}
```

目录返回节点ID、类型、文件名、提交、来源和可用字段，不返回正文。
如存在next_offset，用它继续列举。目录不是已完成阅读的证据。

```json
{"artifact_id":"artifact-<32位随机标识>","action":"read","node_id":"E9","field":"content","start_line":1,"start_column":0,"max_lines":100}
```

field可以为content（正文）、patch（差异）、metadata（节点载荷中非正文/差异字段）。
节点没有该字段时返回错误，不自动切换。使用返回的next_cursor继续读取；行号从1开始，
列是从0开始的Unicode字符偏移。超长单行也能分段续读，不静默丢弃中间文字。
`eof=true`只表示选定字段读到末尾，不证明之前的片段或其他节点已读，不保证业务正确。
来源、提交、覆盖缺口摘要随每次返回提供，外部正文始终标为不可信证据。

## 隔离、恢复与限制

- 采集产物保存到用户目录 `.novacore/evidence/<session_id>/<artifact_id>`。
- session目录登记bundle文件SHA256，原子更新registry.json；仅登记成功后返回ID。
- 同一session恢复可重新读取登记内容。其他session、未登记ID、篡改内容拒绝读取。
- 文件和祖先路径拒绝符号链接及Windows reparse点，不接受任意磁盘路径。
- 单包最多2MiB，每会话最多128个登记条目，单次返回最多16KiB；正文采用更小预算为元数据留空间。
- 当前每次读取在程序内部加载有界bundle，分段控制的是模型返回大小，不是随机访问大型文件。
- 历史旧版证据包不自动导入，不依据聊天里提供的路径授权访问；需重新采集或以后增加人工批准导入。
- 这是应用层范围控制，不是操作系统沙箱；拥有本机写权限者可以修改登记表和产物。
  检查路径不构成对恶意并发文件替换的完整防护。多进程同时写同一session登记表尚无文件锁。
- 没有修复通用Bash隔离，也没有实现所有工具长输出落盘；累计阅读仍可能占满上下文。
- 会话消息持久化缺陷是独立问题，本次不宣称已经修好。登记表不依赖模型摘要恢复。

原有bundle/report路径暂时保留在采集返回值中供用户手动检查；模型的推荐入口是artifact_id。
重启NovaCore加载新工具。只读工具不请求模型，主对话仍可能产生模型费用。
