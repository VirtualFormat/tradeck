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
| 4.2a-0 分钟K PG 先行（快速项） | PG 建 `minute_bars` 表（schema 同 CH 草案：symbol/market/ts(UTC)/OHLCV/amount）+ collector 每日分钟K job（A股先行，失败重试 + 缺口检测 + 幂等 UPSERT）。不等 CH 落地，先把每日数据攒起来；CH 就位后整体迁移 | 分钟K 数据源确认（D1）后即刻启动 |
| 4.2a 分钟K 温层 | 分钟K 采集 job + ClickHouse schema（在线窗口 1 年）+ data-api `/api/bars/minute` | 量化需要分钟级回测时 |
| 4.2b 冷层归档管道 | CH → Parquet/COS 归档 + DuckDB 消费约定；分钟K 全量永久保留 | CH 逼近 1 年窗口时 |
| 4.2c tick 直落冷层 | 逐笔采集 → Parquet 直落 COS（year/market/date/symbol 分区），不进任何在线库 | 需要逐笔回测时 |
| 4.1 全市场技术指标 | 算进 ClickHouse 宽表（列存适合宽表），PG 不动 | 量化需要全市场因子时 |
| 4.3 PG 分区预案 | daily_prices 按 (market, date) 声明式分区 DDL | daily_prices 超 5000 万行时 |

### 阶段三.五：数据质量层（Data Quality Layer，质量架构）

> 背景（2026-08-22 评审发现 + 定案）：collector 的清洗原只有「点状防御」（各 job 字段
> 解析容错 + fund_flow 有效行数闸），无异常值校验、无一致性、脏数据静默入库。
> **决策：前置建独立质量层，不做轻量校验函数**——数据管道「写一次读千次、错了污染
> 下游」，后置重构（改 22 job + 迁移存量脏数据 + 回测作废）成本远高于现在把层建对。
> 分钟K 上量（4.2 系列）前必须就位，否则缺口放大两个数量级。

**架构定位**：collector 内介于「datasource 拉取」与「写库」之间的独立质量闸（`app/quality/` 子包）。

```
数据源 → datasource 门面 → ┌─ 数据质量层 app/quality/ ─┐ → 写库（只放合格数据）
                            ① normalize 标准化（类型/单位/symbol）
                            ② validate 校验（P0 物理/P1 损坏/P2 可疑）
                            ③ quarantine 处置（拦截落库留痕）
                            ④ metrics 度量（质量分/拒绝率）
```

**核心设计决策**：
- 独立子包 `app/quality/`（normalize/validate/rules/quarantine/metrics），不散在 services。
- 规则声明式：每张表一份 `QualityRule`（dataclass），字段级/行级/表级分开，可枚举可测试。
- 处置三态：`ACCEPT`（写库）/ `REJECT`（拦截 + 落 quarantine 表）/ `REPAIR`（自动修：类型/日期/symbol 归一）。
- 两张新表（collector 独占写，init.sql + 存量卷 ALTER 迁移）：
  - `data_quality_rejects`（source_table/symbol/raw_payload jsonb/reject_reason/severity/rejected_at）— 脏数据留痕可审计。
  - `data_quality_metrics`（table_name/date/total/accepted/rejected/repaired/quality_score）— 质量可观测。
- job 接入契约：写库前统一 `await quality_gate(table, rows) -> accepted_rows`（一行调用，规则集中在层里演进）。
- 规则分级（避免误杀真实异动）：P0 物理不可能（REJECT）；P1 明显损坏（REJECT+warn）；P2 可疑（ACCEPT+标记，不拦，供量化侧自决）；REPAIR 自动修。
- 三条铁律映射：quality_gate 自身异常 → 记日志放行（宁可漏拦不可误停管道）；quarantine/metrics 由 collector 独占写；P2 只标记不拦截。

| 任务 | 内容 | 写范围 | 阶段 |
|---|---|---|---|
| Q1 骨架 | `app/quality/` 子包 + QualityRule 声明式框架 + `quality_gate` 统一入口 + quarantine/metrics 两表 DDL（init.sql + main.py 存量 ALTER） | `apps/data-collector/app/quality/`、`init.sql`、`main.py` | 本次 |
| Q2 日K/报价接入 | 4 个 OHLC job（daily_kline/realtime_quotes/indices/macro_assets）接入 quality_gate + P0/P1 规则 + REPAIR | 上述 4 个 job 文件 | 本次 |
| Q3 度量与可观测 | data_quality_metrics 聚合写入 + job 日志拒绝率（`=== xxx done: N rows, rejected M ===`）+ data-api `GET /api/system/quality` 只读端点 | quality/metrics.py、各 job、`apps/backend/app/api/system.py` | 本次 |
| Q4 规则全覆盖 | 榜单/宏观/基本面表规则 + P2 统计标记（Z-score 离群、跳空） | 其余写库 job | 下一迭代 |
| Q5 分钟K 质量 | 缺口检测/多源对账/复权一致性（分钟K 特有） | quality/rules/ | 随 4.2 系列 |

**验收标准（Q1-Q3）**：
- 构造含 P0（high<low、负价、缺 close）、P1（涨跌幅越界）、可 REPAIR（字符串数值/小写 symbol）的输入，quality_gate 正确三态处置，valid 行不受影响。
- 脏行落 `data_quality_rejects`（含 raw_payload/reject_reason/severity），质量聚合落 `data_quality_metrics`。
- 4 个 OHLC job 接入后正常跑通，日志出现 rejected 计数（正常源下应为 0）；其余 job 行为不变。
- 优雅降级：quality_gate 自身异常记日志放行，不阻断写库。
- data-api `GET /api/system/quality` 可读到质量度量（data-api 只读，不写）。

### 分钟K 采集策略（2026-08-22 定）

**「现在开采 + 历史后补」**：分钟K 是时间敏感型资产——当日不采即永久丢失，
历史数据则可延后采购导入。两路合流由存储设计天然支持（CH 按 symbol+ts 排序、
COS 按 year/market 分区，schema 一致即可无缝拼接）。

- **美股/港股**：yfinance 1m 仅近 7 天窗口，但「每日采当日」模式下窗口永远追不上采集——可免费起步。
- **A股**：候选 TickFlow 付费档（SDK 已在用）/ akshare 东财分钟接口（免费但限流风险）/ QMT / iFinD（调研中，见 D4）。
- **纪律要求**：ts 统一存 UTC；每日 job 必须幂等 UPSERT + 缺口报警。

### 阶段四前置：数据源确认（先于 4.2 系列启动）

> 存储设计已就位，但分钟K/tick 的**数据源可用性未确认**——这是采购/调研决策，不是开发任务。
> 4.2a/4.2c 动工前必须先有结论，否则管道建好了没数据可采。

| 待确认项 | 内容 | 现状 | 影响 |
|---|---|---|---|
| D1 分钟K 历史源 | 全市场 1min K线历史（2 万标的 × 多年）从哪来 | **已实测（2026-08-22）**：TickFlow SDK 原生支持分钟K（`klines.intraday`/`intraday_batch`，Period='1m/5m/10m/15m/30m/60m'），但**免费档 403 拒绝**（`PermissionError: 免费服务不支持日内分时数据`）。分钟K 需付费档 | 4.2a 的采集 job 依赖 |
| D2 tick 逐笔源 | 全市场逐笔成交从哪来 | 免费三源（TickFlow/akshare/OpenBB）基本不提供全市场逐笔历史；大概率需付费数据商或券商 Level-2 接口 | 4.2c 的前提；涉及费用决策 |
| D3 采集限额与成本 | 分钟K/tick 的 API 限额、回填历史的速度、付费档价格 | 未调研 | 决定全量初始化要跑多久、年度数据预算 |
| D4 QMT/iFinD 调研 | 迅投 QMT（券商量化终端）与同花顺 iFinD 的分钟K/tick 覆盖、API 形态、成本 | 调研中 | 可能替代/补充 D1、D2；iFinD 另有 Kimi 集成的金融数据库形态待确认 |

**D1 实测明细（2026-08-22）**：
- **接口形态** ✅：`klines.intraday(symbol, period, count)` 单只 + `intraday_batch(symbols, period, count, batch_size=100)` 批量（与日K 同 SDK、同批量分片模式，接入成本低）。
- **周期覆盖** ✅：`1m / 5m / 10m / 15m / 30m / 60m`（另有 1d/1w/1M/1Q/1Y）。
- **免费档权限** ❌：intraday 调 `600519.SH` 返回 HTTP 403「免费服务不支持日内分时数据」。日K 免费，分钟K 必须付费档。
- **未实测（需付费 key）**：付费档的分钟K 历史深度（能回填多少天）、全市场覆盖（CN/HK/US 是否都有）、限额与价格。
- **akshare 东财分钟接口** ❌：`stock_zh_a_hist_min_em(600519, period='1')` 被断连（RemoteDisconnected，与东财 spot 同命运，AGENTS.md 已知限制）——A股分钟K 免费路径本地不可行，需 VPS 实测或走付费源。

**建议动作**：D1 已确认「TickFlow 付费档有分钟K 接口」——下一步是**评估付费档**（注册试用 key，实测历史深度/覆盖/限额/价格，填 D3），与 D2（tick 源）、D4（QMT/iFinD 调研）合并做一轮数据商对比再拍板。免费路径现状：美股/港股可用 yfinance 1m（近 7 天窗口）起步；**A股分钟K 免费路径（akshare 东财）本地被封**，只能走 TickFlow 付费档 / QMT / iFinD。

## 验收记录

| 阶段 | 状态 | Review 问题 | 修复 | 验收结论 | 日期 |
|---|---|---|---|---|---|
| 一 物理拆分 | ✅ 验收通过 | 见下（4 项归阶段二） | 已全部处置 | **实跑全绿** | 2026-08-20 |
| 二 逻辑收口 | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿，data-api 彻底纯化** | 2026-08-20 |
| 三 量化契约 | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿** | 2026-08-22 |
| 三.五 数据质量层（Q1-Q3） | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿，端到端闭环** | 2026-08-22 |
| 三.五 数据质量层（Q4） | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿，规则全覆盖** | 2026-08-22 |
| 三.五 数据质量层（Q6 面板） | ✅ 验收通过 | 见下 | 已全部处置 | **实跑全绿，首日即抓到真实误拦** | 2026-08-22 |
| 四 加固 | 未开始 | - | - | - | - |

### 阶段三.五 Q6 review 明细（数据质量面板，2026-08-22）

Q6 前端由子 agent Faraday 完成（代理路由 + 质量 Tab）；阈值误拦修复由主 agent 诊断 + 实施。
D1 分钟K 数据源实测由主 agent 完成（见下「D1 实测」），已另行提交。

已完成验证：
- 质量代理路由 `/api/system/quality`（web → data-api），失败降级空。
- 数据面板新增「数据质量」Tab：质量分概览（分色 Card/Badge）+ 近 7 天同步状态 + 拦截样本
  （severity 分色，P2 标「可疑但已放行」）。lint 通过、检查清单全绿（无裸元素/手搓/图标库违规）。
- 面板数据经 web 代理可达：5 表质量分 + 100 条拦截样本真实渲染。

**Q6 上线首日抓到真实误拦（观测价值实证）**：
- 现象：board_heat 质量分仅 0.6222（270 行 rejected 102），面板暴露了异常。
- 诊断：102 条拦截全为「change_percent 越界 ±1.0」，但东财板块涨跌幅是**百分数口径**
  （1.04 = 1.04%），我误将阈值按小数口径设 ±1.0 → 正常板块涨跌（1-3%）大量误拦。
- 修复：board_heat 阈值 ±1.0→±50、fund_flow ±1.0→±40（百分数口径，覆盖涨停留余量）。
- 验证：修正后误拦的 1.04%/-3.54% 放行，负市值仍正确拦截。
- 启示：质量度量不只是拦脏数据，也暴露规则自身的误设——面板是数据可靠性的反馈回路。

### D1 实测明细（2026-08-22，分钟K 数据源）

- TickFlow SDK 原生支持分钟K（`klines.intraday`/`intraday_batch`，Period=1m/5m/10m/15m/30m/60m），与日K 同 SDK 同批量模式，接入成本低。
- 免费档 403 拒绝分钟K（PermissionError：不支持日内分时）；分钟K 必须付费档。
- akshare 东财分钟接口本地被断连（已知封 IP 限制），A股分钟K 免费路径本地不可行。
- 未实测：付费档历史深度/全市场覆盖/限额价格（需注册试用 key，归 D3）。

> **阶段三.五收尾（2026-08-22）**：质量层两表已纳入 cleanup TTL（90 天，commit e307fa4）；
> Q4 记录的「movers percent_change 口径不一致」经实测证伪（库内两市场均为小数，子 agent 误报）。
> **质量层后端（Q1-Q4 + TTL）已完整收口。** 剩余 Q5（分钟K 质量）随 4.2 系列、Q6（质量面板）见下。

#### Q6 数据质量面板（独立前端任务，待启动）

> 质量层后端已产出 metrics/rejects 数据并经 data-api `/api/system/quality` 暴露，
> 但前端尚未展示——质量层的价值闭环需要一个可视化入口。这是独立前端迭代，
> 须遵守 AGENTS.md「UI 强制规则」（shadcn 组件、检查清单、Server/Client 边界、空态统一）。

| 任务 | 内容 | 写范围 |
|---|---|---|
| Q6.1 质量 Tab | 数据面板（data-page-client.tsx）新增「数据质量」Tab：质量分概览（各表 score）+ 近 N 天拦截/修复统计 + 最近拦截样本表（quarantine）。用 shadcn Tabs/Table/Badge/Empty，禁手写 | `apps/web/src/components/data/` |
| Q6.2 质量代理路由 | Next 代理 `/api/system/quality` 转发 data-api（参照现有 system 路由模式） | `apps/web/src/app/api/system/quality/route.ts` |
| Q6.3 P2 展示区分 | 拦截样本按 severity 分色 Badge（P0/P1 红、P2 黄），文案标明 P2 为「可疑但已放行」 | 同 Q6.1 |

### 阶段三.五 Q4 review 明细（规则全覆盖 + P2 统计标记，2026-08-22）

主 agent 升级规则框架（non_negative_fields + P2 配置）与 statistical.py（P2 批级检测）；
Q4 接入由子 agent Lagrange 完成（7 job、11 处）。

已完成验证：
- 规则框架升级：`QualityRule` 加 `non_negative_fields`（P0 数值非负）+ `zscore_field`/`daily_gap`（P2 配置）；
  `validate_row` 接入 non_negative 检查；RULES 新增 13 张表规则（榜单/指标/基本面/宏观）。
- P2 统计标记：新建 `statistical.py`（`detect_outliers_zscore` 批内离群 + `detect_daily_gaps` 日K 跳空），
  批级检测挂进 gate._process；P2 只标记不拦（accepted 照收、落 quarantine、不计 rejected_count）。
- Q4 接入：movers/fund_flow/board_heat/analyst_consensus/market_breadth/macro/fundamentals
  （5 写库点）共 7 job 11 处 quality_gate，SQL/列顺序/ON CONFLICT 不变，返回基于 accepted。

实跑验收结果（2026-08-22）——**全部通过**：
- ✅ 规则单测：movers 负 volume P0 / 涨幅 5000% P1、fundamentals 负市值 P0，拦截正确。
- ✅ P2 单测：日K 跳空 63.5% → 放行（accepted=3）+ 落 P2 标记 + 不计 rejected_count。
- ✅ 真实管道覆盖：metrics 表新增 macro_indicators(6749 行)/market_breadth(1 行)/daily_prices(103155 行)。
- ✅ 新表脏数据端到端：movers 负 volume、market_breadth 负计数均 P0 拦截落 quarantine。
- ✅ 精确性验证：daily_prices 10 万行仅 1 条 rejected（为此前手动注入的 BAD 测试行），真实源零误拦。

Review 发现的问题与处置：
1. ~~movers_cache.percent_change 单位口径 CN/US 不一致~~ **经实测证伪（2026-08-22）**：库里 US/CN
   的 percent_change 均为小数口径（US max 0.148、CN max 0.30），两条链路口径一致，P2 z-score 无量纲混合。
   子 agent 的「US 存百分数」为误报，待办不成立，无需处理。
2. fund_flow/board_heat 的 snapshot_date 不在 tuple（靠 DB DEFAULT），过闸 dict 补 date.today()——与 DB 默认同日，仅满足规则校验，无害。
3. technical_indicators（本地自算）/文本类/news/board_map/yield_curve 未接入——规则未登记或无数值语义，符合设计边界。

### 阶段三.五 review 明细（Q1-Q3，2026-08-22）

范围决策（2026-08-22 定）：**前置建独立质量层**（app/quality/ 子包），不做轻量校验函数——
数据管道「写一次读千次、错了污染下游」，后置重构成本远高于现在把层建对。

主 agent 建 Q1 骨架（models/rules/normalize/gate/store + 两表 DDL + 存量迁移）；
Q2 由子 agent Zeno 接入 4 个 OHLC job；Q3 主 agent 写 data-api quality 端点。

已完成验证：
- Q1 骨架：`app/quality/`（quality_gate 统一入口 + 声明式 QualityRule + 处置三态 ACCEPT/REPAIR/REJECT + 严重级 P0/P1/P2）；两表 `data_quality_rejects`（quarantine 留痕）+ `data_quality_metrics`（按表按日聚合）；init.sql + main.py 存量 ALTER 迁移。
- Q2 接入：daily_kline/realtime_quotes/indices/macro_assets 4 个 OHLC job 写库前过 quality_gate，SQL/列顺序/ON CONFLICT 不变，返回条数基于 accepted。
- Q3 可观测：质量日志（total/accepted/rejected/repaired/score）+ data-api `GET /api/system/quality`（data-api 只读）。
- 三铁律映射：quality_gate 异常放行（不误停管道）；两表 collector 独占写、data-api 只读；P2 只标记不拦。

实跑验收结果（2026-08-22）——**全部通过**：
- ✅ 骨架单测：4 行（REPAIR 小写 symbol+字符串数值 / P0 high<low / P0 缺 close / 合格）→ 2 accepted、2 rejected、1 repaired、score 0.5，归一正确。
- ✅ 存量迁移：重启 collector 后 `data_quality_rejects`/`data_quality_metrics` 两表就地建好。
- ✅ 真实管道：daily_prices 质量度量落库（38680 行、rejected=0、score=1.0）——正常源下全合格。
- ✅ 端到端闭环：手动注入脏行（BAD high<low）→ quality_gate 拦截（accepted=0）→ 落 data_quality_rejects（含 reject_reason/severity=P0）。
- ✅ data-api `/api/system/quality` 读到 metrics（只读，单一写者成立）。

Review 发现的问题与处置：
1. **volume 归一 float→BIGINT 类型错风险**（Zeno 报）——normalize 把字符串 volume 转 float，asyncpg 对 BIGINT 列报类型错。已修：`_INT_FIELDS` 单独按 int 归一（volume 系列），单测验证 volume 归一为 int。✅ 已修。
2. 全量初始化百万行质量校验增加几秒到十几秒（逐行纯 Python）——每日增量（5 天）无感，全量略慢可接受。不处理。
3. quote_snapshots 的 change_percent ±100% 阈值（P1）对极端美/港股（拆股/仙股暴动）理论可能误拦——规则注明「跨市场最宽」，留观察项。不处理。

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
