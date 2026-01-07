# 工件 Schema 参考

mnemofold 的每个序列化工件都有明确的版本或稳定的字段布局，漂移必须是
有意为之：所有结构都有 roundtrip / golden 测试固定。本页汇总各工件的
字段与定义位置。

## 事件 envelope（`schema_version = 1`）

定义：`src/mnemofold/events.py`（`Event.to_envelope` / `Event.from_envelope`）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | int | 当前为 1；不匹配的 envelope 直接拒绝 |
| `event_id` | str | 内容寻址 id，由 payload 推导 |
| `event_type` | str | `EventType` 枚举值（如 `note`、`mail_received`） |
| `timestamp` | str | ISO-8601 instant |
| `content` | dict | 事件负载（字符串键） |
| `content_checksum` | str | payload 的 SHA-256 |

`from_envelope` 会重算并校验 `event_id` 与 `content_checksum`，被篡改的
envelope 无法通过反序列化。JSONL 行是 envelope 的 canonical JSON
（`sort_keys`、紧凑分隔符、ASCII）。

## 日志帧（journal `SCHEMA_VERSION = 3`）

定义：`src/mnemofold/storage.py`。

- `frames`：`seq`、`event_id`（UNIQUE）、`event_type`、`timestamp`、
  `envelope_json`、`content_checksum`、`prev_chain_checksum`、
  `chain_checksum`、`created_at`；
- `tombstones`（v3 新增）：`event_id`、`reason`、`deleted_at`；
- `schema_meta`：`schema_version` 键值。

链式校验和 `chain = SHA-256(prev_chain + "\n" + envelope_json)`，创世值由
固定种子字符串派生。`MIGRATIONS` 注册表按版本逐级升级；缺少迁移步骤是
硬错误而不是静默漂移，高于当前代码版本的日志会被拒绝打开。

## 工作流图 dict

定义：`src/mnemofold/graph.py`（`WorkstreamGraph.to_dict` / `from_dict`）。

```json
{
  "nodes": [{"node_id": "...", "node_type": "project", "label": "...",
             "properties": {}, "active": true}],
  "edges": [{"edge_id": "...", "edge_type": "owns", "source_id": "...",
             "target_id": "...", "properties": {}, "active": true}]
}
```

节点按 `node_id`、边按 `edge_id` 排序输出，序列化是确定性的；golden 测试
固定了完整 payload。

## 折叠报告（fold report）

定义：`src/mnemofold/fold.py`（`FoldReport.to_dict` / `digest` /
`to_markdown`）。字段：`fold_id`、`timestamp`、`items_before`、
`items_after`、`merges[{kept_id, removed_id, reason, similarity,
provenance}]`、`rejected[{a, b, similarity, reason}]`、`new_semantic`、
`recurrence_proposals`。`digest` 是 canonical JSON 的 SHA-256，
similarity 一律量化到 1e-6，保证跨平台稳定。

## 回放 trace 行

定义：`src/mnemofold/replay.py`。每行 JSON：

```json
{"hash": "<sha256(prev_hash + canonical(entry))>",
 "entry": {"kind": "event|decision|recall|receipt|checkpoint",
           "timestamp": "...", "entry_id": "...", "payload": {}}}
```

哈希链从 64 个 `0` 起步；`TraceReader.verify` 逐行重算，任何篡改或截断
都会失败。续写已有文件时会先接管链头（`head()`）。

## 触发器日志（trigger log）

定义：`src/mnemofold/triggers.py`（`fired_to_dict` /
`write_trigger_log` / `read_trigger_log`）。JSONL 每行对应一个
`FiredTrigger`：`rule_id`、`kind`、`target_id`、`fired_at`、`severity`、
`message`、`suppressed`、`suppress_reason`。写读往返由测试固定。

## 台账 JSON（ledger）

定义：`src/mnemofold/ledger.py`（`CommitmentLedger.to_json` /
`from_json`）。`{"commitments": [...], "history": [...]}`：commitment 按
id 排序，字段含 `commitment_id`、`owed_by`、`owed_to`、`description`、
`due_date`、`status`、`priority`、`grace_hours`（量化 1e-6）、
`created_at`、`updated_at`、`source_event_ids`、`depends_on`、`tags`
（排序）、`metadata`；history 记录每次状态迁移。

## 工作区快照与 diff

定义：`src/mnemofold/workspace.py`（`Workspace.snapshot` /
`diff_snapshots`）。快照：`memories`（按 tier 分组的排序 id 列表）、
`commitments`（id → status）、`tombstones`、`head`（日志链头）、
`digest`（投影 SHA-256）。diff：`memories.added/removed`（按 tier）、
`commitments.added/removed/status_changes`、`tombstones_added`、
`digest_changed`、`empty`。

## 其他带 roundtrip 保证的工件

- 上下文包：`context.ContextPack`（items、total_tokens、budget、
  profile、ordering），选择结果由精确 0/1 背包 DP 给出，`knapsack_brute_force`
  作为小规模实例的最优性参照；
- 计划：`plan.Plan.to_dict` / `digest`（canonical JSON SHA-256）；
- 剧本：`playbooks.Playbook.to_dict` / `digest`；
- 评估记分卡：`evaluation.Scorecard`（scenario、metrics、details），
  聚合顺序固定。

以上工件的字段级 golden 测试位于 `tests/test_*_golden.py` 与各模块测试中；
修改任何字段都应同时更新对应 golden 与本页。


## 持久化 envelope（`mnemofold.persist`）

落盘工件统一使用自描述 envelope，字节级确定（键排序、紧凑分隔符、
ASCII 转义）：

```json
{"schema": "<名称>", "schema_version": <整数>, "payload": { ... }}
```

`parse_envelope` / `read_envelope` 在 JSON 损坏、schema 名不符、版本
不匹配或 payload 非对象时抛出 `PersistError`——陈旧文件不会被静默误读。
当前登记的 schema：

- `bm25_index`（v1）：`{"k1", "b", "docs"}`。`docs` 为按 id 排序的
  全量文档表；倒排结构是文档的纯函数，`BM25Index.save/load` 重建后
  检索与 explain 结果与保存前一致（有 restart parity 测试）；
- `temporal_store`（v1）：`{"facts": [...]}`，事实按插入顺序保存
  （`current` 的并列判定依赖顺序），字段为 fact_key / value /
  valid_from / valid_to / metadata；
- `redaction_vault`（v1）：`{"salt", "tokens"}`。tokens 含明文映射，
  与原文同等敏感，只应写入受信任存储。

每个 schema 的 golden 字节冻结在 `tests/fixtures/*_golden.json`；
新增可持久化工件时应登记 schema 名、补充 golden，并更新本页。
