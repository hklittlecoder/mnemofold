# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
版本处于 0.x 阶段，每次发布仅递增补丁号。

## [0.1.3] - 2026-11-18

聚焦完整性审计、确定性合并与报表深化。

### Added

- 工作区：`verify_integrity` 只读完整性审计（日志哈希链、trace 链、
  墓碑复活探测、投影摘要稳定性）；CLI 新增 `verify` 子命令
  （人类可读 / `--json`，检查失败时非零退出码）
- 图：`merge_graphs` 确定性合并——同 id 冲突以 base 为准并上报，
  悬挂边丢弃，输入永不被修改，合并结果始终通过结构审计
- 记忆：工作集驱逐审计日志 `evictions()`，驱逐全部可追溯
- 时间：`facts_expiring_within` 到期预览查询（含畸形数据跳过语义）
- 评估：`precision_at_k_curve` 排序质量曲线；按角色切片
  `run_role_slices`；记分卡漂移对比 `compare_scorecards`
- 台账：账龄报告 `aging_report` 与 burndown 序列 `burndown_series`，
  配套 SVG `render_burndown_svg`；报表新增校准可靠性图
  `render_calibration_svg`
- 摄入：严格 thread / meeting 分段模式（键内跨时间聚合、无键事件
  回退 gap 规则）
- 触发器：陈旧线程、待跟进提问、每日小结/每周回顾规则派生，
  与既有冷却/去重/静默时段语义完全兼容
- 持久化：版本化 envelope（`mnemofold.persist`）；BM25 索引、时间
  存储、redaction vault、审批队列可落盘，均带 golden 字节测试
- 文本：词级 `token_jaccard` 与组合相似度 `combined_similarity`
- CLI：`demo` 完整跑通 factory → ingest → fold → recall → context →
  prep → triage → standup 并打印实测分数

## [0.1.2] - 2026-11-18

围绕审计链、持久化与可解释性的一轮深化。

### Added

- 工具：收据日志链式摘要与 `verify_chain` 校验；幂等缓存 JSONL 持久化
  （`save`/`load`，字节级确定），工具结果 `to_dict`/`from_dict`
- 图：统一结构审计 `audit_graph`（悬挂边、溯源环、活跃计数）
- Playbook：审批门控执行器 `PlaybookRunner`（申请、批准、按前置条件
  顺序执行、失败即停），运行报告可序列化
- 记忆：保留期延长/清除 API（附审计历史 `retention_history`）
- 检索：BM25 逐项贡献解释 `explain`，与 `search` 得分在随机语料上
  交叉验证一致
- 折叠：报告自包含 HTML 渲染（动态文本全量转义）

### Changed

- 序列化：图校验和、计划与 playbook 摘要统一走共享的规范 JSON 助手
  `mnemofold.canon`（摘要值保持不变）

## [0.1.1] - 2026-11-17

在 0.1.0 的核心机制之上，深化各子系统的边界行为、可审计性与可复现性。

### Added

- 摄入：确定性情节序列化、声明式分段配置（含有界情节与日历日模式）、
  文档引用抽取、相对截止语（by friday / in 3 days）、带引用的情节转写、
  统一入口 `IngestPipeline`（附摘要 digest）
- 存储：版本化迁移注册表（v2→v3 墓碑表）、日志墓碑 API、`audit_chain`
  定位首个损坏帧、`Journal.project` 投影重建（双跑一致）
- 时间：区域工作日历注册表（含 2025 代表性节假日）、挂钟截止
  （`WallDeadline`，按 IANA 时区解析）、陈旧度策略分级、区间重叠校验
- 检索：结构化查询解析（tag/person/project/before/after/on）、时间窗与
  实体过滤、相关性/重要性/新近度融合权重、实体图扩展、as-of 检索
- 记忆/显著性/上下文：保留期与显式访问记录、声明式层级晋升降级策略、
  规范化特征向量（NumPy 与 torch 路径共享）、切片诊断与特征相关、
  按打包剖面加权优先级、时间序排序
- 巩固/冲突/衰减：工作流序列复发挖掘、折叠报告 Markdown 与 digest、
  证据聚合 `corroborate`、时态库矛盾扫描 `ConflictDetector`、法律保留
  （legal hold）、逐项保留状态快照
- 助手层：承诺台账宽限窗与 nudge、台账 JSON 导入、周报生成与渲染、
  证据式会议议程、覆盖率测量、自包含报告页组装
- 剧本/工具/计划/审批：剧本生命周期（激活/吊销）与序列化 digest、
  工具能力策略门禁、副作用工具幂等缓存、计划步骤间引用校验、计划 diff、
  计划执行循环（预算/依赖/失败传播）、审批 `tick`（过期/persona/升级）
- 隐私/删除/触发/回放：可逆脱敏保管库、人名检测（称谓/签名线索）、
  写/导出分层规则、哈希链访问日志、右被遗忘贯穿存储与索引、触发日志
  校验和 JSONL、录制续接与检查点回放
- 合成工厂：`FactoryConfig`（默认流保持不变）、可选 designer persona、
  带标记的噪声事件、可复用工作流、owner/decision 矛盾、覆盖 payload 的
  manifest 校验和

### Fixed

- 情节/区间比较改为按时间点而非字符串，跨 UTC 偏移不再误判
- 空名相似度视为不相似，避免无名实体的虚假合并候选
- 背包在预算为 0 时仍纳入零权重项
- 安静时段降分后按新分重算优先级档位
- 升级不再被瞬时状态覆盖，随机 persona 改用稳定摘要（去除进程加盐）
- 预算越界改为显式异常而非 `assert`（`-O` 下不被剥离）
- 站立会补全当日完成项与待决项

## [0.1.0] - 2026-11-17

首个版本：mnemofold 离线长期记忆框架的核心机制。

### Added

- 工作事件基础：内容寻址 `Event`（10 种事件类型）、带校验和的 schema 版本化
  envelope、JSONL 序列化、确定性合成时钟与时区安全日分桶（含 DST 边界）
- 存储基底：追加式 SQLite 日志，哈希链校验帧与 WAL 事务
- 工作流图：类型化节点与边、悬挂边与溯源环检测、确定性序列化
- 摄入管道：线程/会议/间隔分段、别名表实体解析与合并候选
- 时间模型：区间有效事实、as-of 查询、陈旧度、工作日历、截止与逾期计算
- 记忆分层：工作集/情景/语义/程序四层，晋升降级与有界工作集
- 显著性评分：NumPy 透明特征；可选 PyTorch MLP（`torch` extra，CPU 即可训练）
- 折叠巩固：确定性夜间折叠、近重复合并、复发挖掘、折叠报告
- 冲突消解：证据信任排序、确定性取代策略、矛盾审计、历史永不丢失
- 衰减遗忘：分层保留曲线、受保护/固定记录、宽限与墓碑语义
- 检索：BM25 倒排索引 + MMR 多样化重排、标签过滤、引用载荷
- 上下文包：确定性 token 估算、0/1 背包精确 DP 与贪心比较器、任务剖面
- 承诺台账：状态机转移、逾期检测、Markdown/JSON 导出
- 收件箱分诊：多信号优先级评分、安静时段规则、precision@k
- 会议准备：证据收集、议程组装、带引用的 Markdown/HTML 数据包
- 站立会报告：Markdown/HTML 与自绘 SVG 负载条
- 剧本库：版本化修订、审批门控、建议引擎
- 工具执行：声明式规范、参数校验、重试与抖动、幂等键
- 计划 DSL：JSON 计划模式、DAG 校验、拓扑排序、执行循环骨架
- 审批队列：角色化审批者、升级链、过期处理
- 隐私策略：PII 检测（含 Luhn 校验）、mask/hash/remove 脱敏、策略引擎、访问日志
- 删除语义：级联删除、墓碑索引、审计报告
- 主动触发：规则引擎、冷却/去重/安静时段/报告覆盖抑制
- 录制回放：校验和 JSONL 追踪、追踪 diff、检查点
- 合成工作历史工厂：种子角色、180 天历史、植入承诺/决策/矛盾
- 评估框架：precision/recall/F1、预算遵循、引用有效性等指标与评分卡
- 报告渲染：Markdown 原语、自绘 SVG（时间线/折叠摘要/负载条）、HTML 包装
- CLI：version、eval、demo、replay、diff、ledger、triage、fold、asof、
  context、prep、privacy、triggers 子命令
