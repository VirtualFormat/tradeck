# 数据服务拆分 — 技术方案

> 目标：把数据层从 web backend 拆为独立服务，为 web 看板、量化服务、量化回测提供统一数据源能力。
> 配套文件：任务拆解与验收见 `docs/TASKS-DATA-SERVICE.md`。

## 三条铁律

1. **DB 永不对外**：PostgreSQL 凭据只有 data-collector 和 data-api 两个进程持有；compose 不映射宿主机端口；任何消费方（含同语言量化进程）只能过 data-api。
2. **单一写者**：所有写库路径（UPSERT / TTL / 快照覆盖）收敛在 data-collector 一个进程；data-api 只读。
3. **优雅降级**：任何外部源失败返回空数据（`{"results": []}` / `[]`），消费方永远拿到可渲染响应。

## 架构拓扑

```
数据源层
  TickFlow（全市场日K）/ akshare 直调（A股报价+深度数据）/ OpenBB :6900（海外源，可分流韩国节点）
        ▲
        │ APScheduler cron（全部 UTC）
┌───────┴─────────────┐
│   data-collector    │  唯一写者 · --workers 1 · schema 所有者（init.sql）
│   scheduler + 22 jobs│
│   datasource 门面    │  Semaphore(4) 限流闸 + 退避重试 + 失败降级
└───────┬─────────────┘
        ▼ UPSERT 写库（幂等）
   PostgreSQL 16 ──── 不映射宿主机端口，仅 collector/data-api 可见
        ▲ 只读
┌───────┴─────────────┐
│     data-api        │  唯一读出口 · 多 worker · service token 鉴权占位
│  通用读 API + 量化契约 │
└───┬──────────┬──────┘
    ▼          ▼
 web-bff    量化服务 / 回测（数据落本地 Parquet 缓存，不重复打 API）
```

部署：compose 5 个 service — `postgres`（去端口映射）、`openbb`、`collector`（`--workers 1`）、`data-api`（多 worker）、`web`。依赖链 postgres/openbb 健康 → collector + data-api → web。

## 数据源（维持三源分工，全部收口在 collector）

| 源 | 职责 | 接入方式 |
|---|---|---|
| TickFlow | 全市场日K（CN 5528 + HK 2841 + US 11645） | collector 经 `datasource/tickflow_source` 调官方 SDK，100只/片批量并发 |
| akshare | A股报价 spot + 东财深度数据（板块/资金流/公告/研报/新闻/宽度） | collector 经 `datasource/call_akshare` 直调（Semaphore(4) 限流闸） |
| OpenBB | 海外一切（报价/财报/宏观/国债/指数） | collector 经 `datasource/openbb_source` 走 REST，可分流韩国节点 |

注意：OpenBB REST 只暴露标准模型，板块/资金流等自定义模型走不通，akshare 直调必须在 collector 保留，不要再塞回 OpenBB provider（历史弯路，已退役）。

## 数据分层

| 层 | 表 | 保留策略 | 服务谁 |
|---|---|---|---|
| 核心资产 | daily_prices、index_prices、macro_indicators、income/balance/cash_flow、equity_profiles、yield_curve_rates、macro_asset_prices | 永久 | 回测/量化/web 共用 |
| 衍生数据 | technical_indicators、market_breadth | 指标滚动窗口（全市场永久存会追平日K，需决策） | 量化/web |
| 业务快照 | movers_cache、board_heat、board_sentiment、fund_flow、analyst_consensus、earnings/economic_calendar | 30 天 TTL（日快照，可回看） | web 为主；共识快照有 point-in-time 价值 |
| 弱结构化 | news_articles、announcements、research_reports | 30/180 天 TTL | web + 情绪打分 |
| 瞬态 | quote_snapshots | 每标的 1 行 UPSERT，不增长 | web |

## 数据存储与容量

单实例 PostgreSQL 16，24 张表：

| 场景 | daily_prices 行数 | 全库估算 |
|---|---|---|
| 现状（首量 250 交易日） | 500 万 | 0.7-1.0 GB |
| 现状 3 年 | 2,000 万 | ~3 GB |
| 回测就绪（日K 补 10 年） | 5,000 万 | 5-7 GB |

- VPS 50-100 GB 卷够用，不分库不上分布式。
- daily_prices 到 1 亿行（20 年）再按 `(market, date)` 声明式分区，现在不做。
- TTL 由 cleanup job 兜底；「只增不减」仅限核心资产层，是设计意图。
- **红线：分钟级数据不进 PG**（2 万标的日增 480 万行）。需要时走 Parquet + DuckDB/ClickHouse，与 PG 并行。

## 对外数据接口（data-api）

1. **通用读接口**（现有 18 路由平移）：quotes/historical/indices/movers/news/macro/profile/fundamentals/analyst/boards/fundflow/calendar/technicals/cn_extras/cross_asset/market_summary/search/system。扁平数组，榜单类支持 `?date=` 快照回看。
2. **量化契约接口**（新增，阶段三）：
   - `POST /api/bars`：多 symbol × 时间区间批量日K，分页/流式。
   - `GET /api/snapshot/{table}?date=`：快照类表历史回看统一入口。
   - as-of 参数：`/api/fundamentals?symbol=X&as_of=YYYY-MM-DD`（依赖快照化改造）。
3. **运维接口**：`/health`、`/api/system/jobs`（`DATA_SYNC_TOKEN` 保护）、`/api/system/data`。

消费方约定：量化/回测拿到数据落本地 Parquet 缓存复用，不重复打 API；web 的按需回源（`_ensure`）保留为 data-api 内部端点，量化侧不继承。

## 量化契约接口（阶段三，已落地）

### 批量日K `POST /api/bars`

面向量化/回测的多标的历史行情批量拉取（替代单 symbol N 次调用）：

```json
// 请求
{"symbols": ["AAPL", "600519.SH"], "start_date": "2025-01-01", "end_date": "2025-12-31", "limit": 100000}
// 响应
{"bars": [{"symbol":"AAPL","date":"2025-01-02","open":..,"high":..,"low":..,"close":..,"volume":..,"amount":..}], "count": 456, "truncated": false}
```

- symbols 1-200 只白名单（`^[A-Z0-9.\-]{1,20}$`）；limit 默认 10 万、上限 50 万防 OOM。
- `truncated: true` = 被 limit 截断，消费方应缩小时间窗或分批。
- 单条 SQL（`symbol = ANY + date BETWEEN`）走 `(symbol, date)` 索引；按 symbol, date 升序。
- 非法请求体 422；DB 异常优雅降级返回空 bars，不 500。

### as-of 时点查询（最小可行版）

- `GET /api/analyst/consensus?symbol=X&as_of=YYYY-MM-DD`：日快照表（PK symbol+snapshot_date）原生支持，取该日期前最近快照，响应 `as_of_exact: true`。
- `GET /api/fundamentals/metrics?symbol=X&as_of=YYYY-MM-DD`：覆盖式最新值表（PK symbol），as_of 用 `updated_at::date <= as_of` 近似，响应 `as_of_exact: false`（无法还原历史值，精确 point-in-time 需阶段四快照化）。
- **as-of 路径均不触发按需回源**（回源拿到的是「现在」的值，对历史时点无意义且违背 point-in-time）。
- income/balance/cash 报表按 fiscal 期间天然有序，as_of 语义不同，本阶段不提供。

### 消费方鉴权（service token）

data-api 作为唯一数据出口，用 `X-Service-Token` + `X-Service-Name` 区分消费方（限流/审计/未来收紧）：

- 配置 `SERVICE_TOKENS`（JSON：`{"<token>": "<consumer_name>"}`）；空 = 内网放行（默认），仍可经 `X-Service-Name` 自报审计。
- 公开读接口（quotes/historical/...）：token 可空放行。
- 量化批量接口（/api/bars）：已配置 SERVICE_TOKENS 时强制有效 token（无/错 → 401）。
- 实现：`apps/backend/app/api/_service_auth.py`（`service_identity` 识别 + `quant_access` 强制）。

### 消费方接入约定

1. 量化/回测进程经 `POST /api/bars` 批量拉历史，落本地 Parquet 缓存反复用，不重复打 API。
2. 批量/重操作请求带 `X-Service-Token` + `X-Service-Name`（如 `backtest`）。
3. point-in-time 敏感的因子计算用 `as_of` 参数，并尊重 `as_of_exact` 标志（false 时知悉为近似）。
4. 任何消费方不得直连 DB；数据服务唯一入口是 data-api。

## 关键决策记录

- **不拆库**：24 张表 + 单一写者是一个整体，拆库会拆碎 UPSERT/TTL/跨表 JOIN。
- **不上消息队列**：cron + UPSERT 幂等够用，回测要的是可重放快照不是流。
- **量化不直连 DB**：同语言也不例外；性能用批量接口 + 消费方本地缓存补。
- **回测缺口**：fundamental_metrics/analyst_consensus 只存最新值，有前视偏差，阶段三快照化解决。
- **技术指标全市场存储**：会追平日K 容量，只存滚动窗口或按需算，不永久全存。

## 验证手段（沿用现有）

- `pnpm lint`（前端 ESLint）
- `bash docker/openbb/verify.sh`（数据层 8 项冒烟）
- backend `/health` + 各 `/api/*` 手测（Swagger）
- 部署前 `docker compose up -d --build` 全量自我验证
