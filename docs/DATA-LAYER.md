# 数据层：三源分工 + 薄门面 + 限流降级

tradeck 的数据获取收口到一层薄门面，横切能力（限流 / 重试 / 降级 / symbol 规范 / 路由）集中在 `apps/backend/app/datasource/`。数据流：APScheduler 定时 job 取数写库 → API 只读 DB → 前端读 API。

## 三源分工（职责零重叠）

| 源 | 职责 | 接入 |
|---|---|---|
| **TickFlow** | 日K（A/美/港，本地据此算技术指标） | 官方 SDK（自带分片 + 并发闸 + 429 退避），`datasource/tickflow_source.py` |
| **akshare** | A 股**报价** + 深度数据（板块 / 资金流 / 研报 / 公告 / 龙虎 / 两融 / 北向 / 新闻 / 涨跌家数） | 报价走 provider `stock_quote`；深度数据 backend 直调，经 `call_akshare` |
| **OpenBB** | 宏观 / 海外指标（fred/oecd/fed）/ 分析师 / 财报日历 / 财务(yf) / 大宗 / 国债 / 指数 / 美港股报价(yf) | `fetch_openbb`（海外源经韩国节点，见 [`OVERSEAS-NODE.md`](OVERSEAS-NODE.md)） |

## 薄门面 `datasource/`

- **`akshare_source.call_akshare(fn, *, retries=2, base_delay=0.5, backoff=1.5, throttle=0.5)`**
  进程级全局并发闸 `Semaphore(4)`（定时任务 / 冷启动 / 主动 load 共享同一上限），在信号量 + 线程池中执行同步 akshare 调用，异常指数退避重试，成功后 throttle 节流。重试耗尽仍抛出，由调用方决定降级（返回空 results / 保留旧快照）。
- **`openbb_source.fetch_openbb`** —— 薄再导出，含海外节点分流。
- **`tickflow_source.get_daily_kline(symbol, count=365)`** —— 封装 `klines.get`；免费档 1 只/次，adapter 内**串行 + 自限速（≥6s/次）**，SDK 内建 429 退避兜底；失败返回 `[]`。

> 门面只做**路由 + 横切**，**不统一 schema**（各源字段仍在 job/provider 内转换）。

### provider 报价并发闸
`stock_quote.py` 的 `aextract_data` 用 `asyncio.gather` 齐发多 symbol，加模块级 `_QUOTE_SEM = asyncio.Semaphore(4)` 把实际并发压到 ≤4，`fetch_individual` 两级降级（`stock_individual_info_em` → `stock_bid_ask_em`）+ 2 次退避重试。provider 是独立包，本地实现与 `call_akshare` 等价的语义。

## symbol 规范

- A 股**个股**用 `.SH`（沪）/ `.SZ` / `.BJ`，港股 5 位补零（`00700.HK`）。
- **指数保留 `.SS`**（走 yfinance，其上证指数用 `.SS`；如 `000001.SS`）。
- `tickflow_source` 内做入参映射：`.SS`→`.SH`、港股补零、美股裸码补 `.US`（`AAPL`→`AAPL.US`）；DB 存 tradeck 规范格式。

## 调度错峰

碰 akshare 且同为每 30 分钟一轮的 job 错开分钟，降低瞬时并发：

| job | 分钟 |
|---|---|
| realtime_quotes | `0,30` |
| board_heat | `5,35` |
| akshare_news | `10,40` |
| market_breadth | `15,45` |
| board_sentiment（须在 board_heat 后读 DB） | `20,50` |

`news` / `news_score` 不碰 akshare，不错峰。

## TickFlow 免费档约束

| 能力 | 每次标的 | 说明 |
|---|---|---|
| A/港/美 日K | 1 只/次 | 周期 1d/1w/1M/1Q/1Y；**盘中不实时** |

免费档**没有** universe 全市场、财务、分钟线。因此只迁**日K**到 TickFlow：报价（akshare/yf）、财务（yf）、全市场（无 universe）、指数（yf）均不迁。`TICKFLOW_API_KEY` 为空则用 `TickFlow.free()`。

## 边界（不做）

- 不迁报价 / 财务 / 全市场 / 指数到 TickFlow（免费档不支持）。
- 不引入 Tushare / 富途；不做统一 DTO（薄门面只统一横切）；不加代理 IP 池。

## 全市场规模提示

当前跟踪 100 只，一次全量 ~1000 次调用、限流后 8–15 分钟。若放大到真·全市场（~1.2 万只），单 IP 逐股 akshare 几乎必被封——全量应改用支持批量接口的源（如 Tushare），而非硬扛 akshare。
