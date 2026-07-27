# tradeck

投研数据看板：全球指数、涨跌榜、宏观、资金流、板块热力、个股详情等。

## 技术栈

- **前端**：Next.js 16 + shadcn/ui + Tailwind v4 + TradingView LC + ECharts
- **后端**：FastAPI（数据管道 + API）+ PostgreSQL
- **数据层**：OpenBB Platform；A 股走自写 `openbb-akshare-provider`，海外源经 Cloudflare 分流到韩国瘦 OpenBB 节点

## 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | 数据管道架构：拓扑、存储（24 表）、定时任务、API 端点、dev 假数据 |
| [`docs/DATA-LAYER.md`](docs/DATA-LAYER.md) | 数据层特性：三源分工、薄门面（限流/重试/降级）、symbol 规范、调度错峰 |
| [`docs/OVERSEAS-NODE.md`](docs/OVERSEAS-NODE.md) | 海外节点部署：韩国瘦 OpenBB、token 生成与配置、分流/回滚/排查 |
| [`CODEBUDDY.md`](CODEBUDDY.md) · [`AGENTS.md`](AGENTS.md) | 开发规范：UI 强制规则、devcontainer |

## 开发 / 部署

- 开发在 devcontainer 内完成（见 `CODEBUDDY.md`）。
- Prod 部署：根 `docker-compose.yml`（`docker compose up -d --build`）。
