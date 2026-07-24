# tradeck 数据管道迁移完成文档

## 概述

将前端从"实时直连 OpenBB API"改为"backend 定时拉取到 PostgreSQL，前端从 backend DB 读"，实现页面秒开（<200ms）。

迁移分 3 个阶段完成，历时 3 天（2026-07-05 ~ 2026-07-08）。

## 架构

```
┌─────────────────────────────────────────────────────┐
│ docker-compose（4 个 service）                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ web      │   │ backend  │   │ openbb       │    │
│  │ Next.js  │──▶│ FastAPI  │──▶│ OpenBB API   │    │
│  │ :3000    │   │ :8080    │   │ :6900        │    │
│  └──────────┘   └────┬─────┘   └──────────────┘    │
│                       │                              │
│                       ▼                              │
│                 ┌──────────┐                         │
│                 │ postgres │                         │
│                 │ :5432    │                         │
│                 └──────────┘                         │
└─────────────────────────────────────────────────────┘
```

### 数据流

```
OpenBB (yfinance/akshare/sec/oecd/federal_reserve)
    │
    │ ① backend 定时拉取（APScheduler）
    ▼
PostgreSQL（9 张表）
    │
    │ ② backend API 提供（FastAPI，<10ms）
    ▼
Next.js Server Component（从 backend 读，<200ms）
```

## 迁移历程

### 阶段 1：基础设施（2026-07-08）

**目标**：核心数据流跑通

**完成内容**：
- 新增 PostgreSQL 16-alpine（docker service，init.sql 自动建表）
- 新增 FastAPI backend（docker service，:8080）
  - asyncpg 连接池
  - APScheduler 定时任务
  - 3 个 API：`/api/quotes` + `/api/historical` + `/api/indices`
  - 3 个 job：日 K 线 + 实时报价 + 指数历史
- 前端 `openbb.ts` 改用 `backendFetch`（quotes/historical/indices）

**解决的问题**：
- OpenBB CFTC provider 启动崩溃 → Dockerfile 加 `pip uninstall openbb-cftc`
- OpenBB `--workers 4` 参数不支持 → 改用 `uvicorn openbb_platform_api.main:app --workers 4`
- asyncpg date 类型错误 → 加 `_parse_date()` 转换

**验证数据**：
- daily_prices: 2754 条（8 美股 × 252 + 3 港股 × 246）
- quote_snapshots: 11 条
- index_prices: 128 条

### 阶段 2：涨跌榜 + 热力图（2026-07-08）

**目标**：迁移首页高频组件

**完成内容**：
- 新增 `movers_cache` 表
- backend 加 `jobs/movers.py`（每 5 分钟拉涨跌榜）
- backend 加 `api/movers.py`（`GET /api/movers?type=gainers&market=US`）
- 前端迁移：
  - `movers-board.tsx`：从 backend `/api/movers` 读
  - `heatmap/page.tsx`：从 backend `/api/movers` 读
  - `api/screener/route.ts`：代理 backend
  - `app-layout.tsx`：侧边栏指数从 backend `/api/indices` 读

**效果**：
- 首页二次：3.3s → **104ms**
- AAPL 二次：2.2s → **71ms**

### 阶段 3：剩余全部组件（2026-07-08）

**目标**：迁移所有剩余组件，完全去掉前端直连 OpenBB

**完成内容**：
- DB 新增 5 张表：`news_articles` / `macro_indicators` / `income_statements` / `equity_profiles` / `fundamental_metrics`
- backend 新增 3 个 job：
  - `jobs/news.py`：每 30 分钟拉新闻
  - `jobs/macro.py`：每天拉宏观指标（CPI/失业率/GDP/EFFR/SOFR）
  - `jobs/fundamentals.py`：每周拉公司信息 + 基本面指标 + 财报
- backend 新增 4 个 API：
  - `/api/news`：从 news_articles 读
  - `/api/macro`：从 macro_indicators 读
  - `/api/profile`：从 equity_profiles 读
  - `/api/fundamentals/metrics` + `/api/fundamentals/income`：基本面 + 财报
- 前端改造：
  - `openbb.ts`：所有函数改用 `backendFetch`
  - `treasury-board.tsx`：用 backend macro 数据
  - 去掉所有直连 OpenBB 的 `fetchJSON` 调用

**解决的问题**：
- `macro_indicators.value` 精度溢出 → 改 DECIMAL(20,6)

**效果**：
- 首页首次：182ms → 二次：81ms
- AAPL 首次：704ms → 二次：92ms

## 最终 DB Schema

### 9 张表

```sql
-- 1. 日 K 线（所有市场）
daily_prices (id, symbol, market, date, open, high, low, close, volume)
  UNIQUE(symbol, date)
  INDEX(symbol, date DESC)

-- 2. 实时报价快照（每只股票最新一条）
quote_snapshots (symbol PK, name, last_price, change, change_percent, volume, market, updated_at)

-- 3. 指数历史
index_prices (id, symbol, market, date, close, volume)
  UNIQUE(symbol, date)

-- 4. 涨跌榜缓存
movers_cache (id, type, market, rank, symbol, name, price, percent_change, volume, updated_at)
  INDEX(type, market)

-- 5. 新闻
news_articles (id, symbol, title, url UNIQUE, summary, publisher, published_at, fetched_at)
  INDEX(symbol)
  INDEX(published_at DESC)

-- 6. 宏观指标
macro_indicators (id, name, date, value DECIMAL(20,6))
  UNIQUE(name, date)

-- 7. 财报
income_statements (id, symbol, fiscal_year, total_revenue, net_income, gross_profit, operating_income)
  UNIQUE(symbol, fiscal_year)

-- 8. 公司信息
equity_profiles (symbol PK, name, sector, industry, market_cap, currency, exchange, description, updated_at)

-- 9. 基本面指标
fundamental_metrics (symbol PK, market_cap, pe_ratio, forward_pe, peg_ratio,
  enterprise_to_ebitda, earnings_growth, revenue_growth, dividend_yield, beta,
  profit_margins, return_on_equity, debt_to_equity, updated_at)
```

## 定时任务

| 任务 | Cron | 时区 | 数据源 | 写入表 | 数据量 |
|---|---|---|---|---|---|
| 日 K 线（美股） | `0 16 * * 1-5` | UTC | yfinance | daily_prices | 252 条/股 |
| 日 K 线（A 股） | `0 8 * * 1-5` | UTC | akshare | daily_prices | 246 条/股 |
| 实时报价 | `*/30 * * * *` | UTC | yfinance/akshare | quote_snapshots | UPSERT |
| 指数历史 | `0 17 * * *` | UTC | yfinance | index_prices | 30 天/指数 |
| 涨跌榜 | `*/5 * * * *` | UTC | yfinance | movers_cache | 60 条 |
| 新闻 | `*/30 * * * *` | UTC | yfinance | news_articles | 10 条/symbol |
| 宏观 | `0 6 * * *` | UTC | oecd/federal_reserve | macro_indicators | 12-20 条/指标 |
| 财报 | `0 7 * * 1` | UTC | sec/yfinance | 3 张表 | 3 条/股 |

### 跟踪的股票

**15 只跟踪股票**：
- 美股：AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META, NFLX
- A 股：600519.SS, 000001.SZ, 300750.SZ, 601318.SS
- 港股：0700.HK, 9988.HK, 1810.HK

**12 个指数 + 大宗商品**：
- 美股：^GSPC, ^IXIC, ^DJI
- 港股：^HSI, ^HSCEI
- A 股：000001.SS, 399001.SZ, 399006.SZ
- 大宗：GC=F, CL=F, SI=F, BTC-USD

## API 端点

| 端点 | 方法 | 参数 | 功能 |
|---|---|---|---|
| `/api/quotes` | GET | `symbols=AAPL,MSFT` | 批量报价 |
| `/api/historical` | GET | `symbol, start_date, end_date` | 日 K 线 |
| `/api/indices` | GET | `symbol` 或 `market` | 指数历史/最新 |
| `/api/movers` | GET | `type, market, limit` | 涨跌榜 |
| `/api/news` | GET | `symbol` 或无 | 新闻 |
| `/api/macro` | GET | `name` 或无 | 宏观指标 |
| `/api/profile` | GET | `symbol` | 公司信息 |
| `/api/fundamentals/metrics` | GET | `symbol` | 基本面指标 |
| `/api/fundamentals/income` | GET | `symbol, limit` | 利润表 |
| `/health` | GET | 无 | 健康检查 |

## 性能对比

| 场景 | 改造前（直连 OpenBB） | 改造后（从 DB 读） | 提升 |
|---|---|---|---|
| 首页首次 | 10-30s | 182ms | 55-165x |
| 首页二次 | 10-30s | 81ms | 123-370x |
| AAPL 首次 | 5-23s | 704ms | 7-33x |
| AAPL 二次 | 5-23s | 92ms | 54-250x |
| OpenBB 宕机 | 页面空白 | DB 仍有数据 | ✅ |

## 文件清单

### 新建（backend）

```
apps/backend/
├── Dockerfile
├── requirements.txt
├── init.sql                          # 9 张表 DDL
└── app/
    ├── __init__.py
    ├── main.py                       # FastAPI 入口 + lifespan
    ├── config.py                     # 环境变量
    ├── db.py                          # asyncpg 连接池
    ├── openbb_client.py               # OpenBB HTTP 客户端
    ├── markets.py                     # pickProvider/pickMarket
    ├── scheduler.py                   # APScheduler 注册 7 个 job
    ├── jobs/
    │   ├── daily_kline.py             # 日 K 线
    │   ├── realtime_quotes.py         # 实时报价
    │   ├── indices.py                 # 指数历史
    │   ├── movers.py                  # 涨跌榜
    │   ├── news.py                    # 新闻
    │   ├── macro.py                   # 宏观数据
    │   └── fundamentals.py            # 公司信息 + 指标 + 财报
    └── api/
        ├── quotes.py                  # GET /api/quotes
        ├── historical.py               # GET /api/historical
        ├── indices.py                 # GET /api/indices
        ├── movers.py                  # GET /api/movers
        ├── news.py                    # GET /api/news
        ├── macro.py                   # GET /api/macro
        ├── profile.py                 # GET /api/profile
        └── fundamentals.py            # GET /api/fundamentals/*
```

### 修改

```
docker-compose.yml                     # 加 postgres + backend service
.devcontainer/docker-compose.yml      # 加 postgres + backend service（dev）
docker/openbb/Dockerfile               # uvicorn --workers 4 + pip uninstall cftc
apps/web/src/lib/openbb.ts             # 全部改用 backendFetch
apps/web/src/components/
  ├── market-overview.tsx              # 调用路径调整
  ├── movers-board.tsx                 # 从 backend 读
  ├── commodities-board.tsx            # 调用路径调整
  ├── treasury-board.tsx               # 用 backend macro 数据
  ├── macro-snapshot.tsx               # 调用路径调整
  └── app-layout.tsx                   # 侧边栏从 backend 读
apps/web/src/app/
  ├── page.tsx                         # 组件接口不变
  ├── heatmap/page.tsx                 # 从 backend 读
  ├── api/screener/route.ts            # 代理 backend
  └── api/quotes/route.ts              # 代理 backend
```

## 已知限制

1. **yfinance 被限流**：profile/metrics/news 在本地环境为空（yfinance 400），VPS 部署后可能可用
2. **A 股数据缺失**：akshare 被东方财富封 IP，A 股日 K 线为空，VPS 部署后需验证
3. **无实时推送**：阶段 4 可加 SSE（sse-starlette），盘中实时更新行情
4. **跟踪股票有限**：阶段 4 可扩展跟踪列表 + 支持用户自选股自动拉取
