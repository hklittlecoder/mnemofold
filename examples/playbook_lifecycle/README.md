# playbook_lifecycle — 剧本生命周期：挖掘、提议、审批、执行、修订

## 这个示例做什么

在植入了重复 `release` 工作流（`workflow_repeats=5`）的 120 天合成历史上，
走完程序性记忆的完整闭环：

1. **挖掘**：夜间折叠从重复步骤序列中提出剧本候选
   （实测 run_count 与 confidence）；
2. **建议**：`PlaybookLibrary.suggest` 按标签把候选浮出；
3. **审批门控**：`PlaybookRunner` 先向 `ApprovalQueue` 提交申请——
   被拒绝的请求不会触碰任何工具，也不会累加 run_count；
4. **执行**：批准后的运行把每个步骤交给真实的工具注册表执行，
   全部成功后 run_count 恰好 +1；
5. **修订**：删减步骤生成 v2 草稿（带 provenance），
   `diff_versions` 精确指出被移除的步骤。

所有数字来自本次实际运行；完全离线、确定性（同一 seed 输出逐字节一致）。

## 运行

```bash
python examples/playbook_lifecycle/run.py
```

退出码 0 且末行输出 `RESULT: OK` 表示全部检查通过。

## 检查点

| 检查 | 含义 |
| --- | --- |
| `recurrence_mined` | 折叠挖掘出至少一个工作流序列提案 |
| `suggestion_found` | 标签匹配能召回该剧本 |
| `denied_run_blocked` | 被拒申请不执行 |
| `denied_run_not_counted` | 被拒申请不计入 run_count |
| `approved_run_completed` | 批准后完整执行 |
| `all_steps_executed` | 每个步骤工具调用成功 |
| `run_count_incremented` | 成功运行恰好计数一次 |
| `revision_created` | 修订生成 v2 草稿 |
| `diff_shows_removed_step` | 版本 diff 指出被删步骤 |
