# 数据服务对外契约（Data Contract）

> 数据服务（tradeck）与消费方（量化业务 / web / 回测 / 未来任何项目）之间的
> **唯一边界**。拆分后消费方只能通过本文档定义的两个出口取数，其他一律禁止。
> 上游设计与铁律见 `docs/DATA-SERVICE.md`、`docs/DATA-STORAGE-TIERED.md`。

## 两个对外出口（除此之外无他）

```
数据服务（采集/清洗/质量/存储：PG 热层 + 冷层 Parquet）
   ├─ 出口 1：data-api REST（统一 HTTP 端口）
   └─ 出口 2：冷层 Parquet（只读文件资产）
```

| 出口 | 用途 | 形态 | 消费方 |
|---|---|---|---|
| **data-api REST** | 在线读、点查、近期窗口、实时/复权/批量 | HTTP/JSON | web、量化在线读 |
| **冷层 Parquet** | 历史批量扫、回测 | DuckDB/Parquet | 回测、研究 |

## 消费方取数规则（铁律）

1. **在线读 / 点查 / 近期窗口** → data-api REST（`/api/bars`、`/api/historical` 等）。
2. **历史批量扫 / 回测** → 冷层 Parquet（DuckDB 直读，见下「冷层消费约定」）。
3. **禁止**：
   - 直连 PostgreSQL（凭据仅 collector / data-api 持有）。
   - 直连数据源（findb / akshare / yfinance / OpenBB）——数据经数据服务采集后提供，消费方不碰源。
   - import 数据服务任何代码（collector / data-api 内部模块）。
   - 调用 collector 的写端点（`/api/ondemand`、`/api/system/jobs/*/run`）。

## 出口 1：data-api REST

统一 HTTP 端口（生产 `:8080`，dev `:8081`）。服务令牌鉴权（`X-Service-Token`，见 `_service_auth.py`）。

### 行情 / K 线

| 端点 | 说明 | 关键参数 |
|---|---|---|
| `POST /api/bars` | 批量日K（PG 原始价 × 复权因子） | `symbols[]`、`start_date`、`end_date`、`adjust`（空/qfq/hfq）、`limit` |
| `POST /api/bars/minute` | 批量分钟K（服务端 UNION 基线/增量并去重） | `symbols[]`、`start_date`、`end_date`、`limit` |
| `GET /api/historical` | 单标的日K（原始价） | `symbol`、`start_date`、`end_date` |
| `GET /api/quotes` | 实时报价快照 | `symbols`（逗号分隔） |

### 基本面 / 资讯 / 宏观

`GET /api/profile` `/api/fundamentals/*` `/api/analyst/*` `/api/news` `/api/macro` `/api/boards` `/api/fundflow` `/api/calendar` `/api/technicals` `/api/cn-extras` `/api/market-summary` `/api/search` —— 详见 data-api Swagger（`/docs`）。

### 系统 / 质量

`GET /api/system/data`（任务/库表/调度）、`GET /api/system/quality`（数据质量度量）。

## 出口 2：冷层 Parquet（数据服务内部只读）

**用途**：分钟K / tick 的全量历史，供回测批量扫描。**不是在线查询接口**。

### 布局（COS bucket `tradeck-lake`，或本地 `data-lake/`）

```text
bars/minute/asset=stock/market=CN|HK|US/symbol=.../year=YYYY.parquet
bars/minute_delta/asset=stock/market=CN|HK|US/year=YYYY/date=YYYY-MM-DD/part-000.parquet
```

两层 schema 统一为 `symbol / datetime(交易所本地无时区) / open / high / low /
close / volume / amount / source`。`bars/minute` 是 `symbol/year` 历史基线；
`bars/minute_delta` 是 `market/date` 全市场增量。查询必须 UNION 两层并按
`(symbol, datetime)` 去重，delta 优先。月度压实把上月及更早的完整 delta 原子
合并回基线，验证零漏键后删除对应 delta。

### 消费约定

- 在线与普通回测调用 `POST /api/bars/minute`，不得自行拼接单层文件。
- data-api 用 DuckDB 一次读取请求涉及的 symbol/year 基线和 market/date 增量，
  多标的统一扫描并在服务端去重。
- 大规模离线研究若未来开放文件资产，也必须复用同一 UNION/优先级语义。

### 示例（DuckDB）

```sql
WITH unioned AS (
  SELECT *, 0 AS priority FROM read_parquet('bars/minute/.../year=2026.parquet')
  UNION ALL
  SELECT *, 1 AS priority FROM read_parquet('bars/minute_delta/.../*.parquet')
)
SELECT * EXCLUDE(priority, rank)
FROM (
  SELECT *, row_number() OVER (
    PARTITION BY symbol, datetime ORDER BY priority DESC
  ) rank
  FROM unioned
)
WHERE rank = 1;
```

## 契约演进

- 新增对外能力只能加在这两个出口上（新 REST 端点 / 新冷层数据集），不新增第三种出口。
- 接口 schema 变更需向后兼容（只加字段不改语义），并更新本文档。
- 消费方接入前先读本文档；不按契约取数（直连 DB/源）视为违规。
