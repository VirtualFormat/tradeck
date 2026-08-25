# plans — 过程性施工文件

本目录存放**进行中的任务拆解与验收记录**（施工过程文件），与 `docs/` 分工：

- `docs/`：长期有效的架构与设计文档，适合对外展示（GitHub / web）。
- `plans/`：过程性文件，随项目推进持续回填，完成后保留作历史记录，不对外展示。

主 agent 按本目录的任务卡派活，流程：派活 → 子 agent 执行（写范围受限）→
review 门禁 → 修复 → 验收 → 回填记录。

| 文件 | 对应设计文档 | 状态 |
|---|---|---|
| [TASKS-DATA-SERVICE.md](TASKS-DATA-SERVICE.md) | [../docs/DATA-SERVICE.md](../docs/DATA-SERVICE.md) | 阶段一~三.五已验收，阶段四进行中 |
| [TASKS-QUANT-BACKTEST.md](TASKS-QUANT-BACKTEST.md) | [../docs/QUANT-BACKTEST.md](../docs/QUANT-BACKTEST.md) | 未开始 |
