# history_workstream — 180 天工作历史 → 工作流图 + 承诺台账

## 这个示例做什么

用内置合成工厂（seed=42，180 天，含 designer persona）生成一段完整的
合成工作历史，然后：

1. 运行 `IngestPipeline`：情节分段、实体收集、承诺提取（带 evidence span）；
2. 构建 `WorkstreamGraph`：person / project / commitment 节点与
   OWNS / PART_OF 边，并校验结构不变量（无悬挂边、溯源无环）；
3. 用抽取到的结构化承诺生成 `CommitmentLedger`；
4. 对照植入真值（planted ground truth）计算承诺 recall / precision。

## 运行

```bash
python examples/history_workstream/run.py
```

无需网络、GPU 或外部数据集；相同 seed 的输出逐字节可复现。

## 输出解读

- `checksum`：覆盖全部事件 payload 的内容摘要，用于确认可复现；
- `commitment recall / precision`：对**合成数据**植入承诺的测量值，
  不是任何真实语料或真实用户的评估结果；
- `RESULT: OK`：recall 达到 1.0 且图不变量全部成立。
