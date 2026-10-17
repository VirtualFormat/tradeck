# 数据层：多源分工 + 薄门面 + 限流降级

tradeck 的数据获取收口到一层薄门面，横切能力（限流 / 重试 / 降级 / symbol 规范 / 路由）集中在 `apps/backend/app/datasource/`。数据流：APScheduler 定时 job 取数写库 → API 只读 DB → 前端读 API。

## 三源分工（职责零重叠）

> 2026-09 更新：A 股批量日级数据优先同花顺，findb 作为全量历史基线、
> 分钟K及同花顺未覆盖维度；AmazingData 代码保留但默认禁用。

| 源 | 职责 | 接入 |
|---|---|---|
| **TickFlow** | 日K（A/美/港，本地据此算技术指标） | 官方 SDK（自带分片 + 并发闸 + 429 退避），`datasource/tickflow_source.py` |
| **akshare** | A 股**报价** + 深度数据（板块 / 资金流 / 研报 / 公告 / 龙虎 / 两融 / 北向 / 新闻 / 涨跌家数） | 全部 backend 直调，经 `call_akshare`（报价用 `stock_zh_a_spot_em` 一次全市场→本地过滤） |
| **OpenBB** | 宏观 / 海外指标（fred/oecd/fed）/ 分析师 / 财报日历 / 财务(yf) / 大宗 / 国债 / 指数 / 美港股报价(yf) | `fetch_openbb`（海外源经韩国节点，见 [`OVERSEAS-NODE.md`](OVERSEAS-NODE.md)） |

### 当前生产路由

| 数据域 | 主源 | fallback / 补充 |
|---|---|---|
| A 股日K | 同花顺 `daily-k-10d` 全市场 dump | findb tracked 补缺 |
| A 股日级估值 | 同花顺 valuation snapshot（100只/批） | 暂无；失败不发布残缺快照 |
| A 股实时快照 | 同花顺批量 | akshare |
| A 股板块目录/行情/成分 | 同花顺指数 API | findb / akshare |
| CN/HK/US 分钟K | findb `codes` 批量 API，全进程节流 | 每日循环追赶全部缺口；无进展日留待下轮 |
| A 股资金流 | findb 全市场表 | 保留旧快照 |
| HK/US 日K | OpenBB/yfinance | findb 历史基线 |

findb API 调用共享进程级 1.05 秒间隔（约 57 次/分钟），避免板块、资金流、
分钟K等 job 各自并发突破单 key 的限频。分钟K每日使用最多 50 只/批的批量协议，
不再逐标的并发请求。

## 薄门面 `datasource/`

- **`akshare_source.call_akshare(fn, *, retries=2, base_delay=0.5, backoff=1.5, throttle=0.5)`**
  进程级全局并发闸 `Semaphore(4)`（定时任务 / 冷启动 / 主动 load 共享同一上限），在信号量 + 线程池中执行同步 akshare 调用，异常指数退避重试，成功后 throttle 节流。重试耗尽仍抛出，由调用方决定降级（返回空 results / 保留旧快照）。
- **`openbb_source.fetch_openbb`** —— 薄再导出，含海外节点分流。
- **`tickflow_source.get_daily_kline(symbol, count=365)`** —— 封装 `klines.get`（单只/请求），adapter 内串行 + 自限速（≥6s/次，**保守实现，非免费档硬约束**——免费档实为 IP 60 次/分钟且有 `klines.batch` 100 只/请求，待迁），SDK 内建 429 退避兜底；失败返回 `[]`。

> 门面只做**路由 + 横切**，**不统一 schema**（各源字段仍在 job/provider 内转换）。

### A 股报价（backend 直调批量 spot）
`realtime_quotes.py` 对 A 股一次调 `ak.stock_zh_a_spot_em()`（全市场 spot），本地按 tracked 代码过滤、映射到 `quote_snapshots`（名称/最新价/涨跌额/涨跌幅→小数/成交量），经 `call_akshare` 走统一限流闸；港/美股报价仍走 yfinance（`fetch_openbb`）。自写 OpenBB akshare provider 已整包退役。

## symbol 规范

业界无统一标准，两大阵营：Yahoo/Reuters 系用 `.SS`（沪）+ 港股 4 位不补零（`0700.HK`）；中国数据商系（Tushare/Wind/东财/TickFlow）用 `.SH/.SZ/.BJ` + 港股 5 位补零（`00700.HK`）；akshare 用裸 6 位代码。

**tradeck 规范格式**（DB / API / 前端统一，采中国数据商阵营，与 TickFlow 对齐）：

- A 股**个股**用 `.SH`（沪）/ `.SZ` / `.BJ`，港股 5 位补零（`00700.HK`），美股裸码（`AAPL`）。
- **指数保留 `.SS`**（走 yfinance，其上证指数用 `.SS`；如 `000001.SS`）。

**入向映射**（取数 → 规范格式）：

- `tickflow_source._to_tf_symbol`：`.SS`→`.SH`、港股补零、美股裸码补 `.US`（`AAPL`→`AAPL.US`）；DB 存规范格式。
- akshare：job 内 `split(".")[0]` 去后缀。

**出向映射**（规范格式 → yfinance/Yahoo）：`markets.to_yahoo_symbol()` —— `.SH`→`.SS`、港股 5 位去前导零成 4 位（`00700.HK`→`0700.HK`），其余原样。**凡调 yfinance（`fetch_openbb` provider=yfinance 或直调 yfinance 库）必须经此映射**；响应里的 Yahoo symbol 由调用方映射回规范格式再写库（参考 `realtime_quotes` 的 `yahoo_to_canonical` 写法）。

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

> 以下经 2026-07 对免费 API（`free-api.tickflow.org`）实测 + SDK 源码确认，取代早期「1 只/次、无 universe」的误判。

| 能力 | 免费档 | 说明 |
|---|---|---|
| A/港/美 日K `klines.get` | 单只/请求 | 周期 1d/1w/1M/1Q/1Y；**盘中不实时** |
| A/港/美 日K `klines.batch` | **100 只/请求** | SDK 自动分片 + 并发 5 + 分片级失败隔离 |
| 限频 | **IP 60 次/分钟** | SDK 不主动限速，内建 429 指数退避 |
| universe 标的池 | ✅ 可用 | 1013 个池：`CN_Equity_A` 5528 / `US_Equity` 11645 / `HK_Equity` 2841 / `CN_Index` 611（实测） |
| 指数日K | ✅ 可用 | 指数即 symbol（`000001.SH`/`399006.SZ`） |
| 实时报价 / 分钟K / 财务 | ❌ 无 | 报价仍走 akshare/yf，财务仍走 yf |

`TICKFLOW_API_KEY` 为空则用 `TickFlow.free()`。因此日K 走 TickFlow；报价（akshare/yf）、财务（yf）不迁。

## 边界（不做）

- 不迁报价 / 财务 / 全市场 / 指数到 TickFlow（免费档不支持）。
- 不引入 Tushare / 富途；不做统一 DTO（薄门面只统一横切）；不加代理 IP 池。

## 全市场规模提示

- **日K 全市场：免费档可行，已落地为 `daily_kline` job**。universe 拿清单 + `klines.batch`（100 只/请求，60 次/分钟）：三市 ~2 万只 ≈ 200 次请求（2026-07 实测全量初始化 ~5 分钟写入 ~310 万行）；首启自动全量一次，此后每日增量。
- **akshare 深度数据（板块/资金流/研报/公告/新闻）不能逐股全市场**：单 IP 逐股调东财几乎必被封——全市场层面的这类数据只能用其现成的批量榜单接口（movers/资金流/板块热度均为一次全市场调用），深度明细仍限 tracked 范围。
- 当前 tracked 100 只是手工精选列表（`daily_kline.py` `TRACKED_SYMBOLS`），是历史误判（「TickFlow 1 只/次」）下的保守产物，**不是任何源的硬上限**。
