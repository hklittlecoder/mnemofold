# assistant_week — 完整助手周：分诊、会议准备、报告与评分卡

## 这个示例做什么

用 21 天合成历史（seed=9）建立一个持久工作区（journal + 投影），然后
按顺序跑一遍助手职责，全部离线、全部真实执行：

1. **收件箱分诊**：对 mail/chat 事件用承诺抽取器派生信号（不直接喂
   标签），`TriageScorer` 评分后由 `TriageBatcher` 分桶
   （act_now / review / defer，含溢出原因）；
2. **会议准备**：从工作区记忆生成带引用的议程与背景数据包；
3. **站立会 + 周报**：台账驱动的 Markdown 站立会与自包含 HTML 周报
   （写入临时目录，退出即清理）；
4. **报告页组装**：承诺时间线 SVG + 负载条 + run metadata 页脚；
5. **上下文打包**：会议资料的预算内 0/1 背包选择；
6. **评估套件**：对植入真值输出承诺 recall、逾期检测、as-of 准确率、
   隐私违规计数（必须为 0）与删除防复活等评分卡。

## 运行

```bash
python examples/assistant_week/run.py
```

除临时目录外不写任何文件；相同 seed 输出可复现。

## 输出解读

所有数字都是**这次合成运行实测**的结果（打印 seed 与 checksum 以便
复现），不代表任何真实用户或真实语料上的效果。`RESULT: OK` 表示工作区
非空、分诊不丢项、上下文包不超预算、评估套件全部通过。


评估环节除整套 scorecard 外，还输出**按 persona 角色切片**的承诺召回
（`run_role_slices`）：每个角色一行 `role slice ...: recall=...`，同样
只基于合成植入的 ground truth，逐 seed 可复现。
