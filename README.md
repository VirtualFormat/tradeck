# tradeck

投研数据看板：全球指数、涨跌榜、宏观、资金流、板块热力、个股详情等。

## 技术栈

- **前端**：Next.js 16 + shadcn/ui + Tailwind v4 + lightweight-charts（K线）+ recharts
- **后端**：FastAPI（数据管道 + API）+ PostgreSQL
- **数据层**：日K 走 TickFlow；A 股报价/深度数据 backend 直调 akshare（统一限流门面）；宏观/海外源走 OpenBB Platform，经 Cloudflare 分流到韩国瘦节点

## 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/`](docs/README.md) | 文档总览（索引） |
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | 数据管道架构：拓扑、存储（24 表）、定时任务、API 端点、live/mock 模式 |
| [`docs/DATA-LAYER.md`](docs/DATA-LAYER.md) | 数据层特性：三源分工、薄门面（限流/重试/降级）、symbol 规范、调度错峰 |
| [`docs/DATA-SERVICE.md`](docs/DATA-SERVICE.md) · [`docs/DATA-STORAGE-TIERED.md`](docs/DATA-STORAGE-TIERED.md) | 数据服务拆分与分层存储设计 |
| [`docs/QUANT-BACKTEST.md`](docs/QUANT-BACKTEST.md) | 量化引擎与策略开发：Polars 矩阵引擎、AI 策略生成、因子挖掘 |
| [`docs/OVERSEAS-NODE.md`](docs/OVERSEAS-NODE.md) | 海外节点部署：韩国瘦 OpenBB、token 生成与配置、分流/回滚/排查 |
| [`CODEBUDDY.md`](CODEBUDDY.md) · [`AGENTS.md`](AGENTS.md) | 开发规范：UI 强制规则、devcontainer |

## 开发 / 部署

- 开发在 devcontainer 内完成（见 `CODEBUDDY.md`）。
- Prod 部署：中国大陆服务器运行 `bash deploy/deploy-cn.sh`，GHCR 镜像默认经
  南京大学镜像站拉取；其他环境也可直接使用根 `docker-compose.yml`。

```bash
# 上海等中国大陆服务器：校验配置、经 NJU 拉镜像并启动
bash deploy/deploy-cn.sh

# 临时绕过镜像站排障
GHCR_REGISTRY=ghcr.io bash deploy/deploy-cn.sh
```
