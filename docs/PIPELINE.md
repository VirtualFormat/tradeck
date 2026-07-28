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

## 技术选型

- **DB：PostgreSQL 16**（官方镜像成熟、支持 JSON/全文检索/时序，可平滑升级 TimescaleDB）。
- **Backend：FastAPI + APScheduler**（复用 OpenBB Python 生态；APScheduler 嵌入式，无需额外 broker）。

## 存储（24 张表）

DDL 见 `apps/backend/init.sql`（postgres 容器首次启动自动执行）：

`daily_prices` `quote_snapshots` `index_prices` `movers_cache` `news_articles` `macro_indicators` `income_statements` `equity_profiles` `fundamental_metrics` `board_heat` `symbol_board_map` `board_sentiment` `fund_flow` `analyst_consensus` `balance_sheets` `cash_flow_statements` `earnings_calendar` `economic_calendar` `technical_indicators` `announcements` `research_reports` `market_breadth` `macro_asset_prices` `yield_curve_rates`

写入约定：全部 UPSERT，可重复执行；job 拉取失败返回 0 行、不覆盖已有数据（降级保旧快照）。

## 定时任务

APScheduler 注册于 `apps/backend/app/scheduler.py`，覆盖日K / 报价 / 指数 / 涨跌榜 / 新闻 / 宏观 / 财报 / 板块 / 资金流 / 研报 / 公告 / 市场宽度 / 宏观资产 / 收益率曲线等。启动时 `_initial_fetch()` 后台跑一轮预热（受数据层全局并发闸约束）。碰 akshare 的高频 job 错峰，见 [`DATA-LAYER.md`](DATA-LAYER.md)。

**日K 全量初始化**：启动时检测 `daily_prices` < 100 万行（未初始化）→ 自动后台全量拉一次（TickFlow universe 三市 ~2 万只 × 250 天，~5 分钟，实测写入 ~310 万行）；此后每日增量（近 5 天 UPSERT）。进度经内存注册表（`app/jobs/progress.py`）上报，`GET /api/system/jobs` 暴露，前端首页状态条（`data-sync-status.tsx`，5s 轮询）对初始化与每日更新都做进度提示。

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

## dev 假数据

devcontainer 的 backend 置 `DEV_SEED=1`，启动时（起调度器前）自动灌入假数据垫底，真 job 到货后逐步覆盖，方便本地看 UI；prod 根 `docker-compose.yml` 不置，默认关。生成逻辑在 `apps/backend/app/seed_mock.py`（亦可手动 `python -m app.seed_mock`）。
