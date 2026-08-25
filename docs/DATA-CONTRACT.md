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
| `GET /api/historical` | 单标的日K（原始价） | `symbol`、`start_date`、`end_date` |
| `GET /api/quotes` | 实时报价快照 | `symbols`（逗号分隔） |

### 基本面 / 资讯 / 宏观

`GET /api/profile` `/api/fundamentals/*` `/api/analyst/*` `/api/news` `/api/macro` `/api/boards` `/api/fundflow` `/api/calendar` `/api/technicals` `/api/cn-extras` `/api/market-summary` `/api/search` —— 详见 data-api Swagger（`/docs`）。

### 系统 / 质量

`GET /api/system/data`（任务/库表/调度）、`GET /api/system/quality`（数据质量度量）。

## 出口 2：冷层 Parquet（只读）

**用途**：分钟K / tick 的全量历史，供回测批量扫描。**不是在线查询接口**。

### 布局（COS bucket `tradeck-lake`，或本地 `data-lake/`）

```
minute_bars/
  year=YYYY/market=CN|HK|US/date=YYYY-MM-DD/part-000.parquet   # 文件内按 (symbol, ts) 排序
tick/
  year=.../market=.../date=.../symbol=....parquet
```

schema（minute_bars）：`symbol / market / ts(UTC epoch 秒) / open / high / low / close / volume / amount`。

### 消费约定

- 用 **DuckDB `read_parquet()`** 读，按 `year/market` 分区谓词下推。
- **先拉本地工作缓存再算**（比直读对象存储稳）。
- **多标的用 `symbol IN (...)` 一次扫**，不要逐只查（避免重复扫全分区）。
- 单标的回测靠文件内 `(symbol, ts)` 排序的 row group 裁剪（详见 DATA-STORAGE-TIERED.md「三层读实现与性能评估」）。

### 示例（DuckDB）

```sql
-- 回测查 2024 年 A股某标的分钟K
SELECT * FROM read_parquet('s3://tradeck-lake/minute_bars/year=2024/market=CN/*.parquet')
WHERE symbol = '600036.SH' AND ts BETWEEN ... ;
```

## 契约演进

- 新增对外能力只能加在这两个出口上（新 REST 端点 / 新冷层数据集），不新增第三种出口。
- 接口 schema 变更需向后兼容（只加字段不改语义），并更新本文档。
- 消费方接入前先读本文档；不按契约取数（直连 DB/源）视为违规。
