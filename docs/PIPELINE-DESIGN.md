# tradeck 数据管道架构设计

## 1. 目标

将"前端实时拉 OpenBB"改为"backend 定时拉数据到 DB，前端从 DB 读"，实现 <50ms 页面加载。

## 2. 技术选型

### DB：PostgreSQL

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **PostgreSQL** | 官方 Docker 镜像成熟、功能全、JSON 字段、时序扩展 | 需独立容器 | ✅ 选 |
| DuckDB | 列式存储、适合分析 | 不是服务型 DB，要嵌入 backend 进程 | ❌ 不适合 docker service |
| SQLite | 无需额外服务 | 并发写差、无网络访问 | ❌ 多容器访问不便 |
| TimescaleDB | 时序优化 | PostgreSQL 超集，复杂度高 | ❌ 杀鸡用牛刀 |

**理由**：PostgreSQL 官方 Docker 镜像质量最高，postgres:16-alpine 仅 100MB，支持 JSON/全文检索/时序，未来可平滑升级 TimescaleDB。

### Backend：FastAPI + APScheduler

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **FastAPI + APScheduler** | Python 复用 OpenBB、APScheduler 嵌入式无需额外服务 | 单进程调度 | ✅ 选 |
| FastAPI + Celery | 分布式任务 | 要 Redis broker，多 2 个容器 | ❌ 过重 |
| Go + custom | 性能好 | 不能复用 OpenBB Python 生态 | ❌ 生态断层 |

**实时推送**：SSE（sse-starlette），比 WebSocket 简单，TickFlow 同款。

## 3. Docker Compose 架构

```
┌─────────────────────────────────────────────────────┐
│ docker-compose.yml（prod）                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐     │
│  │ web      │   │ backend  │   │ openbb       │     │
│  │ Next.js  │──▶│ FastAPI  │──▶│ OpenBB API   │     │
│  │ :3000    │   │ :8080    │   │ :6900        │     │
│  └──────────┘   └────┬─────┘   └──────────────┘     │
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
OpenBB (yfinance/akshare/sec)
    │
    │ ① backend 定时拉取（APScheduler）
    ▼
PostgreSQL（日K/指数/财报/新闻/宏观）
    │
    │ ② backend API 提供（FastAPI + SSE）
    ▼
Next.js Server Component（从 backend 读，<50ms）
```

## 4. DB Schema

```sql
-- 日 K 线（所有市场）
CREATE TABLE daily_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,        -- AAPL / 600519.SH / 0700.HK
    market CHAR(2) NOT NULL,            -- US / CN / HK
    date DATE NOT NULL,
    open DECIMAL(12,4),
    high DECIMAL(12,4),
    low DECIMAL(12,4),
    close DECIMAL(12,4),
    volume BIGINT,
    UNIQUE(symbol, date)
);
CREATE INDEX idx_daily_prices_symbol_date ON daily_prices(symbol, date DESC);

-- 指数历史
CREATE TABLE index_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,        -- ^GSPC / 000001.SH
    market CHAR(2) NOT NULL,
    date DATE NOT NULL,
    close DECIMAL(12,4),
    volume BIGINT,
    UNIQUE(symbol, date)
);

-- 实时报价快照（最新一条）
CREATE TABLE quote_snapshots (
    symbol VARCHAR(20) PRIMARY KEY,
    name VARCHAR(100),
    last_price DECIMAL(12,4),
    change DECIMAL(12,4),
    change_percent DECIMAL(8,6),
    volume BIGINT,
    market CHAR(2),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 新闻
CREATE TABLE news_articles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20),
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    summary TEXT,
    publisher VARCHAR(100),
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_news_symbol ON news_articles(symbol);
CREATE INDEX idx_news_published ON news_articles(published_at DESC);

-- 宏观指标
CREATE TABLE macro_indicators (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,          -- CPI / EFFR / Unemployment
    date DATE NOT NULL,
    value DECIMAL(12,6),
    UNIQUE(name, date)
);

-- 财报
CREATE TABLE income_statements (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    fiscal_year INT,
    total_revenue DECIMAL(18,2),
    net_income DECIMAL(18,2),
    gross_profit DECIMAL(18,2),
    operating_income DECIMAL(18,2),
    UNIQUE(symbol, fiscal_year)
);

-- 涨跌榜缓存（定时刷新）
CREATE TABLE movers_cache (
    type VARCHAR(20) NOT NULL,          -- gainers / losers / active
    market CHAR(2) NOT NULL,
    rank INT,
    symbol VARCHAR(20),
    name VARCHAR(100),
    price DECIMAL(12,4),
    percent_change DECIMAL(8,6),
    volume BIGINT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## 5. Backend 项目结构

```
apps/backend/
├── Dockerfile
├── pyproject.toml
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 环境变量配置
│   ├── db.py                    # SQLAlchemy + asyncpg
│   ├── scheduler.py             # APScheduler 任务注册
│   ├── jobs/
│   │   ├── daily_kline.py       # 盘后拉日 K（15:30）
│   │   ├── realtime_quotes.py   # 盘中轮询报价（30s）
│   │   ├── macro.py             # 宏观数据（每日）
│   │   ├── news.py              # 新闻（每 30 分钟）
│   │   ├── movers.py            # 涨跌榜（每 5 分钟）
│   │   └── financials.py        # 财报（每周）
│   ├── api/
│   │   ├── quotes.py            # GET /api/quotes?symbols=AAPL,MSFT
│   │   ├── historical.py        # GET /api/historical?symbol=AAPL&...
│   │   ├── indices.py           # GET /api/indices?market=us
│   │   ├── news.py              # GET /api/news?symbol=AAPL
│   │   ├── macro.py             # GET /api/macro
│   │   ├── movers.py            # GET /api/movers?type=gainers&market=us
│   │   ├── financials.py        # GET /api/financials/AAPL
│   │   └── stream.py            # SSE /api/stream（实时报价推送）
│   └── models/                  # SQLAlchemy ORM
└── alembic/                     # 数据库迁移
```

## 6. 定时任务

| 任务 | Cron | 时区 | 数据源 | 写入表 |
|---|---|---|---|---|
| 日 K 线 | `30 15 * * 1-5`（美股收盘后） | America/New_York | OpenBB historical | daily_prices |
| 日 K 线（A 股） | `30 15 * * 1-5`（A 股收盘后） | Asia/Shanghai | OpenBB akshare | daily_prices |
| 实时报价 | `*/30 * * * * 1-5`（盘中） | America/New_York | OpenBB quote | quote_snapshots |
| 指数历史 | `0 16 * * 1-5` | UTC | OpenBB index | index_prices |
| 涨跌榜 | `*/5 * * * * 1-5` | UTC | OpenBB discovery | movers_cache |
| 新闻 | `*/30 * * * *` | UTC | OpenBB news | news_articles |
| 宏观 | `0 6 * * *` | UTC | oecd/federal_reserve | macro_indicators |
| 财报 | `0 6 * * 1`（每周一） | UTC | SEC | income_statements |

## 7. 前端改造

Next.js Server Component 从调 OpenBB 改为调 backend：

```typescript
// 改前
const res = await fetch('http://openbb:6900/api/v1/equity/price/historical?...');

// 改后
const res = await fetch('http://backend:8080/api/historical?symbol=AAPL&...');
```

- **去掉 `fetchJSON` 的超时降级**（backend 不会超时）
- **去掉内存缓存**（backend 已有 DB 缓存）
- **保留 `MarketSwitcher`**（market 参数传给 backend）

## 8. 实时推送（SSE）

```python
# backend/app/api/stream.py
from sse_starlette.sse import EventSourceResponse

@app.get("/api/stream")
async def stream():
    async def event_generator():
        while True:
            quotes = await get_latest_quotes()
            yield {"event": "quotes", "data": json.dumps(quotes)}
            await asyncio.sleep(2)
    return EventSourceResponse(event_generator())
```

前端用 EventSource 订阅，实时更新行情。

## 9. 迁移计划

### 阶段 1：基础设施（先跑通）
1. 加 postgres + backend 两个 docker service
2. backend 实现 `/api/quotes` + `/api/historical`（从 DB 读）
3. 定时任务先只做日 K 线 + 实时报价
4. 前端改这两端点从 backend 读

### 阶段 2：全量数据
5. 加指数、涨跌榜、新闻、宏观、财报定时任务
6. 前端所有组件改从 backend 读

### 阶段 3：实时推送
7. backend 加 SSE 端点
8. 前端加 EventSource 订阅实时行情

## 10. 性能预期

| 场景 | 当前（实时拉 OpenBB） | 改造后（从 DB 读） |
|---|---|---|
| 首页加载 | 10-30s | <50ms |
| 个股详情页 | 5-15s | <50ms |
| 数据源故障 | 页面空 | 仍有 DB 历史数据 |
| 并发能力 | OpenBB 单点瓶颈 | PostgreSQL 轻松扛 |
