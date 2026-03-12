# 使用指南

mnemofold 是离线长期记忆框架：所有数据来自内置合成工厂（seeded、可复现），
所有输出带引用（citation），全部机制可在本机 CPU 上验证，无需网络、GPU
或任何外部服务。

## 安装

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
# 可选：训练演示（仅 CPU）
.venv/bin/pip install -e ".[dev,torch]" --extra-index-url https://download.pytorch.org/whl/cpu
```

## 核心流程（库用法）

从合成历史到带引用的助手输出，一条典型管道：

```python
from mnemofold.factory import WorkHistoryFactory, FactoryConfig
from mnemofold.ingest import IngestPipeline
from mnemofold.memory import MemoryStore, MemoryItem, MemoryTier
from mnemofold.fold import Folder
from mnemofold.retrieval import RetrievalEngine, parse_query, FusionWeights
from mnemofold.context import ContextPacker, ContextItem, PackingProfile

# 1. 生成 180 天合成工作历史（植入承诺/决策/矛盾作为真值）
factory = WorkHistoryFactory(seed=42, days=180)
events, manifest = factory.generate()

# 2. 摄入：分段时间线、抽取承诺/决策/文档引用
result = IngestPipeline().run([e.to_event() for e in events])

# 3. 入库 + 夜间折叠（近重复合并、复发挖掘）
store = MemoryStore()
for episode in result.episodes:
    store.add(MemoryItem(episode.episode_id, MemoryTier.EPISODIC,
                         episode.title, title=episode.title))
report = Folder().fold(store, "2025-07-01T02:00:00+00:00")

# 4. 检索（结构化查询 + 融合权重）+ 预算内上下文打包
engine = RetrievalEngine(store=store)
engine.build_index()
hits = engine.search_parsed(parse_query("budget tag:alpha"),
                            fusion=FusionWeights(relevance=1.0, recency=0.3),
                            now="2025-07-01T09:00:00+00:00")
pack = ContextPacker(budget=1200, profile=PackingProfile.MEETING_PREP).pack(
    [ContextItem(h.item_id, h.snippet, title=h.title,
                 token_estimate=len(h.snippet) // 4 + 1,
                 priority=h.score) for h in hits]
)
print(pack.to_markdown())
```

## 助手层

- **承诺台账** `mnemofold.ledger`：状态机转移、逾期检测（含每项承诺的
  grace window）、依赖阻塞、nudge 生成、JSON/Markdown 导出与导入。
- **收件箱分诊** `mnemofold.triage`：透明信号加权评分、图导出的发件人
  重要度、安静时段、批量分桶（act_now / review / defer）。
- **会议准备** `mnemofold.prep`：证据式议程（每条议程引用记忆 id）、
  对植入真值的覆盖率测量。`measure_coverage(prep, expected_ids,
  expected_categories=...)` 同时返回条目级覆盖率与类别级覆盖率
  （`category_coverage`，即至少命中一条的类别占比），用于区分"漏了
  一个决策"和"整个决策类都没找到"两种缺口。
- **站立会与周报** `mnemofold.review`：确定性报告，逐条引用承诺 id，
  可组合为自包含 HTML 页面（`mnemofold.reports.assemble_report_page`）。

## CLI

```bash
mnemofold demo            # 完整离线演示：工厂→摄入→折叠→检索→报告
mnemofold eval            # 对植入真值输出评分卡
mnemofold fold --db j.db  # 运行夜间折叠并打印报告摘要
mnemofold ledger --db ...  # 承诺台账
mnemofold triage / prep / asof / context / triggers / privacy / replay / diff
```

`mnemofold --help` 列出全部子命令；所有命令离线可跑、退出码明确。

## 评估与校准

所有指标都基于植入真值（planted ground truth）的合成场景计算，数字
全部可复现。`mnemofold.evaluation` 模块提供：

- **检索/分诊**：`precision_at_k`、`recall`、`precision`、`f1_score`
- **承诺检测**：`overdue_detection_accuracy`（precision/recall/f1）
- **as-of 查询**：`as_of_accuracy`（历史时点的事实正确性）
- **预算与引用**：`budget_adherence`、`citation_validity`
- **校准**：`brier_score`、`calibration_report`（等宽分桶）与
  `expected_calibration_error`（ECE，加权平均 |预测-观测| 偏差），
  用于检查分诊/置信度分数是否像概率一样行为。

## 配置面

行为全部由显式配置驱动，默认值即基线行为：`FactoryConfig`（合成历史
形态）、`SegmentConfig`（分段规则）、`FusionWeights`（检索融合）、
`StalenessPolicy` / `TierPolicy`（记忆生命周期）、`ToolPolicy`（工具
门禁）、`RetentionPolicy`（衰减曲线）。每个配置都有 `to_dict`/校验与
往返测试，序列化处理见 [reproducibility.md](reproducibility.md)。


## 分段模式、触发器派生与完整性审计

### 严格分段模式

`EpisodeSegmenter` 支持四种 `mode`：

- `gap`（默认）：按时间间隔聚合；thread/meeting 键变化即切分情节；
- `day`：按 `day_tz` 的日历日分桶（跨 DST 的历史保持在本地日）；
- `thread`：严格按 `thread_id` 聚合——同一线程无论间隔多久都在一个情节；
- `meeting`：严格按 `meeting_id` 聚合。

严格模式下不携带对应键的事件回退到 gap 规则（且不再按另一种键分组）；
`max_episode_events` 会把超长键组切成连续情节。配置经
`SegmentConfig.to_dict` / `from_dict` 往返无损。

### 触发器派生

- `derive_commitment_rules(ledger, now)`：台账 → 逾期告警（CRITICAL）与
  截止提醒（WARNING，提前 `ahead_days`）；
- `derive_stale_thread_rules(events, now)`：事件历史 → 陈旧线程规则。
  只提醒“最近沉默”的线程：静默超过 `closed_after_days`（默认两倍
  窗口）视为已了结，不再打扰；
- `derive_followup_rules(events, now)`：以问号结尾且超过
  `unanswered_after_hours` 无人回应的线程 → 跟进规则（表面启发式，
  只检查字面 `?`）；
- `derive_summary_rules(now)`：每日小结（`DAILY_SUMMARY`）与每周回顾
  （`WEEKLY_REVIEW`）的调度规则，id 内嵌触发日期，跨次派生不冲突。

所有派生规则都带 cooldown 与去重窗口，与 `TriggerEngine` 的静默时段、
报表覆盖抑制语义完全兼容。

### 完整性审计

`Workspace.verify_integrity()` 是只读审计，覆盖四层：日志哈希链
（`journal_chain`）、trace 哈希链（`trace_chain`）、墓碑复活探测
（`no_resurrection`，直接探查存储而非 recall 守卫）、投影摘要稳定性
（`projection_stable`）。CLI：

```bash
mnemofold verify --db ./ws          # 人类可读输出，PASS/FAIL
mnemofold verify --db ./ws --json   # 机器可读报告
```

检查失败时退出码非零。被篡改的 trace 会让工作区打开即失败
（`ValueError: hash mismatch ...`）——恢复路径是显式的，不做静默修复。
