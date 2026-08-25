# tradeck 文档

tradeck 是全球股票市场资讯看板（美股 / A 股 / 港股），并逐步演进为投研数据服务 +
量化研究平台。本目录收录**长期有效**的架构与设计文档。

> 过程性文件（任务拆解、验收记录、进行中的施工计划）不入本目录，见 `plans/`。

## 数据层

| 文档 | 内容 |
|---|---|
| [PIPELINE.md](PIPELINE.md) | 数据管道架构：拓扑、存储（24 表）、定时任务、API 端点、live/mock 模式 |
| [DATA-LAYER.md](DATA-LAYER.md) | 数据层特性：三源分工、薄门面（限流/重试/降级）、symbol 规范、调度错峰 |
| [DATA-SERVICE.md](DATA-SERVICE.md) | 数据服务拆分：三条铁律、分层、容量、对外接口（量化契约） |
| [DATA-STORAGE-TIERED.md](DATA-STORAGE-TIERED.md) | 分层存储设计：热 PG / 温 ClickHouse / 冷 Parquet+COS，量级测算与选型 |

## 量化

| 文档 | 内容 |
|---|---|
| [QUANT-BACKTEST.md](QUANT-BACKTEST.md) | 量化引擎与策略开发：Polars 矩阵引擎、META 策略规范、AI 生成、因子挖掘 |

## 部署与运维

| 文档 | 内容 |
|---|---|
| [OVERSEAS-NODE.md](OVERSEAS-NODE.md) | 海外节点部署：韩国瘦 OpenBB、token 配置、分流/回滚/排查 |

## 相关文件（仓库根目录）

| 文件 | 内容 |
|---|---|
| [../AGENTS.md](../AGENTS.md) | 项目指南：架构、约定、UI 强制规则、已知坑 |
| [../CODEBUDDY.md](../CODEBUDDY.md) | 开发规范：devcontainer 强制、prod compose 用途 |
| [../plans/](../plans/) | 过程性施工文件：任务拆解与验收记录（不入 docs） |
