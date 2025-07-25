# 可复现性

mnemofold 的核心承诺之一：**相同 seed + 相同配置 → 逐字节相同的输出**。
本页说明支撑该承诺的机制与约定。

## 确定性来源

1. **显式随机源**：所有随机性来自 `random.Random(seed)` 或显式传入的
   seed；库代码不读取系统熵。工厂的重试抖动、随机审批 persona 等也
   使用带 seed 的 RNG（`ToolRegistry(rng_seed=...)`、
   `auto_resolve(rng_seed=...)`），不使用进程内加盐的 `hash()`。
2. **合成时钟**：时间来自事件时间戳或调用方传入的 `now` 字符串，
   评估与报告从不读取墙上时钟。
3. **规范化序列化**：统一 `json.dumps(sort_keys=True, separators=(",",":"))`；
   集合在输出前排序（按 id 或确定性键），避免哈希序泄漏。
4. **浮点量化**：分数与统计量在**产生点**量化（`round(x, 6)`），而不是
   在序列化层，保证摘要跨 Python 版本/libm 稳定。

## 字节一致的回放

`TraceRecorder` 把事件、决策、召回与回执写入校验和链式 JSONL；
`TraceRecorder` 重新打开同一文件时会**续接**哈希链（resume），
`Replayer.replay_from_last_checkpoint` 支持从最近检查点恢复。
硬约束（测试覆盖）：

- 相同输入两次录制 → 文件逐字节相同；
- 中途篡改/重排 → `TraceReader.verify()` 失败；
- 崩溃（丢弃 recorder）后 resume → 全链仍可验证。

## Golden fixtures

关键算法的输出被 golden 文件钉住（`tests/fixtures/*.json`），覆盖：
事件 envelope、日志哈希链、分段结果、as-of 查询答案、检索排序、
工厂历史 manifest。约定：

- golden 只能**随对应行为变更一起**重新生成，diff 必须进 review；
- 生成方式是运行真实代码（测试模块内提供 `golden_payload()`），
  绝不手写数值。

## 合成数据的诚实标注

工厂产出的一切数字（precision@k、覆盖率、召回率等）都来自带植入真值的
合成历史，测试与报告中随测随标（seed、days、config 会写入 manifest 与
报告页脚 `run_metadata`）。噪声事件带 `noise=True` 标记；离线适配器测试
与真实模型评估严格区分；仓库中不存在任何真实个人数据、密钥或预训练权重。

## 依赖锁定

`uv.lock` 已提交入库（CI 缓存键依赖它）；`pyproject.toml` 声明运行时
仅依赖 NumPy，`torch` 为可选 extra（CPU wheel），缺失时相关测试自动
跳过且默认套件不受影响。
