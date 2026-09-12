# tradb 独立部署切换指南（VPS 操作手册）

> 把数据服务从「tradeck 内嵌 collector/data-api」切换为「tradb 独立 compose 部署」。
> 任务清单与验收见 `plans/TASKS-TRADB-DEPLOY.md`；架构见 `docs/DATA-SERVICE.md`。
> 本文是 VPS 上的分步操作手册，含回滚与排障。命令假设两个仓库都已 clone 到 VPS。

> **状态（2026-09-12）：切换已完成。** tradeck 根 `docker-compose.yml` 已删除全部
> 内嵌数据服务（postgres/clickhouse/openbb/collector/data-api），只剩 `web` + `quant`，
> 经 `tradb_default` 外部网络访问 tradb。下文「步骤 4/5」「回滚」为切换期的历史记录，
> 保留作操作参考——**回滚需先从 git 历史恢复旧 compose**（见「回滚」一节），
> 新部署/日常维护只需看「拓扑」「步骤 1-3」「排障」。

## 拓扑

```
tradeck (web/quant)                      tradb (独立 compose)
  web  ─┐                                  postgres  :5432 (内部, 不映射)
  quant ─┼─ host.docker.internal ──▶ 127.0.0.1:8080  data-api  (唯一读出口, 鉴权)
        └─ (回环)                            127.0.0.1:8082  collector (唯一写者, 运维API)
                                             127.0.0.1:6900  openbb    (数据源代理)
                                             clickhouse :8123 (温层, 内部, 不映射)
```

要点：tradb 全服务只绑 `127.0.0.1` 回环；tradeck 经 `host.docker.internal:host-gateway`
（compose 已配）访问宿主机 localhost 上的 tradb。postgres/clickhouse 不映射宿主机端口。

## 前置

1. VPS 已 clone：`tradeck`（本仓库）与 `tradb`（`git clone https://github.com/VirtualFormat/tradb.git`）。
2. tradb 镜像已构建发布（CI `app-images.yml`，GHCR `ghcr.nju.edu.cn/virtualformat/tradb-*`）。
3. 准备 token：每个消费方一把 `openssl rand -hex 32`，web 与 quant 各一。

## 步骤 1 — 配置 tradb `.env`

```bash
cd tradb
cp .env.example .env
```

编辑 `.env`（关键项）：
- `POSTGRES_PASSWORD`：生产强密码（替换开发默认值）。
- `SERVICE_TOKENS={"<web_token>":"web-bff","<quant_token>":"quant"}`：填入刚生成的 token。
- `DATA_SYNC_TOKEN`：数据中心手动同步令牌（与 tradeck 侧一致）。
- 数据源密钥：`FINDB_KEY` / `HITHINK_FINANCE_API_KEY` / `TICKFLOW_API_KEY` 等（从 tradeck 现 `.env` 平移）。

## 步骤 2 — 数据迁移决策（二选一）

- **A. 新卷从零采集（推荐，最简）**：tradb 用全新 PG 卷 + 新 data-pool，启动后 collector
  自动全量初始化（日K ~250 天 + 分钟K 缺口追赶）。首次就绪需数十分钟，期间 data-api 优雅降级。
- **B. 复用现有数据**：把 tradeck 的 PG 数据目录与 `data-pool/` 挂到 tradb（停 tradeck 内嵌
  postgres 后），tradb 的 `./data-pool` 指向同一目录、PG 卷复用。省去重新采集，但要小心
  两套服务不能同时写同一库（铁律二单一写者）。

> 建议先 A 跑通，稳定后再考虑是否迁移历史数据。

## 步骤 3 — 启动 tradb

```bash
cd tradb
bash deploy/deploy-cn.sh        # 拉镜像 + compose up（经南京大学镜像站）
docker compose ps                # 5 容器健康：postgres/clickhouse/openbb/collector/data-api
curl http://127.0.0.1:8080/health            # -> {"status":"ok"}
curl http://127.0.0.1:8080/api/quotes        # -> 401（鉴权生效）
curl -H "X-Service-Token: <web_token>" http://127.0.0.1:8080/api/quotes   # -> 200（可能空，采集中）
```

## 步骤 4 — 切换 tradeck 到 tradb

编辑 tradeck `.env`：
```bash
TRADB_API_URL=http://host.docker.internal:8080
TRADB_COLLECTOR_URL=http://host.docker.internal:8082
TRADB_SERVICE_TOKEN=<web_token>
QUANT_SERVICE_TOKEN=<quant_token>
```

重启 web/quant：
```bash
cd tradeck
bash deploy/deploy-cn.sh        # 或 docker compose up -d web quant
```

验证：web 首页/个股页/宏观页渲染正常、数据中心面板任务状态正常（数据来自 tradb）。

## 步骤 5 — 停用 tradeck 内嵌数据服务

确认步骤 4 全链路正常后：
```bash
cd tradeck
docker compose stop collector data-api postgres clickhouse
# 观察 web 仍正常后，可选 docker compose rm -f collector data-api
```

> ⚠️ 若步骤 2 选 B（复用 PG/data-pool），不要删卷；仅停容器。

## 回滚

> ⚠️ tradeck 根 compose 已于 2026-09-12 删除内嵌服务，以下两条回滚路径的前提
> （内嵌服务仍在 compose 中）已不成立。如需回滚，先恢复旧 compose：
> `git show eb5e188:docker-compose.yml > docker-compose.yml`（`eb5e188` 为最后一个
> 仍含内嵌服务的提交），再按下述操作。

- **步骤 4 出问题**：把 tradeck `.env` 的 `TRADB_API_URL`/`TRADB_COLLECTOR_URL` 删去（回退默认
  值 `http://data-api:8080` 同 compose 服务名），重启 web/quant 即回到内嵌模式。内嵌服务在
  步骤 5 前一直保持运行，回滚零数据风险。
- **步骤 5 后回滚**：`docker compose up -d collector data-api postgres clickhouse` 重启内嵌服务 +
  回退 `.env`。

## 排障

| 现象 | 排查 |
|---|---|
| web 全站 401 | tradeck `.env` 的 `TRADB_SERVICE_TOKEN` 与 tradb `SERVICE_TOKENS` 的 web-bff token 不一致 |
| web 取数为空但无 401 | tradb collector 还在初始化采集（看 `docker logs tradb-collector`）；或数据源限流 |
| web 连不上 tradb | `docker exec tradeck-web curl -s http://host.docker.internal:8080/health`；确认 extra_hosts host-gateway 生效 |
| tradb data-api 起不来 | `docker logs tradb-data-api`；多为 PG 未健康或 DATABASE_URL 密码错 |
| collector 不写库 | `docker logs tradb-collector`；确认 DATA_MODE=live、scheduler 已注册 job |

## 切换后

- tradeck 仓库内嵌 `apps/backend` / `apps/data-collector` 代码退役删除（另一迭代，见任务 12）。
- 2026-09-12：tradeck 根 `docker-compose.yml` 已删除全部内嵌数据服务
  （postgres/clickhouse/openbb/collector/data-api）及失效的 `clickhouse-data` 卷、
  web 侧已无引用的 `OPENBB_API_URL`；prod 仅剩 `web` + `quant` 两个消费方服务。
- 分钟K 冷层暂留本地 `tradb/data-pool`，数据量上来后迁 COS（4.2b，见 `docs/DATA-STORAGE-TIERED.md`）。

## 数据隔离铁律（2026-09-08 生产教训，强制）

**禁止跨应用 bind mount 共享数据目录。** tradb 接管 tradeck 数据时，必须先把数据
**物理拷贝**到 tradb 自己的目录（`/data/apps/tradb/postgres`、`/data/apps/tradb/data-pool`），
再挂载自己的副本；绝不允许 tradb 与 tradeck 同时挂载同一份数据目录。

**事故经过**：初版切换让 tradb compose 直接 bind mount tradeck 的 `postgres/data` 与
`data-pool`（共享同一目录）。切换窗口 tradeck-postgres 被 compose 意外拉起，与 tradb-postgres
**并发写同一 PG 数据目录**（双写者，违背铁律二），导致：
- `daily_prices` 38,266 组 id 重复（双写者各取一段 id sequence 撞车，同逻辑行插两遍）；
- `daily_prices_pkey` / `data_quality_rejects_pkey` 索引损坏（zero page），日K 初始化写不进。

**修复（2026-09-08 已完成）**：停全服 → PG 与 122G data-pool **物理拷贝**到 tradb 独立目录
（`rsync -aH` 保留硬链接）→ tradb 改挂自己的副本 → 去重（删 38,266 冗余行）→ 重建 pkey →
从 PG 重建 2 个损坏的冷层 parquet（US 2025/2026 daily）。修复后 daily_kline 恢复正常写入。

**深度修复（同日二次，根治）**：首次去重只处理了 id 重复，REINDEX DATABASE 又暴露
`(symbol, date)` 业务键也有 14,417 组重复（内容冲突 0 组，纯冗余）。二次去重（删 40,245 行，
保留 id 最小行）→ `REINDEX DATABASE tradeck` 全库重建索引 → IndexCorrupted 彻底消失。
最终 daily_prices 去重后健康，daily_kline 恢复 `done: 11360 rows` 正常写入。

**操作要点**：
- 物理拷贝必须停写者（PG 数据目录任一时刻只能一个进程打开）。
- data-pool 含 32 万硬链接文件（findb 全量包去重），rsync 必须加 `-H` 保留硬链接，
  否则目标体积膨胀（169G vs 源 122G）。
- 迁移后全量扫一遍 parquet 可读性（`duckdb read_parquet`），损坏文件从 PG 重建。
- **双写者污染的排查顺序**：先查 id 重复（pkey），再查业务唯一键重复（symbol,date 等
  UNIQUE 约束），两者都可能有；REINDEX DATABASE 会逐个暴露，需先清干净重复才能重建索引。

## 已知缺陷（非迁移引入，待修）

**`TProtocolException: Invalid data`（2026-09-08 已根治，两因叠加）**：

1. **冷层 parquet 隐性损坏（主因）**：3 个文件（US 2025、US 2026、HK 2026 daily）内部
   row group 损坏——`count(*)`/`DESCRIBE` 可读，但 merge 的 `read_parquet(...) FULL OUTER
   JOIN incoming` 深层读取时报 `TProtocolException`。迁移前已损坏。**修复：从 PG 重建
   这 3 个文件**（PG 有完整数据）。排查教训：扫 parquet 健康要用 merge 的真实读取方式
   （JOIN 路径），`LIMIT 1`/`count(*)` 会漏检 row group 级损坏。
2. **daily_kline 高频写冷层（放大器）**：原按 50-symbol 分片、每片调一次 merge_daily_pool，
   每片都对同一年度 parquet 做 read+`os.replace`。分片越多，对损坏/被替换文件的读取越频繁。
   **修复：攒批一次 merge**——`_upsert_klines` 加 `pool_collector` 攒批参数，HK/US 冷层行
   攒齐本 universe 后一次性 merge（每 universe 每天 1 次，替代原每 market 数十次）。
   内存可控（HK/US 近 5 天日K 各约 1-2.3 万行，峰值几 MB）。

验证：修复后 daily_kline 全程 **0 次 TProtocolException**（原每分片数十次），
`日K 每日更新 done: 12596 rows` 正常，冷层 286 个 daily parquet JOIN 路径扫描 0 损坏。

另：`merge_daily_pool` 已加文件级 `asyncio.Lock`（`_MERGE_FILE_LOCKS`）作纵深防御——
同一 (year, market) 文件的 merge 在单进程内串行化。注意 asyncio.Lock 仅进程内有效，
生产纪律保持 collector 单进程写 data-pool。

## 分钟K 温层（2026-09-08 首次加载 + 两个修复）

分钟K 温层（ClickHouse `minute_bars`）首次加载，从冷层 delta 分区投影 **1648 万行**
（CN 622 万 + HK 79 万 + US 947 万）。过程暴露并修复两个 `serialize_rows`/`pool_source` bug：

1. **amount 可空**：findb 的 HK/US 分钟K 不返回成交额（`amount=None`），`serialize_rows`
   强制 `float(None)` 导致 HK/US 整天数据被全部拒收（backfill 写入 0 行）。修复：amount
   可空（None 填 0.0；OHLCV 才是必需字段）。
2. **US symbol 规范化**：findb 的 US 分钟K symbol 带 `.US` 后缀（AAPL.US），项目规范是
   美股裸码（AAPL）。`read_delta_day_as_utc` 原样透传导致查询侧（裸码）查不到。修复：
   pool_source 读冷层时剥离 US 的 `.US` 后缀（CN `.SH/.SZ`、HK `.HK` 本就是规范格式不动）。

**温层加载/更新逻辑**：
- **首次/重建回填**：`minute_warm_backfill` job（registry 手动触发），把冷层近 1 年
  `complete` 的 delta 分区逐日投影进 CH（`read_delta_day_as_utc` 本地→UTC + 先删后插幂等）。
- **每日增量**：`minute_kline` job（纽约盘后 17:45）写冷层 delta 分区后，把当日 merge 后的
  最终分区双写进 CH（`replace_market_day` 先删后插）。
- **查询**：data-api `GET /api/bars/minute`（≤50 只、窗口≤31 天、quant_access 鉴权）。
- **TTL**：CH `minute_bars` 表 `TTL ts + INTERVAL 1 YEAR DELETE`，在线窗口 1 年，全量历史
  留在冷层 data-pool（永久）。

## 板块舆情聚合为空（2026-09-09 诊断与修复）

**现象**：`board_sentiment` job 每次 `done: 0 rows`，板块舆情功能无数据。

**根因（代码体系不匹配，非数据源封锁）**：
- 聚合逻辑 `symbol_board_map × news_articles(24h已打分)`，JOIN 命中 0。
- `symbol_board_map` 只剩「汽车芯片」73 只残留（与近24h新闻 symbol 零交集）。
- `board_map` job（东财/同花顺板块成分反解）报 `覆盖不足: 710/1246 板块有成分，保留旧映射`。
- **真实原因**：board_heat 混两套代码体系——同花顺指数（`881/884/885/886.TI`）与
  申万/东财行业代码（`801/850/859.SI`）。同花顺成分接口只认 `.TI`（`.SI` 报
  `Unknown thscode`）。511 个 `.SI` 板块必然为空，把覆盖率拉到 59%（<80% 阈值），
  触发「保留旧映射」保护，symbol_board_map 永远停在残缺残留。
- **同花顺接口本身正常**（实测 `885402.TI` 返回 341 成分）；akshare 东财兜底才是真被封
  （`RemoteDisconnected`，已知限制）。

**修复**（`board_map.py`）：只对 `.TI` 板块取成分，覆盖率分母改为 `.TI` 板块数；
`.SI` 板块跳过（成分需东财/申万源，akshare 被封，待 QMT/AmazingData 接入后补）。

**遗留**：`.SI`（申万行业）板块的成分股暂无源（akshare 被封、同花顺不认 .SI），
待 QMT/AmazingData 数据源接入后补齐；board_map 的 akshare 降级在被封状态下每板块
白等 ~50s 超时，job 运行较慢（不影响正确性）。
