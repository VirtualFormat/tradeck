# 量化引擎与策略开发 — 技术方案（v2）

> 范围：回测引擎、策略编辑（含 AI 生成）、选股 screener、因子挖掘。
> 分钟K / tick / 付费数据源等数据层事项在其它会话处理，本文不覆盖。
> 任务拆解与验收见 `plans/TASKS-QUANT-BACKTEST.md`。上游地基见 `docs/DATA-SERVICE.md`。
> **参照实现**：`../tick-stock-panel`（A 股量化工作台，生产级 Polars 策略/回测/挖掘体系），
> 本文大量设计参照它，差异处会显式说明。
>
> **v2 修订（2026-09-10）**：数据底座已就位（A 股近 10 年分钟K 温冷分层 + 同花顺
> 复权因子入 PG，`/api/bars?adjust=qfq|hfq` 在线），新增三项需求：
> ① 单用户 → 多用户的架构预留；② 因子编辑器（DSL 自定义因子）；③ 分钟级回测。
> 阶段 A–E 已按 v1 验收（2026-08-25），v2 追加阶段 G/H/I/J/K，见任务卡。

## 前提与地基（已就位，不重造）

- **数据出口**：data-api 是唯一读出口，`POST /api/bars` 批量日K（200 只/请求、50 万行上限、
  `truncated` 截断标记）+ `X-Service-Token` / `X-Service-Name` 消费方鉴权，全部已验收。
- **日K 复权口径**：TickFlow `klines.batch` 不指定 `adjust`，**默认 `none`（原始价）**——
  引擎内动态复权的标准前提成立，日K 无需重采。
  （tick-stock-panel 同一结论：存原始价 + adj_factor 动态前复权，enriched 层双口径。）
- **三条铁律不变**：quant 进程只过 data-api，绝不直连 DB；数据落本地 Parquet 缓存复用。
- 分钟K 不进本引擎（走冷层 Parquet/COS 管道，其它会话推进）。

## 关键选型：Polars 自研引擎（不选 vectorbt）

参照项目用纯 Polars/NumPy 实现了选股 + 回测 + 监控 + 因子挖掘全链路（backtest/ 约 2 万行
生产代码），证明这条路线的可行性。对 tradeck 的实际收益：

1. **无 numba/llvmlite 重依赖**：aarch64 构建坑消失，依赖只有 polars/numpy/pyarrow/httpx。
2. **列矩阵内存模型**（`MarketDataMatrix`：时间 × 标的二维数组）对 2 万标的全市场扫描
   天然友好，选股/回测/挖掘共享同一份矩阵缓存。
3. **策略与回测同构**：策略产出信号列，回测直接消费信号矩阵，无 vectorbt 的布尔矩阵
   转换层。
4. 参照代码可逐段研读，撮合语义（T+1/印花税/止损）有生产级口径可对齐。

## 架构拓扑

```
data-api (:8080)  ◀── POST /api/bars（X-Service-Token: quant）
      ▲
      │ 批量日K + as-of 基本面 + 除权因子（TickFlow ex_factors）
┌─────┴───────────────────────────────────────────┐
│ apps/quant（独立容器）                             │
│  data/      data-api 客户端 + Parquet 缓存层        │
│  matrix/    市场矩阵（时间×标的列存，共享缓存）       │
│  engine/    复权 + 撮合回测 + 统计                  │
│  strategy/  META 规范 + 加载器 + 评分 + 内置策略     │
│  ai/        AI 生成（安全校验闸 + 提示词）           │
│  screener/  选股执行（全市场扫描 + 排序）            │
│  mining/    因子挖掘（IC/去重/组合搜索/嵌套样本外）   │
│  api.py     轻量 HTTP（strategies/screen/backtest） │
└─────┬───────────────────────────────────────────┘
      ▼
 quant-cache volume（Parquet：行情/因子缓存 + enriched 矩阵 + 报告/候选库）
```

与 tick-stock-panel 的核心差异：**数据接入不同**（它单容器直读本地 enriched Parquet +
TickFlow 直调；tradeck 必须过 data-api 三条铁律），策略/引擎/AI/挖掘的逻辑设计照搬，
数据层换成 `/api/bars` + 本地缓存。另一差异：**A 股单市场 → 三市场**（A 股语义的
涨停/连板/T+1 等按市场参数化）。

## 核心设计

### 0. 多用户架构预留（v2 新增）

系统当前单用户，但以下决策**现在做几乎零成本、以后改是伤筋动骨**，全部前置：

**身份与隔离**：
- 所有请求上下文带 `user_id`（单用户阶段恒为 `"default"`，从 `QUANT_DEFAULT_USER`
  环境变量读，不做鉴权）。HTTP 层从 header `X-User-Id` 取（缺省回落 default），
  禁止在业务函数签名里省略该参数。
- **共享层**：行情/因子矩阵缓存、内置策略、挖掘因子目录——全局只读，多用户天然共享。
- **私有层**：用户策略（`custom_*`）、AI 策略（`ai_*`）、自定义因子（`uf_*`）、
  复合因子（`cf_*`）、回测报告、挖掘候选——全部按 `user_id` 命名空间隔离：
  `data/users/{user_id}/strategies/`、`data/users/{user_id}/factors/`、
  `data/users/{user_id}/candidates/`。加载器按 `builtin（全局）+ user 目录` 合成视图。
- 多用户切换时的改动面被压缩为：鉴权中间件 + `user_id` 来源从常量变 token 解析，
  存储布局与 API 契约零变化。

**执行隔离（worker 池，参照 backtest/worker.py 轻量化）**：
- 回测/挖掘/AI 策略执行三类重计算走 **spawn 子进程任务**：主进程只收发
  progress/result/error 消息，子进程崩溃/超时/OOM 可杀可控，不拖垮 API 进程。
- 单用户阶段池大小 = 1（串行队列，等价于现状的进程内执行 + 隔离保险）；
  多用户时调大池 + 每用户并发上限，配置项 `QUANT_WORKER_POOL_SIZE` /
  `QUANT_MAX_CONCURRENT_PER_USER` 现在就留。
- 与「backend 必须单进程」纪律不冲突：quant 是独立服务，APScheduler 不在此进程；
  worker 是任务级 spawn 子进程而非 API 多 worker。

**明确不做（多用户阶段才启动）**：鉴权/注册/配额计费、行级权限、共享策略市场。
当前只留结构，不留半成品功能。

### 0.5 因子编辑器（v2 新增，参照 factors/dsl.py + store.py）

用户不写代码、用公式表达式定义因子，与策略编辑并列的一等能力。

- **DSL 编译器**（`app/factors/dsl.py`，参照移植）：文本 → tokenizer → 递归下降
  解析 → AST → 语义检查 → Polars Expr，编译失败返回结构化错误码（E001-E016），
  不抛裸异常。算子表白名单：ts_*（mean/std/sum/max/min/delay/delta/rank/zscore/
  corr/cov/quantile/decay_linear）+ 截面（rank/zscore/winsorize）+ 算术函数。
  编译期红线照搬：ts_* 只向后看（负 shift 拒绝）、嵌套窗口两阶段物化、
  截面算子禁嵌时序窗口、AST 深度/窗口/token 数硬上限。
- **自定义因子三类**：`uf_*` 用户 DSL 因子、`cf_*` 复合因子（≤8 成员加权，
  引用 uf/base/virtual）、base/virtual 为系统内置。id 正则强制前缀。
- **生命周期**：draft → active → watch → retired（状态机字段现在就建，
  流转逻辑随挖掘联动逐步启用）。
- **消费贯通（单一事实源铁律）**：因子注册表 `factors/registry.py`（FactorSpec：
  id/label/group/公式/方向/预热窗口/版本）是唯一定义点，选股评分、回测、
  挖掘、web 展示四端全部从注册表取——**禁止各端各自硬编码因子清单**
  （参照的三处清单漂移合并为注册表的教训）。
- **编辑器 UI**：公式输入 + 实时编译诊断（错误码定位）+ 样例数据即时预览
  （因子值曲线/分布）+ 版本管理（公式变更 version+1 进缓存键）。
  落 `data/users/{user_id}/factors/*.json`（多用户命名空间，见上）。
- 与挖掘的边界：编辑器产物是**用户声明的因子**（人工假设驱动）；
  挖掘产物是**机器搜索的组合**（数据驱动）。两者都进注册表、都可入候选库，
  但挖掘候选仍守「显式确认才发布」纪律。

### 1. 数据层（app/data/）

- **client.py**：httpx 封装 data-api。`/api/bars` 自动分片（symbols 超 200 分批、
  `truncated=true` 按时间窗对半切）；as-of 走现有 `/api/analyst/consensus?as_of=` 与
  `/api/fundamentals/metrics?as_of=`；请求头带 `X-Service-Token` + `X-Service-Name: quant`。
- **除权因子（v2 改源）**：A 股已从 TickFlow 付费档 ex_factors **切换到 data-api
  复权出口**（同花顺公司行为事件已在 PG 重建全市场 qfq/hfq 因子，
  `/api/bars?adjust=qfq|hfq` 在线，缺失行显式标注覆盖率）。引擎仍保持
  raw/adjusted 双口径：优先 data-api 出因子序列（`/api/factors` 待加）保持
  引擎零改动；未覆盖市场（US/HK）沿用原降级路径。**因子缺失降级为「无复权」
  并在结果显式标注**（优雅降级铁律），不得静默当已复权。
- **store.py（Parquet 缓存）**：`cache/daily/market=US/symbol=AAPL.parquet`，增量合并
  （按 date 去重，最后写入胜出 = UPSERT 语义）；请求区间 ⊆ 已缓存区间直接读盘，缺段只补缺口。
- **分钟数据（v2 新增，client_minute.py）**：在线走 `POST /api/bars/minute`
  （分片/截断沿用日K模式）；10 年级批量扫按 DATA-CONTRACT 走冷层 Parquet + DuckDB
  直读。缓存进 quant-cache，布局 `minute/market=CN/symbol=X/year=YYYY.parquet`。

### 2. 市场矩阵（app/matrix/，参照 backtest/matrix.py）

- 从 Parquet 缓存构建 `MarketDataMatrix`：全局交易日轴 × universe 标的轴，OHLCV/amount/
  turnover 各为一个二维 numpy 数组，列存对齐（停牌/缺行用 NaN，绝不错位连接）。
- **enriched 层**：矩阵上预计算指标列（MA/EMA/MACD/RSI/KDJ/BOLL/量比/动量/波动率/极值），
  一次算全市场落盘，选股/回测/挖掘共用。同时保留**复权价 + raw 原始价双口径**
  （`close` 前复权用于指标与信号，`raw_close` 用于成交价与市值计算）。
- 矩阵按 universe + 区间缓存，增量延伸（新交易日只算增量行）。

### 3. 回测引擎（app/engine/，参照 backtest/engine.py + strategy.py）

- **复权**（`adjust.py`）：ex_factors 动态前复权，OHLC 同乘、volume 反比，双口径输出。
- **精确涨跌停（v2 升级）**：从「统一 ±10%/±20% 近似」升级为按板块/日期/ST 状态
  精确分档（参照 price_limit_pct：主板 ±10%、创业/科创 ±20%、ST ±5%、北交所 ±30%）；
  ST 判定用股票名称数据（数据层已备）。
- **撮合**（`MatcherConfig` 对齐参照口径）：
  - 成交口径：`close_t` / `open_t+1` 可配（默认 open_t+1，信号当日收盘产生次日成交，
    防未来函数铁规矩）。
  - **分钟精确成交（v2 新增，fill_mode）**：`minute_fill`（信号触发日用分钟K 优化：
    有参考线→穿越价，无参考线→VWAP，数据缺失降级日K口径）+ `minute_trigger`
    （卖出信号盘中触发：MA 跌破反推触发价线 → 分钟收盘确认下穿 → 下一分钟开盘
    成交，信号白名单制起步仅 MA 类卖出信号）。参照 engine._resolve_minute_fill /
    minute_trigger.py。
  - 成本模型（分市场默认值，可覆盖）：
    | 市场 | 佣金 | 印花税 | 滑点 |
    |---|---|---|---|
    | CN | 万 2.5（最低 5 元） | 卖出千 1 | 千 1 |
    | US | 0（零佣假设） | — | 千 0.5 |
    | HK | 万 3 | 千 1（双向） | 千 1 |
  - 仓位规则：max_positions / max_exposure / 等权或 score 加权 / 初始资金。
  - 风控：止损/止盈/max_hold_days 已实现；**移动止损/移动止盈 v2 补**
    （trailing_stop_pct / trailing_take_profit_activate+drawdown，对齐参照
    MatcherConfig，退出优先级：挂单 > 风控 > 信号 > 到期 > end）。
  - 市场约束开关：CN T+1、CN ±10%/±20% 涨跌停不可成交、整手 100 股；默认全开。
- **统计**：年化/累计收益、最大回撤、夏普、卡玛、胜率、盈亏比、换手率；
  净值曲线含基准对比列（指数从 data-api `/api/indices` 拉）。

### 4. 策略体系（app/strategy/，核心照搬参照）

**策略 = 单 Python 文件 + 顶层 `META` 字面量字典**：

```python
import polars as pl

META = {
    "id": "dual_ma", "name": "双均线", "description": "...", "tags": ["趋势"],
    "basic_filter": {...},          # 引擎统一处理：价格/市值/成交额/ST/新股/板块
    "params": [                     # 用户可调参数（UI 自动生成表单的依据）
        {"id": "fast", "label": "快线周期", "type": "int", "default": 5, "min": 2, "max": 60},
    ],
    "scoring": {"momentum_20d": 0.6, "vol_ratio_5d": 0.4},   # 权重和 = 1.0
    "order_by": "score", "descending": True, "limit": 100,
}
ENTRY_SIGNALS = ["ma_cross_up"]     # 回测/监控用信号列
EXIT_SIGNALS = ["ma_cross_down"]
STOP_LOSS = -0.05

def filter(df: pl.DataFrame, params: dict) -> pl.Expr: ...        # 模式 A：单日
# 或 def filter_history(df, params) -> pl.DataFrame（模式 B：窗口，配 LOOKBACK_DAYS）
```

- **三层目录权限（v2 挂多用户命名空间，见 §0）**：
  | 目录 | 谁写入 | 前缀 |
  |---|---|---|
  | `app/strategy/builtin/` | 仅项目维护（随镜像） | — |
  | `data/users/{uid}/strategies/custom/` | 用户手写 | `custom_` |
  | `data/users/{uid}/strategies/ai/` | AI 生成 | `ai_` |
- **加载器**（参照 strategy/engine.py）：importlib 热加载、META 归一化（params 多种
  写法容错为 list[dict]，格式坏降级不崩）、两阶段过滤（basic_filter 先行收窄再跑策略）、
  通用评分排序（scoring 权重 → score 列）。
- **叠加策略（composite，v2 补实现）**：上限 8 个子策略防 OOM。合并口径照搬参照
  composite.py（选股/回测共用纯函数）：entry 支持 union(OR)/intersect(≥min_confirm)，
  score 按子策略内排名归一 [0,1] 加权融合；**exit 必须来源投影**（子策略的退出信号
  仅在它自己 entry 后的持仓窗口内生效，撮合层零改动）——直接 OR(exit) 会产生
  "B 平掉 A 仓位"的幽灵平仓，这是参照用生产事故换来的纪律。
- **内置策略**：首批精简移植参照的 18 个（趋势/量价/反转三类代表），A 股专属语义
  （涨停/连板）标注 CN-only。
- **策略红线**：策略模块禁网络/DB/文件系统写入（ast 闸强制），只能读注入的矩阵数据。

### 5. AI 策略生成（app/ai/，照搬参照的双层设计）

**轻量级：自然语言 → JSON 条件**（参照 custom_signals_ai.py，不写代码）：
- system 提示词注入 enriched 字段白名单（分类中文标签）+ 操作符 + 日期偏移规则；
- LLM 输出固定结构 `{"name", "conditions": [{left, op, right, leftDays, rightDays}]}`；
- 复用 custom_signals 的校验闸（字段白名单/操作符/偏移范围）后编译成 Polars 表达式。
- 适合快速验证筛选思路，AI 不接触代码执行面。

**完整级：自然语言 → 策略文件**（参照 ai_generator.py）：
- compact 版策略开发指南作 system 提示词（降长请求超时概率）；
- LLM 生成完整 .py → **ast 静态安全校验**（白名单 import 仅 polars/datetime/numpy、
  禁 os/sys/subprocess、禁 dunder 属性、禁危险 call）→ META 语义校验 →
  结构不合法自动 repair 一轮 → 落 `data/strategies/ai/` 热加载；
- 前端流式接收生成过程。

配置：`AI_PROVIDER=openai_compat` + `AI_BASE_URL` + `AI_API_KEY` + `AI_MODEL` 环境变量，
**留空即关闭 AI 功能**（优雅降级）。密钥只走环境变量，登记 `.env.example`，不入库不入仓。

### 6. 选股 screener（app/screener/）

- 执行器：加载策略 → basic_filter 收窄 → 策略过滤 → scoring 排序 → 返回 Top N
  （全 A 股扫描是参照的主打场景，tradeck 三市场按 market 分区扫）。
- 自定义信号（方式一）：UI 上 `字段+操作符+阈值` 组合，编译 Polars 表达式热加载，
  无需写代码（参照 custom_signals.py）。
- 结果落 `strategy_signals` 语义：供每日 cron 信号扫描与 web 展示（见阶段 E）。

### 7. 因子挖掘（app/mining/，参照 mining.py + mining_runtime.py 精简）

**功能边界（V1 对齐参照口径）**：只研究本地日频因子与已发布策略；不生成任意公式、
不接受 AI 自由代码、不用分钟数据。

**v2 防泄漏加固（必须补，金融正确性缺口）**：
- **purge/embargo 隔离带**：训练/测试折之间留 purge_bars=30 + embargo_bars=5，
  forward return 窗口期跨边界泄漏是当前实现的系统性乐观偏差。
- **真嵌套验证**：外层评估 + 内层调参双层（参照 generate_nested_folds），
  当前单层折调参结果直接上外层是另一处乐观偏差。
- **统计检验**：Newey-West HAC t 值（IC 序列自相关校正）+ BH-FDR 多重检验 q 值
  + DSR 通缩夏普——零依赖 numpy 手写（参照 stats_v2.py，黄金参考向量锁数值）。
  挖 48 个因子不做 FDR 校正，假发现率不可控。

闭环流程：
1. 训练区间重算因子方向与统计（Rank IC，按全局交易日轴精确连接 forward return）。
2. 截面 IC 相关性去重。
3. beam 搜索 ≤4 因子受控排名组合（beam_width 截断，代理预算可控）。
4. **嵌套样本外验证**比较组合；已有策略作对照轨独立评估，不参与因子竞争。
5. 运行/事件/结果持久化（Parquet/SQLite），刷新可重连。
6. 候选入**研究候选库**——**只有用户显式确认且过晋级门槛才发布为独立策略，
   永不自动上线**（这是参照最重要的纪律，照搬）。

因子目录（首版）：价量技术类（动量/均线偏离/趋势/波动率/量价/超买超卖）+
收益形态（彩票效应/偏度/上涨天数）+ 流动性（Amihud 非流动性/换手异动）。
财务因子（pb/roe/毛利率/营收利润同比）用 data-api as-of 接口，**严格点时口径：
因子值只在公告次一交易日起生效，公告前为空值剔除，绝不填 0**；
`fundamental_metrics` 的 as-of 是 updated_at 近似（`as_of_exact: false`），
结果中必须标注此局限（精确 point-in-time 待数据服务阶段四快照化）。

时点红线：价格序列无未来函数；**T 日只能用 T-1 已知的标签与因子**；
信号成交统一次日开盘；每个因子记录其 as-of 精确性等级。

### 8. 服务与部署

- quant 容器加轻量 HTTP（FastAPI，profile `quant` 默认不启动）：
  `GET /strategies`（含 params schema）、`POST /screen`、`POST /backtest`、
  `POST /ai/generate`（流式）、`GET /mining/runs` 等；
  v2 新增 `GET/POST/PUT/DELETE /factors`（因子编辑器 CRUD + 编译诊断 +
  预览）与 `POST /backtest`（走 worker 池，见 §0）。
- web 端消费经 Next 代理路由（Client Component 不直连 backend 的既有约定），
  UI 遵守 AGENTS.md「UI 强制规则」（shadcn、空态统一、phosphor 图标）。
- 环境变量：`BACKEND_API_URL`、`SERVICE_TOKEN`、`AI_*`、`TICKFLOW_API_KEY`；
  v2 新增 `QUANT_DEFAULT_USER`（单用户阶段恒 default）、
  `QUANT_WORKER_POOL_SIZE`（默认 1）、`QUANT_MAX_CONCURRENT_PER_USER`（默认 1）。
- 资源纪律：API 进程单进程；重计算走 spawn 子进程池（§0），
  挖掘/参数扫受 mem limit 约束，按标的池分批。

## 与数据层的边界（明确不做）

- ~~分钟K/tick 回测~~（v2 已激活：冷层管道已落地，分钟成交价修正/盘中触发/
  分钟频回放按阶段 H 推进，读冷层 Parquet + 温层 `/api/bars/minute`）。
- 实盘/模拟盘交易接口：只出研究结果与信号，不接券商。
- ~~ex_factors 落 PG~~（v2 已落地：A 股同花顺因子已在 PG，quant 经 data-api 读）。
- 因子挖掘不生成任意公式、不用分钟数据（V1 边界，对齐参照；
  **用户手工声明公式走因子编辑器 §0.5，与挖掘边界不冲突**）。
- regime 市场环境过滤（5 档状态作回测入场过滤，参照 regime_builder.py）：
  依赖全市场聚合数据，列为中期可选，不进当前阶段。
- 鉴权/注册/配额（多用户正式功能）：只留结构（§0），不留半成品。

## 风险

1. **体量**：参照 backtest/ 约 2 万行，精简移植是主要工作量；按阶段验收逐段消化，
   不一次搬完。
2. **内存**：2 万标的 × 10 年矩阵约 1.6GB float64（enriched 列更宽）；扫描/挖掘按
   universe 分批，CLI/参数控制批大小。
3. **除权因子缺口**：免费档无 ex_factors；缺失标的降级无复权 + 结果点名，不阻塞。
4. **AI 生成安全**：ast 闸是第一道（白名单 import），容器隔离是第二道（无 DB 凭据、
   无宿主网络外权限）；AI 目录永不进 builtin。
   v2 加第三道：重计算走 spawn 子进程池，AI 代码的资源型 DoS（死循环/爆内存）
   被进程边界兜住，可杀可控。
5. **基本面 as-of 近似**：挖掘财务因子时结果标注局限，见「因子挖掘」节。
6. **多用户预留的纪律风险**：user_id 命名空间与 worker 池是结构预留，
   真正的隔离强度（鉴权/配额/行级权限）多用户阶段才验收——在此之前
   不得对外宣称支持多用户。
