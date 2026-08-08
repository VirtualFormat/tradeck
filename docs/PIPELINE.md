# 数据管道架构

核心设计：**前端不直连数据源**。backend 通过 APScheduler 定时从数据源拉取写入 PostgreSQL，前端 Server Components 从 backend API 读库（毫秒级），实现页面秒开（直连数据源需 10–30s，读库 <200ms）。数据源故障时页面仍有 DB 历史数据兜底。

## 拓扑

```
web (Next.js :3000)  ──▶  backend (FastAPI :8080)  ──▶  PostgreSQL (:5432)
                                    │
                                    └──▶  数据源：TickFlow / akshare / OpenBB(:6900)
```

数据流：

```
数据源 ──① APScheduler 定时拉取──▶ PostgreSQL ──② FastAPI 只读──▶ Next.js Server Component
```

三源分工与限流降级见 [`DATA-LAYER.md`](DATA-LAYER.md)；海外源分流见 [`OVERSEAS-NODE.md`](OVERSEAS-NODE.md)。

## 运行模式

backend 通过 `DATA_MODE` 在两种互斥模式间运行，变量仅接受 `live` / `mock`，无效值会在导入配置时直接令服务启动失败：

- `live`（默认）：启动 APScheduler 和真实数据任务，不执行 mock seed。dev 与 prod 未显式配置时均使用此模式。
- `mock`：启动时自动写入模拟数据，不启动 APScheduler；手动同步与读 API 按需回源同时禁用，不会请求或写入真实数据。

数据库身份通过 `mock_seed_runs.database_mode` 单例 marker 持久化。backend lifespan 会在任何 seed 或 scheduler 启动前完成校验：空数据库绑定为当前 mode；已有业务数据但无 marker 的历史库只允许迁移为 live；marker 与 `DATA_MODE` 不一致时直接拒绝启动。因此遗漏卷变量时 mock 不能写入 live 卷，live 也不能连接 mock 卷。

dev compose 的 live 模式沿用现有 `tradeck_devcontainer_dev-postgres-data`，避免升级配置时丢失已下载的全市场历史；mock 模式必须同时显式传入 `DEV_POSTGRES_VOLUME=tradeck-dev-postgres-mock-data`。prod 根 compose 不传 `DATA_MODE`，始终采用默认 live 行为。

## 技术选型

- **DB：PostgreSQL 16**（官方镜像成熟、支持 JSON/全文检索/时序，可平滑升级 TimescaleDB）。
- **Backend：FastAPI + APScheduler**（复用 OpenBB Python 生态；APScheduler 嵌入式，无需额外 broker）。

## 存储（24 张表）

DDL 见 `apps/backend/init.sql`（postgres 容器首次启动自动执行）：

`daily_prices` `quote_snapshots` `index_prices` `movers_cache` `news_articles` `macro_indicators` `income_statements` `equity_profiles` `fundamental_metrics` `board_heat` `symbol_board_map` `board_sentiment` `fund_flow` `analyst_consensus` `balance_sheets` `cash_flow_statements` `earnings_calendar` `economic_calendar` `technical_indicators` `announcements` `research_reports` `market_breadth` `macro_asset_prices` `yield_curve_rates`

写入约定：全部 UPSERT，可重复执行；job 拉取失败返回 0 行、不覆盖已有数据（降级保旧快照）。

## 定时任务

APScheduler 注册于 `apps/backend/app/scheduler.py`，仅在 `DATA_MODE=live` 时启动，覆盖日K / 报价 / 指数 / 涨跌榜 / 新闻 / 宏观 / 财报 / 板块 / 资金流 / 研报 / 公告 / 市场宽度 / 宏观资产 / 收益率曲线等。启动时 `_initial_fetch()` 后台跑一轮预热（受数据层全局并发闸约束）。碰 akshare 的高频 job 错峰，见 [`DATA-LAYER.md`](DATA-LAYER.md)。

**日K 全量初始化**：启动时按市场检查 `daily_prices` 历史行数和最新交易日；历史量不足或最新 K 过旧的市场自动后台全量拉一次（TickFlow universe，近 250 天），不会因其他市场已有大表而掩盖缺失。此后每日增量（近 5 天 UPSERT）。进度经内存注册表（`app/jobs/progress.py`）上报，`GET /api/system/jobs` 暴露，前端首页状态条（`data-sync-status.tsx`，5s 轮询）对初始化与每日更新都做进度提示。

## API 端点（只读 DB）

`apps/backend/app/api/` 各 router，前端 Server Components 直接消费：

```
/api/quotes  /api/historical  /api/indices  /api/movers  /api/movers/turnover
/api/news  /api/macro  /api/profile
/api/fundamentals/{metrics,income,balance,cash}
/api/analyst/consensus  /api/calendar/{earnings,economic}
/api/boards/{heat,sentiment}  /api/fundflow  /api/technicals
/api/announcements  /api/research  /api/breadth  /api/market-internals
/api/cross-assets  /api/yield-curve  /api/yield-curve/spread
/api/market-summary（三市宽度对比）  /api/search（代码/名称搜索）
/api/system/jobs（任务进度，读内存注册表而非 DB）
```

## dev 模拟数据

dev 默认 live，不会自动灌模拟数据。需要检查纯模拟页面时，显式切换并重建 dev、postgres、backend，保证开发容器不会保留旧的 `DATA_MODE`：

```bash
DATA_MODE=mock DEV_POSTGRES_VOLUME=tradeck-dev-postgres-mock-data \
  docker compose -f .devcontainer/docker-compose.yml up -d --force-recreate dev postgres backend
```

mock backend 启动时会自动运行 `apps/backend/app/seed_mock.py`。在该容器中可用 `python -m app.seed_mock` 重复执行 UPSERT；live 或无效模式会拒绝执行。切回真实数据：

```bash
DATA_MODE=live DEV_POSTGRES_VOLUME=tradeck_devcontainer_dev-postgres-data \
  docker compose -f .devcontainer/docker-compose.yml up -d --force-recreate dev postgres backend
```

仅改变 `DATA_MODE` 或 `DEV_POSTGRES_VOLUME` 不会改变数据库身份；错误组合会在 lifespan 阶段 fail fast，且不会运行 seed 或真实数据任务。
