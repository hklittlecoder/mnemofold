# folding_demo — 夜间折叠：巩固、复发挖掘、剧本

## 这个示例做什么

在植入了重复工作流（`workflow_repeats=5`）的 120 天合成历史上，运行
`Folder` 的夜间折叠，展示三件事：

1. **晋升**：一条高显著性情景记忆被巩固为语义事实（`*_sem`）；
2. **近重复合并**：两条几乎相同的语义笔记合并，败者进入胜者的
   provenance，折叠报告同时记录被拒绝的候选（附相似度）；
3. **复发挖掘**：重复出现的步骤序列（draft → review → publish）被提出
   为剧本候选，示例随后把它落成一条已审批、已激活的 `Playbook`。

第二次折叠验证**幂等**：不再有新的合并或晋升。

## 运行

```bash
python examples/folding_demo/run.py
```

完全离线；相同 seed 输出可复现。

## 输出解读

- `merges / rejected / new semantic`：第一次折叠的巩固计数；
- `workflow 'release': draft -> review -> publish x5`：挖掘到的复发工作流；
- `second fold idempotent: merges=0 new_semantic=0`：幂等性；
- `RESULT: OK`：全部不变量成立（含幂等与剧本激活）。
