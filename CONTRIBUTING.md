# Contributing

感谢对 mnemofold 的关注！本文档介绍开发环境搭建与协作约定。

## 开发环境

要求 Python 3.11+；依赖锁定在 `uv.lock`。

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
# 可选：PyTorch CPU 版（用于可训练显著性模型演示）
.venv/bin/pip install -e ".[torch]" --extra-index-url https://download.pytorch.org/whl/cpu
```

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `make build` | 构建 wheel（`--no-isolation`） |
| `make test` | 快速测试（不含 `slow`/`model` 标记） |
| `make test-all` | 全部测试（含慢测试与 torch 模型测试） |
| `make format` | ruff 自动格式化 |
| `make format-check` | 格式与 lint 检查 |
| `make lint` | ruff check + mypy |
| `make typecheck` | mypy 类型检查 |

提交前请运行 `make format`，并确保 `make test` 与 `make format-check` 通过。

## 提交约定

- 使用 Conventional Commits：`feat:`、`fix:`、`test:`、`docs:`、`refactor:`、`chore:`、`ci:`、`build:`
- 主题行保持简短，一个提交对应一个连贯变更
- 版本号仅递增补丁位（0.1.0 → 0.1.1），并同时更新 `CHANGELOG.md` 与
  `src/mnemofold/_version.py`；两者不一致时测试会失败

## 测试要求

- 新功能需带边界测试，覆盖操作的两个方向（如 encode/decode、apply/回滚）
- 公共 API、配置 schema 与序列化输出需有 golden/roundtrip 测试，确保任何漂移都是有意的
- 确实缓慢的训练/集成测试标记 `@pytest.mark.slow`；torch 依赖测试标记 `@pytest.mark.model`，
  在缺少 torch 的环境必须干净跳过
- 所有测试离线可跑；合成数据一律来自 `mnemofold.factory` 并固定随机种子

## 设计原则

- 确定性优先：相同 seed + 配置 → 字节一致的输出
- 诚实评估：所有指标数字来自带植入真值的合成实验，不声称真实 LLM 或真实用户结果
- 引用必须可解析：报告中引用的每个 memory id 都指向存在的记录
- 隐私分层：高层级内容永不泄漏到低层级

## Pull Request

较大改动请先开 issue 讨论方向。保持 PR 小而聚焦；CI 会在
Python 3.11/3.12/3.13 上运行 build、test-all、format-check 与 lint。
