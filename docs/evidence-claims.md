# 证据事实和引用约束

采集包新增 collection_facts：每个PR的总改动文件数、实际采集改动文件数、
成功收集的上下文文档数、带具体文件名的省略记录数量。它们是不同口径，不能相加
当成PR改动数。总数来自GitHub元数据，不是证明所有文件都已查看。
PR节点metadata.collection_summary保留skipped_files；coverage.gaps同时保留file。
没有具体文件名的限制只表示范围不完整，不应猜测是某个已收录文件缺少片段。

兼容旧kind=code分类；payload.role=changed_file明确表示改动文件，可能是文档或配置。
上下文文档role=context_document。只有该路径在已收录改动列表中时，才能给出已知
change_status；否则unknown，不等于unchanged。上下文文档仍不自动成为验收标准。
旧包缺collection_facts时Reader返回facts_available=false，不反推PR总改动数。

## 引用校验

ValidateEvidenceCitations与ReadEvidence使用同一会话登记表，仅接受artifact_id。
每个reference包括node_id、commit_sha（节点无提交时明确传null）、field、
start_line、start_column、excerpt。行号从1开始、列按Unicode字符从0开始，
对metadata引用采用ReadEvidence返回的格式化JSON文字；patch位置是patch字段行号，
不是变更后源码行号。一次最多10条、单条原文最多2000字符、响应最多16KiB。

校验确认节点存在、提交匹配、指定位置的原文精确一致。不做模糊匹配，
不调用模型或网络，也不更改包。返回unknown_node/commit_mismatch/
invalid_location/excerpt_mismatch等原因。semantic_verification始终false。

模型输出应区分直接事实、推断和无法判断，并在引用错误时修正后再引用。
这是工具支持和Skill约束，不是所有自然语言结论的自动硬性审查门槛；
引用存在不等于结论成立，也不能证明模型确实阅读了全部内容。
