# integrity_audit — 完整性审计走查：验证、篡改、遗忘、复活、导出

## 这个示例做什么

在一个一次性 workspace 上按脚本走完所有防护层，每一步都打印实测结果：

1. **健康审计**：新工作区的 `verify_integrity()` 四层检查
   （日志哈希链 / trace 哈希链 / 复活探测 / 投影摘要稳定性）全部通过；
2. **篡改检测**：复制一份 trace 并修改其中一条 payload——副本被读取器
   拒绝（`verify() == False`），原工作区不受影响；
3. **右被遗忘**：先 `forget_preview` 查看影响面，再 `forget`——
   之后任何 `recall` 都取不回；
4. **复活探测**：绕过守卫把已删内容塞回存储，`verify_integrity`
   立刻在 `resurrected_keys` 中点名它；移除后审计恢复通过；
5. **导出一致性**：bundle manifest 的事件数与日志帧数一致，
   trace 摘要按类型计数。

完全离线、确定性（无随机 seed 参与），不含任何真实个人数据。

## 运行

```bash
python examples/integrity_audit/run.py
```

退出码 0 且末行输出 `RESULT: OK` 表示全部检查通过。
