# Security Policy

## 受支持版本

| 版本 | 支持状态 |
| ---- | -------- |
| 0.1.x | ✅ 接收安全修复 |

## 报告漏洞

请通过 GitHub 的 private vulnerability reporting 提交安全问题，
**不要**在公开 issue 中披露细节。

报告请尽量包含：

- 复现步骤（离线、固定 seed 的最小示例最佳）
- 受影响的版本与 Python 版本
- 影响范围评估（例如：是否破坏隐私分层、删除语义或引用完整性）

我们会在 14 天内确认收到并给出初步评估；修复发布后会在
`CHANGELOG.md` 中记录。

## 安全说明

mnemofold 是离线框架，攻击面与设计约束如下：

- 默认测试与示例不需要网络、GPU 或外部数据集；不存在遥测或外部端点
- 隐私模块（`mnemofold.privacy`）提供 PII 检测与脱敏；隐私分层规则保证
  高层级内容不会泄漏到低层级
- 删除模块（`mnemofold.deletion`）实现 right-to-forget 级联与墓碑语义，
  并有属性测试保证已删除内容不会经由任何查询路径复活
- 所有报告渲染对文本做 HTML 转义，防御 hostile text 注入
- "模型"相关演示（`torch` extra）仅在本地合成数据上训练，不加载预训练权重
