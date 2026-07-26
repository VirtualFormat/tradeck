# 数据层重构：薄统一数据层 + akshare 限流 + TickFlow 迁移

分三阶段，每阶段可独立验证、独立提交。阶段 1 最紧急（解决 akshare 封 IP 风险），阶段 2/3 依赖阶段 1 的数据层门面。

## 1. 背景

tradeck 的数据获取现有**三种不一致形态**，限流/重试/降级/symbol 规范散落重复：

1. `apps/backend/app/openbb_client.py` 的 `fetch_openbb()` —— yfinance/fred/oecd + akshare 报价，已有海外韩国节点分流（见 `OVERSEAS-NODE.md`）。
2. backend **8 个 job 直调 `import akshare`** —— 各自 `try/except` + 硬编码 `asyncio.sleep`：
   `board_heat` / `board_map` / `fund_flow` / `market_breadth` / `announcements` / `research_reports` / `akshare_news` / `economic_calendar`(百度源)。
3. **provider 内调 akshare** —— `packages/openbb-akshare-provider/openbb_akshare_provider/models/stock_quote.py` 用**无上限 `asyncio.gather`** 对全部 symbol 齐发（realtime_quotes 一次 ~100 只、每只可能 2 次请求），**最高危封 IP 点**。

数据流：APScheduler 定时 job 取数写库 → API 只读 DB → 前端读 API。冷启动预热 `scheduler.py` 的 `_initial_fetch()` 启动时后台跑一遍所有 job。

## 2. 目标

1. **稳现状**：给 akshare 加限流/重试/错峰，解决封 IP 风险（最紧急）。
2. **正边界**：抽薄数据层门面，横切能力（限流/重试/降级/symbol/路由）收口一处。
3. **换更稳源**：把日K/指数迁到 TickFlow（官方 SDK，自带分片+并发闸+429退避），迁移后精简 akshare provider。

## 3. 关键约束：TickFlow 仅免费档

| 能力 | 限频 | 每次标的 | 周期 |
|---|---|---|---|
| A/港/美 日K | 10/min | **1 只/次** | 1d/1w/1M/1Q/1Y |
| A/港/美 实时报价 | 10/min | 5 只/次 | — |

**免费档没有**：universe 全市场、financials 财务、分钟线；日K **盘中不实时**。SDK 源码在 `../tickflow`（自带分片+并发闸+429退避）。

→ **实际能稳妥迁走的只有：日K + 指数 + 技术指标（随K线本地算）**。报价（非实时+配额）、财务（无）、全市场（无 universe）**都不迁**。

## 4. 三源终态职责（迁移后，职责零重叠）

| 源 | 职责 | 接入 |
|---|---|---|
| **TickFlow** | 日K / 指数K线（A/美/港） | 官方 SDK（自带横切） |
| **akshare** | A股**报价** + 深度数据（板块/资金流/研报/公告/龙虎/两融/北向/新闻/涨跌家数） | backend 直调（经统一 `call_akshare`） |
| **OpenBB** | 宏观/海外指标（fred/oecd/fed）/分析师/财报日历/财务(yf)/大宗/国债/美港股报价(yf) | `fetch_openbb`（海外节点） |

> akshare provider 的报价/K线 fetcher：`equity_historical`(日K)、`index_historical`(指数) 迁 TickFlow 后变孤儿可移除；`stock_quote`(报价) **保留**。其余 4 个 fetcher（`north_flow`/`margin_trading`/`dragon_tiger_list`/`concept_boards`）本就无 job 使用，一并清理。

---

## 阶段 1：薄数据层 + akshare 限流（立即做，稳现状）

### 1.1 新增 `apps/backend/app/datasource/` 薄门面

- `akshare_source.py`：进程级全局并发闸 + 退避重试 + symbol 规范 + 统一降级。

```python
import asyncio

_sem = asyncio.Semaphore(4)  # 进程级全局闸：定时任务/冷启动/未来主动load 共享同一上限

async def call_akshare(fn, *, retries=2, base_delay=0.5, backoff=1.5, throttle=0.5):
    """在全局信号量 + 线程池中执行 ak 调用；异常时指数退避重试；成功后节流。"""
    async with _sem:
        last_exc = None
        for attempt in range(retries + 1):
            try:
                r = await asyncio.to_thread(fn)
                if throttle:
                    await asyncio.sleep(throttle)
                return r
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(base_delay * backoff ** attempt)
        raise last_exc
```

- `openbb_source.py`：薄包现有 `fetch_openbb`（几乎直通）。
- 门面只做**路由 + 横切**，**不统一 schema**（各源字段仍在 job/provider 转换）。增量落地，不强制一次重写。

### 1.2 backend 8 处直调接入 `call_akshare`

上述 8 个 job 把 `await asyncio.to_thread(fetch)` 改为 `await call_akshare(fetch, throttle=...)`，**移除各自硬编码 `asyncio.sleep`**（节流交给门面）。原有 `try/except` 降级逻辑保留。

### 1.3 provider `stock_quote.py` 加并发闸（最高危必改）

`aextract_data` 的无上限 `asyncio.gather` → 加模块级 `_QUOTE_SEM = asyncio.Semaphore(4)`，`get_one` 包进 `async with _QUOTE_SEM:`；`fetch_individual` 两级降级（`stock_individual_info_em` → `stock_bid_ask_em`）外加 2 次退避重试。仍用 gather，但实际并发 ≤ 4。

> 注：provider 包与 backend 是独立包，backend 的 `call_akshare` 不能被 provider import，provider 层单独实现等价信号量+重试即可（语义一致）。
> `equity_historical.py`(单 symbol) / `index_historical.py`(串行 for) 无并发问题，阶段 1 不改（阶段 3 随迁移移除）。

### 1.4 冷启动预热受益（无需改代码）

`scheduler.py` 的 `_initial_fetch()` 顺序 `await` 每个 job。各 job 接入全局闸后**自动受限**，无需改 `_initial_fetch`。

### 1.5 调度错峰 `scheduler.py`

同 `minute="*/30"` 且碰 akshare 的 job 错开分钟（仍每 30 分一轮）：

| job | 现在 | 改为 |
|---|---|---|
| realtime_quotes | `*/30` | `0,30` |
| board_heat | `*/30` | `5,35` |
| akshare_news | `*/30` | `10,40` |
| market_breadth | `*/30` | `15,45` |
| board_sentiment（读DB，须在 board_heat 后） | `*/30` | `20,50` |

`news`/`news_score` 不碰 akshare，不动。频率周期不变。

**阶段 1 验证**：本地起 backend，触发 `run_realtime_quotes_job` / `run_akshare_news_job`，日志无异常、并发受限、降级行为不变（限流/断网返回空 results 或保留旧快照，不抛未捕获异常）。**独立提交**。

---

## 阶段 2：接 TickFlow，迁日K/指数（换稳源）

### 2.1 依赖 & 配置

- `apps/backend/requirements.txt` 加 `tickflow`。
- `apps/backend/app/config.py` + `docker-compose.yml` 加 `TICKFLOW_API_KEY`（免费档可空，用 `TickFlow.free()`）。

### 2.2 新增 `datasource/tickflow_source.py`

封装 `klines.get(symbol, period="1d", count=...)`。因免费档 **1 只/次 + 10/min**，adapter 内**串行 + 自限速**（≥6s/次，或依赖 SDK 内建 429 退避）。symbol 已是 `代码.市场后缀`（`600519.SH`/`AAPL.US`/`00700.HK`），与 tradeck 一致，几乎零映射。

### 2.3 迁 job（保留 DB schema 不变，只换取数源）

- `daily_kline.py`：A/美/港日K 改走 TickFlow（替换原 `pick_provider` → openbb 逻辑）。
- `indices.py`：指数 K线改走 TickFlow。
- `technical_indicators.py`：本地基于 `daily_prices` 算，**不动**（自动受益于新日K）。
- **不迁**：`realtime_quotes`（报价留 akshare/yf）、`fundamentals`（财务留 yf）、`movers`（无 universe）。

**阶段 2 验证**：触发 `run_daily_kline_job`，确认 100 只日K落库、耗时 ~10min 内、无封禁；技术指标随之正常。**独立提交**。

---

## 阶段 3：精简 akshare provider（清理孤儿）

- 迁移后 `equity_historical`(日K)、`index_historical`(指数) 无调用方 → 从 provider `__init__.py` 的 `fetcher_dict` 移除并删文件。
- 未使用的 `north_flow` / `margin_trading` / `dragon_tiger_list` / `concept_boards` fetcher 一并清理。
- **保留 `stock_quote`**（A股报价仍走 akshare provider，`realtime_quotes` 依赖）。
- 更新 `docker/openbb/Dockerfile`（国内含 akshare provider）；`Dockerfile.overseas` 本就不含，无需动。
- 可选：若清理后 provider 仅剩 `stock_quote`，评估整包退役 vs 改 backend 直调报价（视工作量）。

**阶段 3 验证**：`realtime_quotes`（A股报价）仍正常；OpenBB 端点 `/equity/price/quote?provider=akshare` 可用；无 import 报错。**独立提交**。

---

## 变更文件清单

- **新增**：`apps/backend/app/datasource/{__init__,akshare_source,openbb_source,tickflow_source}.py`
- **改 jobs**：`board_heat` / `board_map` / `fund_flow` / `market_breadth` / `announcements` / `research_reports` / `akshare_news` / `economic_calendar` / `daily_kline` / `indices`
- **改 provider**：`stock_quote.py`（加闸）；阶段 3 删 `equity_historical`/`index_historical` + 4 个未用 fetcher，改 `__init__.py`
- **改配置**：`scheduler.py`（错峰）、`config.py`、`requirements.txt`、`docker-compose.yml`、`docker/openbb/Dockerfile`

## 不做（范围外）

- 不迁报价/财务/全市场到 TickFlow（免费档不支持）。
- 不引入 Tushare/富途（富途港美股实时非当前所需；Tushare 全市场另议）。
- 不做统一 DTO（薄门面只统一横切，不统一 schema）。
- 不加代理 IP 池。

## 待实现时确认

- TickFlow 免费档 A股实时报价"盘中是否更新"——若可用且时效可接受，阶段 2 可评估把 `realtime_quotes` 也迁（30 只 / 6 次每分钟）。
- provider 仅剩 `stock_quote` 时是否整包退役（改 backend 直调报价）。

## 附：规模估算（当前 100 只 tracked）

- 一次全量拉取（`_initial_fetch`）：~25–30 个接口、~1000 次调用、限流后 8–15 分钟、DB 30–80 MB。
- 若放大到真·全市场（~1.2 万只）：~10–15 万次调用、限流下 10–15 小时、DB 3–8 GB，且单 IP 单机 akshare 逐股几乎必被封——全量应改用支持批量接口的源（如 Tushare），而非硬扛 akshare。
