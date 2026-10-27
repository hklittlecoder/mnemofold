# 架构总览

mnemofold 是一条从"原始工作事件"到"带引用的助手输出"的确定性管道。
所有阶段都可以离线运行：合成数据由内置工厂生成，指标全部来自带植入
真值（planted ground truth）的实验。

## 数据流

```text
合成工作历史 (factory)
        │  SyntheticEvent → Event（内容寻址 id）
        ▼
摄入管道 (ingest)
        │  情节分段 / 实体解析 / 承诺与决策提取（带 evidence span）
        ▼
记忆分层 (memory)                    工作流图 (graph)
        │  working / episodic /            │  节点 + 类型化边
        │  semantic / procedural           │  结构不变量校验
        ▼                                  ▼
折叠巩固 (fold) ──── 冲突消解 (conflict) ── 时间模型 (temporal)
        │  近重复合并 / 复发挖掘 → 剧本      │  区间有效事实 / as-of 查询
        ▼                                  ▼
衰减遗忘 (decay)                    检索 (retrieval)
        │  保留曲线 / 受保护记录            │  BM25 + MMR + 引用载荷
        ▼                                  ▼
                        上下文打包 (context)
                        │  token 估算 / 0-1 背包 DP / 预算约束
                        ▼
        助手层：台账 (ledger) · 分诊 (triage) · 会议准备 (prep)
                站立会与周报 (review) · 主动触发 (triggers)
                        │
                        ▼
        报告 (reports)：Markdown / 自包含 HTML / 自绘 SVG
```

横切所有阶段的支撑设施：

- **存储基底 (storage)**：追加式 SQLite 日志，哈希链校验帧，可从日志重建投影
  （详见 [storage.md](storage.md)）
- **录制回放 (replay)**：校验和 JSONL 追踪，字节一致的回放与检查点恢复
- **策略与隐私 (privacy)**：PII 检测、脱敏、分层读写规则、访问日志
- **删除语义 (deletion)**：right-to-forget 级联与墓碑，防止已删内容复活
- **工具与计划 (tools / plan)**：声明式工具规范（带能力标签、副作用分级、
  幂等键、超时与重试抖动）、DAG 校验的计划与 perceive-plan-act-observe
  循环，以及步骤 / token / synthetic-money 三重预算与 `budget_snapshot()`
  进度查询
- **审批 (approvals)**：待审批队列、角色化审批者、升级链
- **评估 (evaluation)**：对植入真值的 recall/precision、预算遵循、引用有效性等
- **显著性 (salience / salience_torch)**：NumPy 透明特征评分；可选 torch MLP 对照

## 核心不变量

| 不变量 | 守护方式 |
| ------ | -------- |
| 字节确定性 | 相同 seed + 配置 → 相同事件、追踪与摘要；回放与实时运行逐字节一致 |
| 预算约束 | 上下文包永不超预算（0/1 背包精确 DP，小规模实例对拍暴力解） |
| 删除不复活 | 墓碑索引阻断一切查询路径；属性测试覆盖检索/图/投影 |
| 隐私分层 | 高层级内容永不下泄；策略引擎带优先级与冲突诊断 |
| 引用可解析 | 报告与检索结果引用的 memory id 必指向存在且未删除的记录 |
| as-of 稳定 | 后续巩固/折叠不改变历史 as-of 查询的答案 |
| 折叠幂等 | 对同一存储重复折叠不产生新变化 |

## 确定性设计

- 所有随机性来自显式 seed（`random.Random` / NumPy 默认生成器），禁止读取系统熵
- 时间来自合成时钟或事件时间戳，不读取墙上时钟
- 序列化统一使用 sort_keys 的紧凑 JSON；浮点在产生点量化（`round(x, 6)`）
- 集合遍历前排序（按 id 或确定性键），避免哈希序泄漏到输出

## 分层理由

记忆分层的概念参考了 MemGPT 的分层内存设计（Packer et al., 2023）与
Generative Agents 的记忆流评分（Park et al., 2023：recency / importance /
relevance 三因子）。mnemofold 自行实现了这些机制：显著性特征全部透明可
检查（NumPy 路径），检索采用经典 BM25（Robertson & Zaragoza, 2009）与
MMR 多样化重排（Carbonell & Goldstein, 1998），遗忘曲线遵循 Ebbinghaus
指数衰减形式。时间有效性采用时态数据库的区间语义（valid_from / valid_to
与 as-of 快照查询）。

这些机制的共同点是**可验证**：每条记忆携带来源（provenance），每次合并、
取代、删除都留下可审计的记录，评估数字全部来自合成实验而非主观判断。

## 模块依赖方向

依赖只允许从外层指向内层：

```text
cli / examples / evaluation
    → 助手层 (ledger, triage, prep, review, triggers)
    → 认知层 (fold, conflict, decay, retrieval, context, playbooks, plan)
    → 基础层 (memory, graph, temporal, ingest, salience)
    → 地基层 (events, clock, storage, replay, privacy, deletion, tools, approvals)
    → factory（仅测试与演示数据）
```

`factory` 只被测试、示例、评估与 CLI demo 使用，核心管道不依赖它——
这保证框架可以接入真实事件源，而合成工厂只承担离线验证的职责。


## 完整性与持久化层

### 哈希链

框架内所有追加式记录都带 SHA-256 链，任何编辑、重排或截断都可被检出：

| 记录 | 位置 | 校验入口 |
| --- | --- | --- |
| 日志帧 | `journal.db`（SQLite） | `Journal.audit_chain` / `verify_chain` |
| 行为 trace | `trace.jsonl` | `TraceReader.verify`（打开即校验，篡改即拒绝恢复） |
| 工具收据 | `ReceiptLog` | `verify_chain(head)` / `digest()` |
| 访问日志 | `AccessLog` | `verify()` / `export_jsonl` + `import_jsonl`（导入时逐行验链） |
| 触发日志 | trigger log | `write_trigger_log` / `read_trigger_log` |

### 版本化持久化 envelope

`mnemofold.persist` 统一落盘格式：`{schema, schema_version, payload}`，
canonical JSON 字节确定。schema 或版本不符一律抛 `PersistError`——
陈旧文件永远不会被静默误读。已登记 schema：`bm25_index`、
`temporal_store`、`redaction_vault`、`approval_queue`、`plan`、
`playbook_library`，每个都有 golden 字节测试冻结。

### 四层工作区审计

`Workspace.verify_integrity()`（CLI：`mnemofold verify`）只读地交叉验证：

1. `journal_chain` — 日志帧链完整；
2. `trace_chain` — 行为 trace 链完整；
3. `no_resurrection` — 绕过守卫直接探查存储，确认没有墓碑键复活；
4. `projection_stable` — 投影摘要连续两次计算一致。

删除遵循 **preview → execute → audit** 模式：`forget_preview` /
`DeletionEngine.preview` 先给出与真实执行逐条一致的干跑计划，
执行后 `DeletionReport`（JSON/Markdown）留档。

### 会话汇总

`Workspace.session_summary()`（CLI：`mnemofold session`）把 stats、
完整性检查、台账账龄、日志计数与 trace 摘要聚合为一份 JSON 安全的
交接报告，全程只读、不查墙上时钟（时间锚定在最新日志事件）。
