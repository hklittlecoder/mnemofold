# API 参考

按架构分层（见 [architecture.md](architecture.md)）组织的核心 API 速查。
所有公开类型均为 dataclass 或普通类，带完整类型标注；示例片段可直接运行
（离线、合成数据）。

## 地基层

### `mnemofold.events`
- `Event(event_type, timestamp, content)` — 内容寻址的不可变事件；
  `event_id` 由类型+时间戳+内容的 SHA-256 派生。
- 便捷构造器：`Event.mail_received / mail_sent / meeting_scheduled /
  meeting_held / note / task_update / document_change / chat_message /
  commitment_ack / focus_block`。
- `to_envelope() / from_envelope() / to_json() / from_json()` — schema
  版本化序列化，反序列化时校验 `event_id` 与 `content_checksum`。
- `EventStore(path)` — 追加式 JSONL 事件存储。

### `mnemofold.storage`
- `Journal(path)` — 哈希链 SQLite 日志：`append / extend / get /
  iter_events / frame_info / verify_chain / audit_chain / head_checksum /
  record_tombstone / tombstone / project`。
- `TraceRecorder.resume(path)` 语义同样适用于日志重开：链自动续接。
- `MIGRATIONS` — 版本化 schema 迁移注册表；缺级即硬错误。

### `mnemofold.clock`
确定性合成时钟与时区安全日分桶（含 DST 边界）。

### `mnemofold.temporal`
- `IntervalFact(fact_key, value, valid_from, valid_to=None)` — 区间有效
  事实；比较按时间点进行（跨时区偏移安全）。
- `TemporalStore` — `add / current / as_of / history / staleness / keys`。
- `StalenessPolicy.classify(store, key, now)` → fresh/aging/stale/expired。
- `IntervalValidator().validate(store)` — 检测同键重叠区间。
- `CalendarRegistry.with_defaults()` — hk/us/de 工作日历；
  `WallDeadline.instant() / is_overdue() / rolled_to_workday()`。

### `mnemofold.privacy`
- `detect_pii(text)` → `PiiMatch` 列表（email/phone/card(Luhn)/address/name）。
- `redact(text, matches, mode)` — MASK / HASH / REMOVE。
- `RedactionVault(salt).seal / unseal` — 可逆脱敏。
- `can_read / can_write / can_export / export_violations` — 分层规则。
- `PolicyEngine.evaluate / explain` — allow/deny/ask 判定与逐规则解释。
- `AccessLog.record / verify / head_hash` — 哈希链访问日志。

### `mnemofold.deletion`
- `DeletionEngine(get_target, delete_item, is_protected)` — 级联删除 +
  墓碑；`delete()` 返回 `DeletionReport`（deleted/blocked/errors）。

### `mnemofold.tools`
- `ToolSpec(name, description, side_effect, parameters, required,
  timeout_seconds, max_retries, idempotent, capabilities)` + `to_schema()`。
- `ToolRegistry.register / invoke / validate_args / list_tools / schemas`；
  可选 `policy=ToolPolicy(...)`、`idempotency=IdempotencyStore()`、
  `receipts=ReceiptLog()`、`enforce_timeouts=True`、`rng_seed=N`。
- `ToolReceipt / ReceiptLog.to_jsonl / from_jsonl / digest`。

### `mnemofold.approvals`
- `ApprovalQueue.submit / decide / tick / escalate / auto_resolve /
  audit_metrics`；`Approver(persona=AUTO_APPROVE|AUTO_DENY|ASK|RANDOM)`。

## 基础层

### `mnemofold.ingest`
- `EpisodeSegmenter(segment config) / SegmentConfig` — gap 或 day 模式分段。
- `CommitmentExtractor / DecisionExtractor / DocumentReferenceExtractor` —
  全部返回带 `EvidenceSpan` 的 mention，`resolves_in(event)` 双向可验。
- `AliasTable.merge / merged_into / merge_history`。
- `IngestPipeline().run(events)` → `IngestResult`（episodes/entities/
  commitments/decisions/documents + `digest()`）。

### `mnemofold.memory`
- `MemoryItem / MemoryStore`（`add / get / peek / remove / promote /
  demote / apply_policy / record_access / under_retention`）。
- `TierPolicy / PolicyReport` — 声明式晋升降级。

### `mnemofold.graph`
- `WorkstreamGraph.add_node / add_edge / neighbors / nodes_by_type /
  check_no_dangling_edges / check_provenance_acyclic / to_dict / from_dict`。

### `mnemofold.salience`
- `SalienceScorer.score / feature_vector`；`FEATURE_NAMES` 为 NumPy 与
  torch 路径共享的规范特征序。
- `SalienceDiagnostics.describe / slice_means / feature_correlations`。
- 可选 `mnemofold.salience_torch`（`torch` extra）：`SalienceMLP(seed=...)`、
  `train_salience_model`、`compare_to_baseline`。

## 认知层

### `mnemofold.fold`
- `Folder(similarity_threshold, min_episodes_for_recurrence).fold(store,
  timestamp)` → `FoldReport`（merges/rejected/new_semantic/recurrence_
  proposals；`to_markdown() / digest()`）。

### `mnemofold.conflict`
- `ConflictResolver.resolve / apply_resolution / audit_report`；
  `corroborate(evidences)` 聚合佐证；`ConflictDetector.scan /
  scan_and_apply` 扫描时态库重叠冲突。

### `mnemofold.decay`
- `DecayEngine.apply_decay / simulate / snapshot / place_hold /
  release_hold / property_protected_never_deleted`。

### `mnemofold.retrieval`
- `RetrievalEngine(store, graph=None)`：`index_item / build_index /
  search / search_parsed`（支持 `fusion`、`as_of`、`expand_graph`）。
- `parse_query("...")` → `ParsedQuery`；`FusionWeights / fuse_score`；
  `mmr_rerank`；`build_deletion_engine / forget / safe_index`。

### `mnemofold.context`
- `ContextPacker(budget, profile, ordering).pack(items)` → `ContextPack`
  （精确 0/1 背包 DP；`to_markdown()`）；`effective_priority`；
  `BudgetExceededError`；`verify_budget / verify_dp_vs_greedy`。

### `mnemofold.plan`
- `Plan / PlanStep / validate_plan / topological_order / diff_plans`。
- `PlanLoop(plan, approvals=None, now=None).run_to_completion(registry)` —
  token/money/step 预算、审批门控（deferred/denied）、precondition 门控、
  effects 写入 `loop.world`、`$step.output` 引用解析。

### `mnemofold.playbooks`
- `PlaybookLibrary.add / suggest / approve / activate / revoke /
  create_revision`；`Playbook.to_dict / digest`。

## 助手层

### `mnemofold.ledger`
- `Commitment / CommitmentLedger`（`transition / overdue / upcoming /
  nudges / open_dependencies / blocked_commitments / all_commitments /
  remove / to_json / from_json / to_markdown`）。

### `mnemofold.triage`
- `TriageScorer.score / batch_score / apply_quiet_hours`；
  `TriageBatcher.batch` → `BatchPlan(act_now/review/defer)`；
  `attach_graph_importance(items, graph)`；`precision_at_k`。

### `mnemofold.prep`
- `MeetingPrepper(store).prepare(...)` → `MeetingPrep`（证据式议程、
  `to_markdown / to_html`）；`measure_coverage(prep, planted_ids)`。

### `mnemofold.review`
- `StandupGenerator(ledger).generate(today)`；
  `WeeklyReviewGenerator(ledger).generate(start, end)`；
  `render_standup_markdown / render_standup_html / render_weekly_markdown /
  render_weekly_html`。

### `mnemofold.triggers`
- `TriggerEngine.add_rule / tick / active_triggers`；
  `write_trigger_log / read_trigger_log`（校验和 JSONL）。

## 顶层

### `mnemofold.workspace`
- `Workspace(path)` — journal + 投影 + trace 的持久工作区：
  `ingest_events / remember / forget / ask / recall / rebuild / stats /
  projection_digest`。重开即重建，双跑 digest 必须一致；墓碑阻断复活。

### `mnemofold.evaluation`
- 指标原语：`precision / recall / f1_score / precision_at_k /
  budget_adherence / citation_validity / overdue_detection_accuracy /
  stale_fact_avoidance / as_of_accuracy / deletion_resurrection_check /
  privacy_violation_count / coverage_score / replay_determinism_score`。
- 场景：`run_commitment_scenario / run_triage_scenario /
  run_asof_scenario / run_privacy_deletion_scenario /
  run_commitment_slices / run_suite(ScenarioConfig)`。

### `mnemofold.reports`
- `render_timeline_svg / render_workload_strip / render_fold_summary_svg /
  render_metric_table / wrap_html / assemble_report_page`。

### `mnemofold.factory`
- `WorkHistoryFactory(seed, days, config=FactoryConfig(...))` —
  `generate()` 返回 `(events, manifest)`；`planted_items()` 提供真值。

### CLI
`mnemofold <subcommand>`：ingest / ask / recall / remember / forget /
export / standup / review / playbooks / ledger / triage / fold / asof /
context / prep / privacy / triggers / replay / diff / eval / demo /
version。`mnemofold <subcommand> --help` 查看参数；退出码：0 成功、
1 操作性错误、2 校验失败。
