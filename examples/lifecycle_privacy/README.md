# lifecycle_privacy — 记忆生命周期与隐私：封存、折叠、遗忘、审计

## 这个示例做什么

在一份带种子的合成工作历史（10 天）上，用一个一次性 workspace 完整走一遍
个人数据的受控生命周期：

1. **隐私**：一条含合成 PII（邮箱 / 电话 / 卡号）的笔记先经
   `detect_pii` 检出，再用带盐的 `RedactionVault.seal` 转成可逆 token；
   **只有封存后的文本**进入记忆（`remember`）；
2. **巩固**：夜间折叠 `fold` 对投影记忆做晋升与近重复合并；
3. **检索**：`ask` 返回的每条引用都能 `recall` 到活体记忆；
4. **右被遗忘**：`forget_preview` 先给出影响面（含级联与受影响台账项），
   确认后再 `forget` —— 级联删除、落墓碑，`recall` 永不再返回；
5. **审计**：`verify_integrity`（日志链 / trace 链 / 复活探测 / 投影摘要）
   与 trace 摘要交叉印证。

所有输出数字都来自本次实际运行；PII 全部为合成数据，示例完全离线、
结果确定（同一 seed 两次运行输出逐字节一致）。

## 运行

```bash
python examples/lifecycle_privacy/run.py
```

退出码 0 且末行输出 `RESULT: OK` 表示全部检查通过。

## 检查点

| 检查 | 含义 |
| --- | --- |
| `pii_detected` | 至少检出 3 类 PII 片段 |
| `sealed_hides_email` / `sealed_hides_card` | 封存文本不含原文 |
| `vault_unseal_restores` | vault 可精确还原（可逆脱敏） |
| `citations_resolve` | 检索引用全部指向活体记忆 |
| `preview_plans_the_note` | 预览准确列出将被删除的键 |
| `forgotten_not_recallable` | 遗忘后任何路径都取不回 |
| `integrity_ok` | 四层完整性审计全部通过 |
| `trace_has_receipts` | trace 中留有操作回执 |
