## 变更内容
<!-- 概述这个 PR 做了什么、为什么。 -->

## 变更类型
- [ ] 新功能（feat）
- [ ] 缺陷修复（fix）
- [ ] 测试/文档/重构（test/docs/refactor）
- [ ] 构建或 CI（build/ci/chore）

## 检查清单
- [ ] `make format` 与 `make format-check` 通过
- [ ] `make test` 通过；确实缓慢的测试已标记 `@pytest.mark.slow`
- [ ] `make lint`（含 mypy）通过
- [ ] 新代码带边界测试，覆盖操作的两个方向
- [ ] 确定性未被破坏：相同 seed + 配置 → 相同输出
- [ ] 未声称真实 LLM / 真实用户结果；合成数据已明确标注
- [ ] 若涉及发布：`_version.py` 与 `CHANGELOG.md` 已同步更新
