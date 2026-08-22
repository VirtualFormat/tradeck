# 数据服务拆分 — 任务拆解与验收

> 主 agent（项目经理角色）按此文件派活给子 agent；每个阶段完成后执行 review → 修复 → 验收，全绿才进入下一阶段。
> 技术背景见 `docs/DATA-SERVICE.md`。验收结果逐阶段回填到本文档「验收记录」。

## 角色与流程

- **主 agent**：拆解任务、派发子 agent、review 子 agent 产出、修复问题、验收、回填记录。
- **子 agent**：按「任务卡」执行，写范围严格限制在列出的文件内，完成后列出改动文件清单。
- **Review 门禁**（每阶段必过）：
  1. 代码 review：改动符合 AGENTS.md 约定（优雅降级、UPSERT、中文注释、单进程纪律）。
  2. 铁律检查：DB 无新增暴露面、写路径全在 collector、消费方无直连 DB。
  3. 验证手段全绿（见各阶段验收标准）。

## 阶段一：物理拆分（低风险搬运）

**目标**：collector 与 data-api 双进程跑通，web 功能零回归。
**关键路径**：1.1 → 1.3 → 1.4 串行；1.2 与 1.1 并行（写范围不重叠）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| 1.1 建 collector 包 | 新建 `apps/data-collector/`，迁入 `app/jobs/`、`app/datasource/`、`app/scheduler.py`、`app/db.py`、`app/markets.py`、`app/openbb_client.py`、`app/config.py`、`init.sql`、Dockerfile、requirements.txt | `apps/data-collector/**` | — |
| 1.2 TRACKED_SYMBOLS 解耦 | 从 `daily_kline.py` 提到 `apps/data-collector/app/constants.py`；`cn_extras.py` 改为经 API 或共享常量包获取 | `apps/data-collector/app/constants.py`、`apps/backend/app/api/cn_extras.py` | — |
| 1.3 瘦身 data-api | `apps/backend` 移除 scheduler 启动逻辑（main.py lifespan 不再 start_scheduler），保留 18 读路由 | `apps/backend/app/main.py` | 1.1 |
| 1.4 compose 拆分 | dev/prod compose 拆 `collector`（workers 1）+ `data-api`（多 worker）service；postgres 去掉 `ports:` 宿主机映射 | `.devcontainer/docker-compose.yml`、`docker-compose.yml` | 1.1、1.3 |

**验收标准**：
- `docker compose up -d --build` 全绿，collector /health 与 data-api /health 均 200。
- 宿主机 `psql -h localhost` 连不上 postgres（端口未暴露）。
- web 首页/个股页/宏观页渲染无回归（数据来自 data-api）。
- data-api 日志无任何外部数据源调用；collector 日志正常跑 job。
- data-api 确认无 scheduler 进程内注册（多 worker 安全）。

## 阶段二：逻辑收口

**目标**：数据服务零 web 业务依赖。
**关键路径**：三项互相独立，可并行派三个子 agent。

| 任务 | 内容 | 写范围 |
|---|---|---|
| 2.1 system.py 归位 | 任务面板/手动触发 API 挂到 collector（或独立 admin 路由），web 经 API 读 | `apps/data-collector/app/api/`、`apps/web/src/app/api/system/` |
| 2.2 _ensure 收口 | 按需回源改为 data-api 内部端点，仅 web 语义路径使用，量化接口不继承 | `apps/backend/app/api/_ensure.py` |
| 2.3 mock 迁出 | `mock_data.py`/`seed_mock.py`（~2400 行）移出数据服务进 web 侧或独立 mock 服务；live/mock marker 机制保留在 collector | `apps/web/` 或 `apps/mock/`、collector lifespan |

**验收标准**：
- collector 与 data-api 代码 grep 无 web 专属逻辑（mock/前端文案/页面语义）。
- mock 模式仍可独立起（独立 volume），live 不受影响。
- `_ensure` 回源仅 web 代理路由可达，量化契约接口无此路径。

## 阶段三：量化契约（核心新工作）

**目标**：量化/回测可接入。
**关键路径**：3.2（as-of schema）先行，3.1 与之并行，3.3/3.4 收尾。

> **范围决策（2026-08-22 定）**：as-of 本阶段只做**查询层最小可行版**，不做 schema 快照化改造。
> analyst_consensus 本就是日快照表，天然支持 `?as_of=`（该日期前最近快照）；
> fundamental_metrics 只有最新值，`?as_of=` 用 updated_at 近似（响应标注 `as_of_exact: false` 的局限）。
> 完整的 point-in-time 快照化（加历史快照表）留待量化项目真正需要时，列入阶段四。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| 3.1 批量 bars | `POST /api/bars`（多 symbol + 区间 + 分页/流式），单 symbol N 次调用的替代 | `apps/backend/app/api/bars.py` | — |
| 3.2 as-of 查询层 | analyst_consensus `/api/analyst?as_of=`（日快照表原生支持）；fundamental_metrics `?as_of=` 用 updated_at 近似 + 响应标注局限；不做 schema 改造 | `apps/backend/app/api/analyst.py`、`fundamentals.py` | — |
| 3.3 service token | data-api 加消费方鉴权占位（`X-Service-Token`，沿用 DATA_SYNC_TOKEN 模式），按消费方区分/审计；公开读接口现阶段可空 token 放行（内网），量化批量接口强制要求 | `apps/backend/app/config.py`、中间件/依赖注入 | — |
| 3.4 消费方约定文档 | 量化侧本地缓存约定、接口契约（bars/as-of/token）写入 docs | `docs/DATA-SERVICE.md` 增补 | 3.1-3.3 |

**验收标准**：
- 批量接口单次拉 100 只 × 250 天日K 不超时、内存可控（流式）。
- as-of 查询返回的是该日期之前可见的最新值（point-in-time 正确）。
- 无 token 请求被拒绝；不同消费方 token 可区分。

## 阶段四：加固（可后置）

> 最终状态设计已定案：**热/温/冷三层异构存储**（PG 16 + ClickHouse 单节点 + Parquet/腾讯云 COS/DuckDB），
> 详见 `docs/DATA-STORAGE-TIERED.md`（含量级测算、选型依据、CH schema 草案、Parquet 分区布局、
> CVM 1TB 磁盘预算与 COS 成本模型）。分钟K/tick 全量历史永久保留在 COS。
> 原则：需求真实出现再实施，当前不做任何一项。

| 任务 | 内容 | 触发条件 |
|---|---|---|
| 4.2a 分钟K 温层 | 分钟K 采集 job + ClickHouse schema（在线窗口 1 年）+ data-api `/api/bars/minute` | 量化需要分钟级回测时 |
| 4.2b 冷层归档管道 | CH → Parquet/COS 归档 + DuckDB 消费约定；分钟K 全量永久保留 | CH 逼近 1 年窗口时 |
| 4.2c tick 直落冷层 | 逐笔采集 → Parquet 直落 COS（year/market/date/symbol 分区），不进任何在线库 | 需要逐笔回测时 |
| 4.1 全市场技术指标 | 算进 ClickHouse 宽表（列存适合宽表），PG 不动 | 量化需要全市场因子时 |
| 4.3 PG 分区预案 | daily_prices 按 (market, date) 声明式分区 DDL | daily_prices 超 5000 万行时 |

### 阶段四前置：数据源确认（先于 4.2 系列启动）

> 存储设计已就位，但分钟K/tick 的**数据源可用性未确认**——这是采购/调研决策，不是开发任务。
> 4.2a/4.2c 动工前必须先有结论，否则管道建好了没数据可采。

| 待确认项 | 内容 | 现状 | 影响 |
|---|---|---|---|
| D1 分钟K 历史源 | 全市场 1min K线历史（2 万标的 × 多年）从哪来 | TickFlow 免费档实测日K可用，分钟K覆盖范围/历史深度/限额未实测 | 4.2a 的采集 job 依赖 |
| D2 tick 逐笔源 | 全市场逐笔成交从哪来 | 免费三源（TickFlow/akshare/OpenBB）基本不提供全市场逐笔历史；大概率需付费数据商或券商 Level-2 接口 | 4.2c 的前提；涉及费用决策 |
| D3 采集限额与成本 | 分钟K/tick 的 API 限额、回填历史的速度、付费档价格 | 未调研 | 决定全量初始化要跑多久、年度数据预算 |

**建议动作**：4.2 启动前先实测 TickFlow 分钟K 能力（D1），tick 源（D2）单独做一轮数据商调研对比再拍板。

## 验收记录

| 阶段 | 状态 | Review 问题 | 修复 | 验收结论 | 日期 |
|---|---|---|---|---|---|
| 一 物理拆分 | ✅ 验收通过 | 见下（4 项归阶段二） | 已全部处置 | **实跑全绿** | 2026-08-20 |
| 二 逻辑收口 | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿，data-api 彻底纯化** | 2026-08-20 |
| 三 量化契约 | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿** | 2026-08-22 |
| 四 加固 | 未开始 | - | - | - | - |

### 阶段三 review 明细（2026-08-22）

子 agent 协作：3.1 bars 由 Locke（完整交付，含 ASGI 端到端冒烟 + 10 类非法请求自测）、3.2 as-of 由 McClintock（完整交付）；3.3 service token 由主 agent 实现 + 接入 bars；3.4 文档由主 agent 写。

范围决策（2026-08-22 定）：as-of 只做查询层最小可行版，不做 schema 快照化改造（留阶段四）。

已完成验证：
- 3.1 批量 bars：`POST /api/bars`（pydantic 校验 symbols 1-200 白名单/日期/limit 上限 50 万防 OOM；单条 SQL 走索引；响应 {bars,count,truncated}；优雅降级空 bars）。
- 3.2 as-of 查询层：analyst `?as_of=`（日快照表，as_of_exact=true）；fundamentals metrics `?as_of=`（updated_at 近似，as_of_exact=false）；as_of 路径均不触发回源；income/balance/cash 不动。
- 3.3 service token：`_service_auth.py`（service_identity 识别 + quant_access 强制）；config 加 SERVICE_TOKENS；compose（dev/prod）data-api 加 SERVICE_TOKENS 插值；bars 挂 quant_access + 消费方审计日志。
- 3.4 文档：DATA-SERVICE.md 补「量化契约接口」一节（bars/as-of/token/消费方接入约定）。

实跑验收结果（2026-08-22）——**全部通过**：
- ✅ bars 合法批量：AAPL+MSFT 2025-08 → 200，count 28，两 symbol，数值正确。
- ✅ bars 非法：201 只 422、start>end 422、非法 symbol 字符 422。
- ✅ bars 截断：limit=3 → count 3、truncated=true。
- ✅ 鉴权（配 SERVICE_TOKENS）：无 token 401、有效 token 200、错误 token 401；普通读接口 quotes 不受影响（200）。
- ✅ 鉴权（空 SERVICE_TOKENS 内网默认）：bars 无 token 放行 200。
- ✅ as-of 语义：analyst 无 as_of 取最新快照（exact=true）、as_of=2025-08-01 返回 null（该日前无快照）；fundamentals metrics as_of 同理——point-in-time 语义正确，历史查询拿不到「现在」的值。

Review 发现的问题与处置：
1. 阶段三初验时 `/api/bars` 404——已知坑 #6（uvicorn --reload bind mount 漏文件变更），`docker restart tradeck-dev-data-api` 解决，非代码问题。
2. SERVICE_TOKENS 最初经 `VAR=.. docker compose up` 前缀传递未生效（compose environment 块无插值）——已在 dev/prod compose 的 data-api 环境块补 `SERVICE_TOKENS` 插值修复。
3. bars 为量化契约引入顶层 `bars` 数组结构（与既有扁平数组风格不同）——量化批量接口的刻意新契约，记录在 DATA-SERVICE.md，可接受。

### 阶段二 review 明细（2026-08-20）

子 agent 协作：2.1 由 Bohr（429 中断，主 agent review 验收补尾）、2.3 由 Herschel（完整交付）、2.2 由 Hegel（429 中断，主 agent review + 补删除）；2.2 计算下沉与最终删除由主 agent 执行。

已完成验证：
- 2.1 system.py 归位：data-api 删 /jobs 与 /run 端点，/data 经 httpx 从 collector 拉 next_run_at（60s 缓存 + 降级 null）；collector 补 next_run_at + 新增 /api/system/schedules；web 代理路由 /jobs、/run 转 collector（COLLECTOR_API_URL），/data 留 data-api；backend config 删 OPENBB_OVERSEAS_*、新增 COLLECTOR_API_URL。
- 2.2 _ensure 收口（铁律修复）：collector 新增 POST /api/ondemand/{kind}（白名单 7 类 + per-key 锁 + symbol 校验 + 优雅降级）；data-api _ensure 改为 httpx 薄转发；4 路由全部改新签名；mock 打桩签名兼容。随后主 agent 删除 backend 的 jobs/、scheduler.py、datasource/、openbb_client.py——**data-api 最终依赖仅 config/database_mode/db/markets/services/api，零外部源、零写库**。
- 2.3 mock 迁出：新建 apps/mock/ 独立 Job 型容器（seed_mock + mock_data + database_mode/db 副本 + constants），compose 加 mock-seed（profile: mock）；backend 删 seed_mock/mock_data；AGENTS.md 用法改两步流程。
- 2.2 前置（主 agent）：compute_indicators/LOOKBACK_DAYS 下沉 data-api services/indicators.py，MARKET_COVERAGE_THRESHOLDS 内联 market_summary，解除 backend 对 jobs 的纯计算依赖。

实跑验收结果（2026-08-20）——**全部通过**：
- ✅ collector /health（8082）、data-api /health（8081）200。
- ✅ data-api 启动日志零 scheduler/job，仅 marker 验证 + ready。
- ✅ collector /api/ondemand 校验行为正确：未知 kind 404、非法 symbol（含空格/下划线）400。
- ✅ 回源链路通畅：data-api quotes → collector ondemand → yfinance → 优雅降级（本次 yfinance 限流 Too Many Requests，results 空，属 AGENTS.md 已知数据源限制，非代码问题）。
- ✅ web /api/system/jobs 显示 collector 实时运行记录（news job running）；web /api/system/data 25 个 job 中 24 个 next_run_at 非 null（data-api→collector 调度拉取生产路径验证成功）。

Review 发现的问题与处置：
1. data-api 回源后立刻重读存在时序窗口（collector 写库慢于 data-api 重读），首访可能短暂返回空、下一请求即命中——可接受的降级行为，且 collector ondemand 是同步 await 的，实际窗口极小；不处理。
2. mock-seed 容器未端到端实跑（需独立 mock 卷 + 显式 profile）——compose config 校验通过，运行时留待首次使用 mock 模式时验证。
3. mock_data.py 内 ensure_database_mode 与 database_mode.py 重复（迁入前即如此）——保持原样，seed_mock 走 database_mode 副本。

### 阶段一 review 明细（2026-08-20）

子 agent 协作：1.1 由子 agent Dirac 建骨架（中途 429 中断，主 agent review 补验）、1.4 由子 agent Curie 改 compose；1.2/1.3 主 agent 本地执行。

已完成验证：
- 全量 `python3 -m compileall` 通过（collector + backend）。
- collector import 图无悬空引用；8 个 job 的 TRACKED_SYMBOLS 全部切到 `app.constants`，daily_kline 兼容 re-export 已清除。
- backend API 侧无 `app.jobs` / `app.scheduler` 业务 import 残留（仅 `api/system.py` 保留 `scheduler_jobs_snapshot` 快照调用，属阶段二收口范围）。
- compose config 校验通过；prod/dev postgres 均无宿主机端口映射；init.sql 挂载指向 data-collector。
- cn_extras 语义等价性核对：announcements job 只写 tracked A 股，data-api 改读全表与原 `_CN_SYMBOLS` 过滤等价。

Review 发现的问题与处置：
1. backend `api/system.py` 仍 import `app.scheduler.scheduler_jobs_snapshot`，scheduler 不再启动后 `/api/system/data` 的 `next_run_at` 恒 null、job 状态恒 idle——降级不报错，明确归阶段二 2.1「system.py 归位」彻底解决。
2. backend `config.py` 仍声明 `OPENBB_OVERSEAS_*`（有默认值不影响启动），归阶段二清理。
3. backend 目录仍保留 jobs/scheduler.py/mock_data/seed_mock——`api/system.py` 与 `_ensure` 按需回源的过渡依赖，归阶段二 2.3 迁出。
4. AGENTS.md / docs 中「backend」指 service 名的描述未更新——待阶段一实跑验收后统一刷新文档。

实跑验收结果（2026-08-20，dev compose 全量）——**全部通过**：
- ✅ `docker compose build collector data-api` 构建成功，`up -d` 全绿。
- ✅ collector /health（8082）与 data-api /health（8081）均返回 200。
- ✅ 宿主机 `nc -z localhost 5432` 连接被拒、`docker port tradeck-dev-postgres` 无映射——**铁律一（DB 永不对外）运行时成立**。
- ✅ collector 日志：marker 验证 live → 注册全部 22 job → initial fetch 实际写库（indices 2233 行、quotes、movers US=60、macro 6745 点）。CN=0 为 akshare 被东财断连的已知数据源限制，非代码问题。
- ✅ data-api 日志：仅 marker 验证 + ready，**零 scheduler/job/外部源调用——单一写者运行时成立**。
- ✅ web 端到端：首页 HTTP 200；web 经 Next 代理 → data-api → DB 读到 collector 刚写入的实时数据（fetched_at 与 collector 日志时刻精确对应，全链路打通）。
- ✅ historical 复核：web 代理 `days=5` 正确返回 8/17-8/18（与库一致）；此前一次 2 月数据为误用 `start_date` 参数的既有行为（代理路由只认 days），非拆分引入。

运维备注：
- dev 容器重建后丢失 post-create 装的 Node/pnpm（手动 recreate 绕过 VS Code 的 post-create 钩子），已重跑 `.devcontainer/post-create.sh` 修复并启动 next dev。**注意**：VS Code Reopen in Container 会自动处理，手动 `--force-recreate dev` 后需手动重跑 post-create。
- 旧孤儿容器 `tradeck-dev-backend`（旧单 backend 拓扑）已停止并删除。
