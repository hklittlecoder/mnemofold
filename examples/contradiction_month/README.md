# contradiction_month — 矛盾月份：取代、as-of、审计与删除级联

## 这个示例做什么

在一段植入了三类矛盾（截止日期变更、负责人改派、决策反转）的 120 天
合成历史上，演示长期记忆面对矛盾时的四条保证：

1. **时间取代（supersede）**：事实变更时关闭旧区间、开启新区间，
   两个版本都保留在时态库中；
2. **as-of 正确性**：对变更前后两个探测时刻分别查询，必须各自返回
   当时可知的值——对植入真值逐条核对；
3. **证据信任消解**：故意制造一对区间重叠的冲突事实（未验证 vs 已验证
   来源），`ConflictDetector` 按信任序消解并产出审计报告；
4. **右被遗忘（right-to-forget）**：删除一个承诺会级联删除其证据，
   法律保留（legal hold）的节点在级联中被阻断保留，墓碑阻止复活。

## 运行

```bash
python examples/contradiction_month/run.py
```

完全离线；相同 seed 输出可复现。

## 输出解读

- `as-of answers correct: N/N`：对合成植入真值的逐条核对结果；
- `winner value: bob`：已验证来源战胜未验证来源的消解结果；
- `cascade deleted / blocked(protected)`：删除级联与保留阻断的审计行；
- `RESULT: OK`：全部不变量成立。
