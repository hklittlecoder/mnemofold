# 存储基底：日志、迁移与投影

`mnemofold.storage` 是整个框架的地基：所有持久状态都从一条追加式
(append-only) SQLite 日志推导而来。本页说明其设计与不变量。

## 哈希链日志

每个事件写入 `frames` 表的一行，包含：

- 单调递增的 `seq`（AUTOINCREMENT 主键）
- 完整的事件 envelope JSON 与内容校验和
- `prev_chain_checksum` / `chain_checksum`：SHA-256 哈希链

链式校验和的计算方式为
`chain = SHA-256(prev_chain || "\n" || envelope_json)`，
创世值由固定常量 `mnemofold_genesis_v1` 派生。任何截断、篡改或
重排都会使后续所有帧的校验失败。

`verify_chain()` 回答"链是否完整"；`audit_chain()` 进一步报告
第一个损坏帧的 `seq` 与已检查帧数，供修复工具与 CLI 审计使用。
链算法的输出由 golden fixture（`tests/fixtures/journal_chain_golden.json`）
钉死，任何漂移都会导致测试失败，从而保证跨版本可比对。

## 原子性与崩溃恢复

- 单条 `append` 与批量 `extend` 都运行在 `BEGIN IMMEDIATE` 事务中；
  `extend` 是全有或全无的：批内任何失败都会整体回滚，日志保持原状。
- 重复 `event_id` 静默跳过且不破坏链的连续性。
- 连接被丢弃（模拟进程崩溃）后重新打开，WAL 模式保证已提交帧全部
  可见，链继续从原 head 延伸。相应行为由
  `tests/test_storage.py::TestInterruptedWrites` 覆盖。

## 模式迁移

`schema_meta` 表记录当前 schema 版本。打开日志时：

1. 版本比代码新 → 直接报错（防止旧代码写坏新库）；
2. 版本落后 → 按 `MIGRATIONS` 注册表逐级执行迁移增量
   （例如 v2→v3 增加 `tombstones` 表）；
3. 缺少某一级迁移 → 报 `no migration path` 硬错误，绝不静默跳级。

新建库直接使用最新 schema 快照；迁移只服务于既有旧库，两者由同一
组测试（含"手工构造的 v2 库"）双向验证。

## 墓碑 (tombstones)

删除语义（right-to-forget，参考 GDPR 的擦除权要求）在日志层以墓碑
实现：`record_tombstone()` 写入标记而非删除帧，哈希链保持可验证，
所有消费方（检索、图、投影）都必须检查墓碑并阻止已删内容复活。
首条墓碑生效（first write wins），按 `event_id` 排序可确定性遍历。

## 投影：日志是唯一事实来源

图、索引、统计等都是派生状态，通过 `Journal.project(factory)` 从
日志重建：按 `seq` 顺序把每个事件折叠进一个 `Projection`
（`apply(event)` + `digest()`）。核心不变量是**双跑一致**：同一日志
折叠两次、在两个库实例上折叠、或重开后折叠，digest 必须逐字节相同
——`EventStatsProjection` 是参考实现，相关性质在测试中硬性验证。

## 与其他模块的关系

- `events`：envelope 与内容寻址 id 的序列化契约（日志只存 envelope）
- `deletion`：在墓碑之上实现级联删除与防复活审计
- `replay`：追踪录制复用同样的校验和纪律，保证回放字节一致

上游概念参考：事件溯源与追加式日志的通用模式、时态数据库中
"事实随时间演进但历史不丢失"的语义（详见 docs/architecture.md 的
引用列表）。本页描述的实现与 schema 均为本项目自有设计。
