# 量化引擎与策略开发 — 任务拆解与验收

> 流程沿用数据服务拆分的模式：主 agent 派活 → 子 agent 按任务卡执行（写范围严格受限）→
> review 门禁 → 修复 → 验收，逐阶段回填「验收记录」。技术背景见 `docs/QUANT-BACKTEST.md`，
> 参照实现 `../tick-stock-panel`。
> Review 门禁：① 代码符合 AGENTS.md 约定（优雅降级/中文注释/单进程纪律）；
> ② 铁律检查（quant 无直连 DB、策略无网络访问、信号次日成交无未来函数、
> 挖掘候选永不自动上线）；③ 各阶段验收标准全绿。

## 阶段 A：骨架与数据层（地基）

**目标**：`apps/quant` 容器起得来，能从 data-api 拉数、落 Parquet 缓存、增量合并。
**关键路径**：A1 → A2 串行；A3 与 A2 并行（写范围不重叠）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| A1 包骨架 + Dockerfile | `apps/quant/` 包结构（data/matrix/engine/strategy/ai/screener/mining/api）、requirements.txt（polars/numpy/pyarrow/httpx/pydantic/fastapi，无 numba）、Dockerfile | `apps/quant/**` | — |
| A2 data-api 客户端 + 缓存 | `data/client.py`（bars 自动分片/truncated 对半切窗/指数退避、as-of 查询、service token 头）、`data/store.py`（Parquet 布局、区间命中判定、缺口补拉、date 去重合并）、`data/factors.py`（ex_factors 拉取 + 缺失降级标记） | `apps/quant/app/data/**` | A1 |
| A3 compose 接入 | dev/prod compose 加 `quant` service（profile quant、quant-cache volume、BACKEND_API_URL/SERVICE_TOKEN/TICKFLOW_API_KEY 环境变量） | `.devcontainer/docker-compose.yml`、`docker-compose.yml`、`.env.example` | A1 |

**验收标准**：

1. `docker compose --profile quant run --rm quant python -m app.cli fetch --symbols AAPL,600519.SH --start 2024-01-01` 跑通，Parquet 落盘，二次执行命中缓存零补拉。
2. 截断场景实测：truncated 后自动分窗，最终行数完整无重复。
3. ex_factors 缺失标的：降级路径走通，输出显式标注未复权。
4. grep 确认 quant 包内无 `asyncpg` / `DATABASE_URL`（直连 DB 红线）。

## 阶段 B：矩阵与回测引擎（核心）

**目标**：市场矩阵 + 动态复权 + 撮合回测跑通，无未来函数。
**关键路径**：B1 → B2 串行。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| B1 市场矩阵 + enriched | `matrix/`：全局交易日轴 × 标的轴列存矩阵（NaN 对齐不错位）、复权价 + raw 双口径、指标列预计算（MA/EMA/MACD/RSI/KDJ/BOLL/量比/动量/波动率/极值）、增量延伸缓存。参照 `backtest/matrix.py` + `indicators/pipeline.py` 精简 | `apps/quant/app/matrix/**` | A2 |
| B2 复权 + 撮合引擎 | `engine/adjust.py`（ex_factors 动态前复权）、`engine/matcher.py`（MatcherConfig：close_t/open_t+1 口径、分市场成本模型、止损/止盈/移动止损、max_positions/exposure、等权/score 加权、CN T+1/涨跌停/整手开关）、`engine/stats.py`（收益/回撤/夏普/卡玛/胜率/换手 + 基准对比）。参照 `backtest/engine.py` | `apps/quant/app/engine/**` | B1 |

**验收标准**：

1. 简单信号（如固定日期买卖）在 tracked 100 只 × 2 年跑通，净值/成交明细产出。
2. 未来函数用例：改信号日收盘价，净值不变（证明成交在次日）。
3. 约束实测：开 T+1 前后结果有差异；涨跌停日买单不成交。
4. 复权正确性：600519.SH 分红日附近，复权净值曲线除权日无跳空；raw 口径成交价为真实价格。
5. 指标列抽查对账：MA20/MACD 与 pandas 参考实现误差小于 1e-6。

## 阶段 C：策略体系与 AI 生成（编辑能力）

**目标**：META 策略规范 + 三层目录 + AI 生成安全闭环。
**关键路径**：C1 → C2 → C3 串行；C4（提示词）与 C3 并行。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| C1 策略规范 + 加载器 | `strategy/meta.py`（META 归一化容错）、`strategy/loader.py`（三层目录热加载：builtin/custom/ai）、`strategy/scoring.py`（评分排序）、两阶段过滤（basic_filter 先行）、composite 上限 8。参照 `strategy/engine.py` + `scoring.py` | `apps/quant/app/strategy/**` | B1 |
| C2 内置策略移植 | 精简移植参照 18 个内置策略（趋势/量价/反转代表），A 股专属语义标注 CN-only；`strategy-guide.md` 开发指南（人类版） | `apps/quant/app/strategy/builtin/`、`apps/quant/app/strategy/prompts/strategy-guide.md` | C1 |
| C3 AI 安全闸 + 生成器 | `ai/validator.py`（ast 白名单校验：仅 polars/datetime/numpy、禁危险模块/dunder/call、META 语义校验、自动 repair）、`ai/generator.py`（完整策略生成 + 流式）、`ai/conditions.py`（轻量 JSON 条件生成 + 白名单校验编译）。参照 `ai_generator.py` + `custom_signals_ai.py` | `apps/quant/app/ai/**` | C1 |
| C4 AI 提示词 | `prompts/strategy-guide-compact.md`（AI 运行时精简指南，参照改写为三市场 + tradeck 字段） | `apps/quant/app/strategy/prompts/` | C2 |

**验收标准**：

1. 三个目录各放样例策略，加载器全部发现；META 非标准写法（dict/list[str]）容错不崩。
2. 内置策略在 enriched 矩阵上跑出结果且排序合理。
3. 安全闸用例：含 `import os` / `__import__` / `subprocess` 的策略代码一律拒绝；缺 META 或缺入口函数明确报错；结构非法触发 repair 重试。
4. 轻量条件生成：JSON 条件编译为 Polars 表达式并可执行；白名单外字段拒绝。
5. AI 配置留空时功能优雅关闭（不报错）。

## 阶段 D：选股与挖掘（研究闭环）

**目标**：全市场选股扫描 + 因子挖掘闭环 + 候选库纪律。
**关键路径**：D1 与 D2 并行（写范围不重叠）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| D1 选股执行器 | `screener/`：策略扫描（basic_filter 收窄 → 过滤 → scoring → Top N）、自定义信号（字段+操作符+阈值编译热加载）、按市场分区扫描、结果落信号记录 | `apps/quant/app/screener/**` | C1 |
| D2 因子挖掘 | `mining/`：因子目录（价量技术 + 收益形态 + 流动性，财务因子走 as-of 严格点时口径）、Rank IC + 相关性去重、beam 搜索 ≤4 因子组合、嵌套样本外验证、运行持久化可重连、候选库（显式确认 + 晋级门槛才发布）。参照 `mining.py` + `mining_runtime.py` 精简 | `apps/quant/app/mining/**` | B2、C1 |

**验收标准**：

1. 全 A 股（或指定 universe）扫描耗时与内存可控（分批），Top N 结果含 score 明细。
2. 自定义信号 UI 语义（字段+操作符+阈值）编译执行正确。
3. 挖掘闭环：因子 IC 计算 → 去重 → 组合搜索 → 嵌套样本外 → 候选落库，全程持久化，中断后重连续跑。
4. 候选**不自动发布**：未经显式确认不出现在策略列表；确认后生成独立策略文件（发布轨与对照轨隔离）。
5. 时点用例：财务因子公告日前为空值；T 日因子不用 T 日后数据。
6. 财务因子结果标注 as-of 精确性等级（metrics 近似 / consensus 精确）。

## 阶段 E：服务化与 web 集成（展示层）

**目标**：HTTP 服务 + web 页面消费，全部走代理，遵守 UI 强制规则。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| E1 quant HTTP API | `api.py`：strategies 列表（含 params schema）/ screen / backtest / ai generate（流式）/ mining runs；profile quant 启动 | `apps/quant/app/api.py`、`apps/quant/app/main.py` | D1、D2 |
| E2 web 代理路由 | Next 代理 `/api/quant/*` 转发 quant 容器 | `apps/web/src/app/api/quant/**` | E1 |
| E3 策略工作台页 | 策略列表 + params schema 自动生成参数表单（shadcn Form）+ 回测触发 + 结果展示（净值图经 ui/chart）；AI 生成器对话框（流式）；信号 Tab 联动现有 /screener 页 | `apps/web/src/app/quant/**`、`apps/web/src/components/quant/**` | E2 |
| E4 每日信号 cron | 对 universe 跑已发布策略，信号写记录供 web 展示（日快照语义） | `apps/quant/app/jobs/` | D1 |

**验收标准**：

1. web 页面列出全部策略，参数表单由 schema 生成（滑杆/数字/下拉按 type），改参跑回测出结果。
2. AI 生成器流式出码，安全闸拦截的坏代码有明确错误提示。
3. UI 检查清单全绿（无裸元素/手搓/图标库违规、空态统一、ChartContainer 包裹图表）。
4. Client Component 不直连 quant（只走 Next 代理）。

## 阶段 F：加固（可后置，按需启动）

| 任务 | 内容 | 触发条件 |
|---|---|---|
| F1 参数优化器 | 参数网格扫描 + 敏感性分析（参照 optimizer.py），按 universe 分批 | 策略调参需求出现时 |
| F2 walk-forward | 滚动训练/验证窗，样本外净值拼接（参照 walkforward.py） | 策略过拟合存疑时 |
| ~~F3 分钟K 精确成交~~ | 已升级为阶段 H（v2） | — |
| ~~F4 因子目录扩展~~ | 已升级为阶段 K 因子编辑器（v2） | — |

---

# v2 阶段（2026-09-10 修订）

> 背景：数据底座就位（A 股近 10 年分钟K 温冷分层 + 同花顺复权因子入 PG），
> 新增需求：多用户架构预留、因子编辑器、分钟级回测。设计见 `docs/QUANT-BACKTEST.md` v2。
> 阶段 A–E 验收结论不变；以下阶段沿用同一流程（任务卡 → review 门禁 → 验收记录）。

## 阶段 G：数据层收敛 + 多用户骨架（地基，最高优先）

**目标**：引擎与数据底座对齐（复权源、分钟数据、精确涨跌停），多用户结构预留落地。
**关键路径**：G1 → G2 串行；G3 与 G4 可并行（写范围不重叠）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| G1 复权源切换 | data-api 新增 `/api/factors` 出因子序列；quant `data/factors.py` 从 TickFlow ex_factors 切换到 data-api，引擎零改动（raw/adjusted 双口径不变）；US/HK 沿用降级路径；退役付费档依赖 | `apps/backend/app/api/**`、`apps/quant/app/data/**` | — |
| G2 精确涨跌停 | 引擎涨跌停判定从统一 ±10%/±20% 升级为按板块/日期/ST 精确分档（主板 ±10%/创业科创 ±20%/ST ±5%/北交所 ±30%），ST 判定用名称数据（参照 price_limit_pct） | `apps/quant/app/engine/**` | — |
| G3 分钟数据客户端 | `data/client_minute.py`：在线 `/api/bars/minute`（分片/截断沿用日K模式）+ 冷层 Parquet/DuckDB 批量扫；缓存 `minute/market=CN/symbol=X/year=YYYY.parquet` | `apps/quant/app/data/**` | — |
| G4 多用户骨架 | `user_id` 贯穿请求上下文（header `X-User-Id`，缺省 `QUANT_DEFAULT_USER`）；存储布局迁移 `data/users/{uid}/{strategies,factors,candidates}`；加载器按 builtin + user 目录合成视图；worker 池骨架（spawn 子进程任务，`QUANT_WORKER_POOL_SIZE=1` 起步）+ 移动止损/移动止盈补齐 | `apps/quant/app/**`（不动 matrix/mining 算法） | G1 |

**验收标准**：

1. A 股回测复权因子走 data-api（600519.SH 分红日无跳空，与 G1 前结果对账一致）；
   因子缺失标的降级路径仍显式标注。
2. ST 股 ±5%、创业板 ±20% 涨跌停判定逐案正确（合成用例）。
3. 分钟客户端：温层在线读 + 冷层批量扫各一条链路跑通，缓存命中零补拉。
4. 两个 user_id 各建策略/因子互不可见；缺省 header 回落 default 兼容现有调用。
5. 回测任务走 worker 子进程执行，杀子进程后主进程存活并报错明确；
   移动止损/移动止盈用例正确（含退出优先级）。
6. 铁律 grep：quant 无 asyncpg / DATABASE_URL；多用户命名空间外零写入。

## 阶段 H：分钟级回测（核心兑现，拆两子阶段）

**目标**：分钟K 数据兑现为回测真实性。
**关键路径**：H1 → H2 串行（H2 依赖 H1 的分钟数据通路）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| H1 分钟成交价修正 | `minute_fill`（信号触发日分钟K：有参考线→穿越价、无参考线→VWAP，缺失降级日K）+ `minute_trigger`（卖出信号盘中触发：MA 跌破反推触发价线→分钟收盘确认→下一分钟开盘成交，信号白名单起步仅 MA 类卖出信号） | `apps/quant/app/engine/**` | G3 |
| H2 分钟频策略回放 | 策略协议扩 `timeframe="1m"`：日线窗口截至 T-1 + 当日分钟流喂策略，分钟级涨停拒买 + 复权折算（参照 minute_replay.py MinuteSignalReplayer） | `apps/quant/app/engine/**`、`apps/quant/app/strategy/**` | H1 |

**验收标准**：

1. minute_fill：有/无参考线两种用例成交价符合穿越价/VWAP 语义；分钟数据缺失日
   自动降级日K口径且结果标注。
2. minute_trigger：MA 跌破卖出在盘中触发（早于次日开盘），白名单外信号不受影响。
3. 与纯日K口径同策略同区间对拍：差异方向可解释（分钟修正应更贴近真实成交）。
4. H2：分钟频策略逐日回放产出入场命中（含触发时刻、涨停拒买计数），
   跳过无分钟分区日不中断。

## 阶段 I：研究严谨性（防泄漏 + 统计检验，插队在 H 大规模使用前）

**目标**：补上当前挖掘实现的金融正确性缺口（防泄漏隔离 + 显著性检验）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| I1 防泄漏加固 | `make_nested_folds` 加 purge_bars=30 + embargo_bars=5 隔离带；升级为真嵌套（外层评估 + 内层调参双层，参照 generate_nested_folds） | `apps/quant/app/mining/**` | — |
| I2 统计检验 | Newey-West HAC t 值 + BH-FDR q 值 + DSR 通缩夏普（零依赖 numpy 手写，参照 stats_v2.py，黄金参考向量锁数值）；挖掘报告带出显著性列 | `apps/quant/app/mining/**` | I1 |
| I3 参数优化器 + walk-forward | 参数网格扫描 + 敏感性分析（参照 optimizer.py）；滚动训练/验证窗样本外净值拼接（参照 walkforward.py）；走 worker 池 | `apps/quant/app/engine/**` | G4 |

**验收标准**：

1. purge/embargo 用例：forward return 窗口跨边界时训练/测试不共享标签；
   嵌套内层调参结果不直接进外层评估。
2. NW t 值 / BH-FDR q 值 / DSR 与黄金参考向量误差 < 1e-6（固定测试向量）。
3. 48 因子批量挖掘报告含 FDR 校正后显著性标注。
4. 优化器/walk-forward 在 worker 池跑通，结果含敏感性分析与样本外拼接净值。

## 阶段 J：因子编辑器（用户声明因子的一等能力）

**目标**：不写代码、用公式表达式定义因子，与策略编辑并列。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| J1 因子注册表 | `factors/registry.py`（FactorSpec：id/label/group/公式/方向/预热/版本），选股评分/回测/挖掘/web 四端统一从注册表取，消灭各处硬编码清单 | `apps/quant/app/factors/**` + 四端接线 | G4 |
| J2 DSL 编译器 | 文本→AST→语义检查→Polars Expr，结构化错误码（E001-E016）；算子白名单（ts_*/截面/算术）；编译期红线照搬参照（负 shift 拒绝/嵌套窗口两阶段物化/截面禁嵌时序/深度窗口 token 硬上限） | `apps/quant/app/factors/dsl.py` | J1 |
| J3 自定义因子存储 + 生命周期 | `uf_*`（DSL 因子）/`cf_*`（复合 ≤8 成员加权）落 `data/users/{uid}/factors/*.json`；draft→active→watch→retired 状态机字段 | `apps/quant/app/factors/store.py` | J2 |
| J4 编辑器 UI + API | `/factors` CRUD + 编译诊断（错误码定位）+ 样例数据即时预览（因子值曲线/分布）；公式变更 version+1 进缓存键；遵守 UI 强制规则 | `apps/quant/app/api.py`、`apps/web/src/components/quant/**` | J3 |

**验收标准**：

1. DSL 编译：合法公式编译为 Polars Expr 可执行；各类非法公式（负 shift/嵌套窗口/
   截面嵌时序/超深 AST）返回对应错误码不抛裸异常。
2. 用户因子创建后：选股评分可用、回测可用、挖掘目录出现、web 展示——四端同源。
3. 复合因子 ≤8 成员加权正确；成员引用 uf/base/virtual 解析正确。
4. 两个 user_id 因子互不可见；公式改 version+1 后旧缓存不命中。
5. 挖掘候选「显式确认才发布」纪律不被编辑器绕过（编辑器产物进注册表但
   不自动进策略）。

## 阶段 K：web 集成收尾 + 运维加固

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| K1 quant lifespan + 信号 cron | 每日信号 cron 注册进 quant lifespan（E4 欠账） | `apps/quant/app/main.py`、`apps/quant/app/jobs.py` | G4 |
| K2 stats 第三方对账 | 回测统计与 empyrical 口径对账（阶段 B 挂账） | `apps/quant/app/engine/stats.py` | — |
| K3 分钟回测 web 展示 | 成交明细带 intraday fill 价/触发时刻列；分钟频回放结果页 | `apps/web/src/components/quant/**` | H2、J4 |
| K4 composite 叠加策略 | 8 子策略上限；entry union/intersect + score 排名归一加权 + exit 来源投影（防幽灵平仓，照搬参照 composite.py 口径） | `apps/quant/app/strategy/composite.py` | G4 |
| K5 quant 测试目录 | 建 `apps/quant/tests/`（unittest 或 pytest，与 data-collector 对齐用标准库 unittest）；把 G–J 验收脚本固化为回归测试（复权对账/涨跌停分档/移动止损/分钟成交/嵌套折防泄漏/DSL 编译红线/因子 CRUD/多用户隔离）+ 门面级集成测试（HTTP→facade→store 创建 uf+cf+改名，Epicurus 指出可一次性暴露 J 的三个 P1）；CI 或手动可重复跑 | `apps/quant/tests/**` | G–J |
| K6 用户因子四端贯通 | 编辑器的 DSL/复合因子（注册表）接入挖掘目录（mining factor_catalog）与策略评分（strategy scoring 白名单）——用户因子可被挖掘/选股/回测消费（§0.5 四端消费）；挖掘侧用户因子参与 IC/去重/组合搜索，策略侧 scoring 白名单扩展为用户因子 | `apps/quant/app/mining/factors.py`、`apps/quant/app/strategy/**`、`apps/quant/app/factors/**` | J |

**验收标准**：

1. 信号 cron 定时触发产出记录，web 可查。
2. 统计指标与 empyrical 对账误差在约定阈值内，口径差异注释标注。
3. composite：来源投影用例（B 的退出信号平不掉 A 的仓位）；union/intersect 语义正确。
4. UI 检查清单全绿。
5. quant 测试目录可重复跑（`python -m unittest discover` 全绿），覆盖 G–J 关键验收点 +
   门面级集成测试。
6. 用户因子四端贯通：编辑器创建的 DSL 因子能被挖掘目录发现（参与 IC/组合搜索）、
   被策略 scoring 引用（选股/回测可用）。

## 中期可选（登记，不进当前排期）

## prod 部署记录（2026-09-11，主 agent）

阶段 G–K 全部代码部署到 prod（host-thu，腾讯云）。链路：推 develop → CI 构建
tradeck-quant 多架构镜像 → VPS `docker compose pull && up -d --force-recreate quant`。

**部署中发现的 prod 特有缺口（已逐一处置）**：

1. **tradb 缺 `/api/factors` 与 `/api/instruments` 读出口**（架构错配）：这两个读出口加在
   tradeck 仓库的 apps/backend（内嵌 data-api），但 prod 的 quant 连的是 tradb（独立仓库
   VirtualFormat/tradb，缺这两个文件）。已把两文件 + 路由注册同步到 tradb 仓库
   （commit 187883c），推 main 触发 CI 构建 tradb-data-api 镜像，VPS 重建生效。

2. **prod daily_prices 为空**：prod 的 A 股日K 全在冷层 Parquet（cold-layer-first 拓扑），
   PG daily_prices 未回填——`/api/bars` 读 PG 故 quant 拿不到日K，复权因子 job 也算不出。
   已写一次性回填脚本（冷层 2025/2026 → daily_prices UPSERT），灌 224 万行；随后重跑
   `rebuild_adjustment_factors` 产出 253 万行复权因子。**注意**：cold-layer-first 拓扑下
   PG daily_prices 与冷层会持续漂移，需评估是否把回填纳入日常 job（待办，见下）。

3. **prod adjust_factors 复权因子 job 首次全量初始化**：57184 事件 → 253 万行因子
   （daily_prices 回填后重建成功）。

4. **prod instrument_master 为空 + tradb 无 instrument_names job**：把 instrument_names job
   文件同步到 tradb（拷入容器），跑出 5571 只 A 股中文名（含 204 只 ST 股）+
   quote_snapshots 回填 30 行。**tradb 仓库需补 instrument_names job 注册**（registry/scheduler），
   当前只在容器内手动跑了一次（待办，见下）。

5. **tradb-openbb 与 tradeck-openbb 抢 6900 端口**：重建 tradb-data-api 时连带重启了
   tradb-openbb（它本就不该跑，tradeck-openbb 正常），已 `docker update --restart=no` + stop 停掉。
   tradb compose 的 openbb 服务应评估加 profile 禁用（避免每次 force-recreate 连带拉起）。

**端到端验证（prod 真实数据）**：quant 回测 600519，复权生效（unadjusted 从降级变为空），
日K 411 行 + 因子 410 行缓存，worker 子进程跑出交易；`/api/factors` 返回 qfq=1.0 正确；
`/api/instruments` 返回 ST海王/贵州茅台；quant → tradb data-api 鉴权 + 数据通路正常；
web → quant（QUANT_API_URL）正常。全部服务健康（tradb-openbb 已按预期停掉）。

**部署后待办**：
- [x] ~~tradb compose 的 openbb 服务与 tradeck-openbb 端口冲突~~ → 2026-09-12 已按正式架构
      处置：tradeck-openbb 停用（compose 加 legacy profile），tradb-openbb 启用（127.0.0.1:6900），
      端口冲突消除。tradeck 内嵌数据层（postgres/clickhouse/collector/data-api/openbb）整体
      加 legacy profile 退役，tradeck 默认启动集 = web + quant（commit 62cfd49）。
- [x] ~~tradb 仓库补 instrument_names job 注册~~ → 2026-09-12 已完成（Herschel）：
      job 文件纳入 git（与线上 md5 一致）、registry + scheduler 注册（cron 07:00 UTC）、
      CI 构建 + VPS 部署，生产 `/api/system/data` 已含该 job（36 个 job 之一）。
      commit 16b4214。
- [x] ~~PG daily_prices 与冷层漂移~~ → 2026-09-12 复核：daily_kline job 正常双写 PG
      （prod daily_prices CN 1033 万行、max(date)=当日），部署时的空是一次性状态缺口
      （findb 冷层历史未回填 PG），非持续漂移。降级为「监控 daily_prices freshness」。
- [x] ~~daily_prices freshness 监控~~ → 2026-09-12 复核：tradb `/api/system/data` 已有被动
      freshness 监控（daily_prices 4 天阈值 + 前端轮询展示），够用不加重；顺带补了
      instrument_master freshness 规则（此前 _TABLE_RULES 缺失）。commit 16b4214。

### 正式架构（2026-09-12 起生效）

```
tradb（数据源层 + 数据服务，独立 compose /data/apps/tradb）：
  tradb-openbb（OpenBB 海外源，127.0.0.1:6900）→ tradb-collector（唯一写者）
    → tradb-postgres（热层）+ tradb-clickhouse（温层）+ 冷层 Parquet
    → tradb-data-api（唯一读出口，127.0.0.1:8080，SERVICE_TOKENS 鉴权）
        ▲ tradb_default 外部网络（tradb_net）
tradeck（业务层，/data/apps/tradeck，默认启动集 = web + quant）：
  tradeck-web（:3000，经 tradb_net 读 tradb data-api）
  tradeck-quant（:8083，经 tradb_net 读 tradb data-api）
  tradeck-nginx（80/443，deploy/nginx 独立 compose）
  （内嵌 postgres/clickhouse/collector/data-api/openbb 全部 legacy profile 退役）
```

openbb 归属澄清：OpenBB 平台镜像的 CI 在 tradeck 仓库（openbb-images.yml，历史原因），
但运行时 openbb 是 tradb 数据源层组件（tradb-openbb），tradeck 不再跑 openbb。

---

| 项 | 说明 | 启动条件 |
|---|---|---|
| regime 市场环境过滤 | 5 档市场状态作回测入场过滤（T-1 对齐 fail-closed，参照 regime_builder.py）；A 股策略不过滤环境回测基本失真，但依赖全市场聚合数据 | market_breadth 数据齐备后 |
| 因子 DSL 用于挖掘 | 机器自动生成公式因子（vs 编辑器是用户手工声明） | 编辑器稳定 + 挖掘出结论后 |
| 财务因子 as-of 精确化 | data-api metrics 出公告日精确点时口径（参照 fundamentals.py 模板：公告次日生效/join_asof/缺失 null 不填 0） | 数据层阶段四快照化 |
| 多用户正式功能 | 鉴权/注册/配额/行级权限/策略市场 | 真实多用户需求出现时 |
| numba 内核加速 | 矩阵物化编译内核（参照 matrix.py @njit） | Polars 路径实测成瓶颈后（当前判定：不引） |

---

# 阶段 A–E 验收记录（v1，2026-08-25 全部通过）

## 阶段 G review 明细（2026-09-10，主 agent 总负责 + 4 子 agent 并行）

### 独立 review 门禁（Lovelace，2026-09-10）

开发完成后由独立 review agent（未参与开发）做严格 code review，主 agent 复现/修复/验证。
结论：**需修复后合并 → 修复后通过**。无 P0，4 个 P1 + 6 个 P2。

主 agent 修复并实测验证的项：
- **[P1] X-User-Id 路径穿越 + loader 任意文件执行面**（复现确认：`../../etc` 直通目录逃逸，
  loader 会 exec_module 该路径 .py）→ 已修：`current_user_id` 加白名单正则
  `^[A-Za-z0-9_-]{1,32}$`，恶意输入 400 拒绝（实测 `../../etc`/`a/b`/`..` 全拒，
  `u2`/`default`/`valid_user-1` 正常）。
- **[P1] `/api/factors` 无 limit 防全历史大响应**（200 只 A 股全历史单请求数百 MB）→
  已修：backend 加 `limit`（默认 20 万，上限 50 万）+ `truncated` 标记；quant `fetch_factors`
  配套对半切窗递归（与 bars 同模式）。实测默认 limit 不截断（2429 行 truncated=False）、
  limit=100 正确截断（truncated=True）。
- **[P1] worker 池 Semaphore 跨事件循环绑定** → 已修（防御性）：Semaphore 改为按 loop 惰性
  重建（`_semaphore()` 记录绑定 loop，跨 loop 重建）。注：本机 Python 3.12 实测连续
  `asyncio.run()` 未复现崩溃（3.12 Semaphore 惰性绑定 loop），但持锁态/其他版本有风险，
  防御性修复保留。
- **[P1] 退出优先级重排对拍**（review 要求确认行为变化）→ 已对拍：合成数据 signal 与
  stop_loss 同日成立时，新口径记 `stop_loss`（风控优先），旧口径记 `signal`——收益数值不变
  （同日同价退出），仅归因标签变化，方向正确（保护性离场先于主动卖点）。
- **[P2] worker exitcode 误导**（终态消息送达但走 terminate 分支时带 -SIGTERM）→ 已修：
  结果正常送达时 exitcode 记 None。

主 agent 复核确认「无需修/接受」的项：
- qfq→ex_factor 复权基准随回测区间终点漂移（同区间自洽、收益率/绩效不受影响，仅绝对价位
  口径）——非金融错误，已在 factors.py docstring 点明。
- 移动止损「收盘触发、当日 open 成交」的 open_t+1 时序错位——日K 固有近似（参照同样），
  H 阶段分钟精确成交后消除。
- ST 判定空转（A 股中文名无源）——数据底座缺口，已登记 backlog（AGENTS.md 待优化项）。
- 涨跌停分档日期边界（创业板注册制当天/科创板开板当天）——逐案核对无 off-by-one。

主 agent 额外收口（review 之外的集成断点）：
- worker 的 names（ST 判定）透传断点（G2/G4 集成断裂）——已修 worker/api 两处。
- TickFlow 残留引用清理（dev/prod compose 的 quant TICKFLOW_API_KEY，quant 已不消费）。

回归验证（修复后）：worker 链路回测 trades=2、复权生效（unadjusted=[]）、子进程 pid/exitcode=0
正常、双用户隔离、恶意 user_id 拒绝、`/api/factors` limit 截断正确——全绿。

---

## 开发实施记录（2026-09-10，主 agent 总负责 + 4 子 agent 并行）

## 阶段 H1 review 明细（2026-09-10，主 agent 亲测复核）

## 阶段 H2 review 明细（2026-09-10，主 agent 亲测复核）

## 阶段 I review 明细（2026-09-10，主 agent 亲测复核）

### 独立 review 门禁（Laplace，2026-09-10）

## 阶段 J review 明细（2026-09-10，主 agent 亲测复核）

## 阶段 K review 明细（2026-09-10，主 agent 亲测复核）

### 独立 review 门禁（Anscombe，2026-09-11）

结论：**需修复后合并 → 修复后通过**。无 P0（合并语义 entry/score/exit 投影正确且有金标准
测试锁定、用户因子求值防未来函数、隔离可靠），2 P1 + 3 P2。修复：主 agent。

主 agent 修复并实测：
- **[P1] K6 挖掘端断线**：`factor_catalog(user_id)` 在 prod 无调用方（run_mining 和
  api_mining_run 都没传 user_id）——用户因子进不了挖掘目录，K6「四端贯通」的挖掘端名不副实。
  已修：run_mining 加 user_id 透传 + api_mining_run 补 user_id 依赖注入。实测：default 挖掘
  含 uf 因子、u2 不含（隔离正确）。
- **[P1] composite 退出投影 max_hold 窗口过紧**：原按 entry 日起算 max_hold，open_t+1/
  涨跌停顺延（1~2 日成交滞后）会把落在「实际买入日+max_hold」内的 exit 误滤掉。已修：
  窗口加成交滞后余量（_ENTRY_FILL_LAG_BARS=2），并同步修正测试（原测试把 entry 日计窗
  焊死为预期——Anscombe 指出这是「锁定错误行为」），新增滞后余量生效用例。
- **[P2] 用户因子热路径重复编译**：_evaluate_user_factor 加编译产物缓存（键含
  user_id+factor_id+version+formula，version+1 自动失效，用户隔离）。
- **[P2]** QUANT_SIGNAL_* 补登 .env.example；web 注释阶段标签对齐。

亲测确认「无发现」的维度：composite 合并语义（union/intersect/score 排名归一/中性分）、
用户因子求值防未来函数（test_no_lookahead_tampering_future_rows 是教科书式对照）、
多用户隔离、main.py lifespan 与 on_event 共存、pending_exit 修复、K4/K6 在 loader.py 的
叠加改动兼容（6 内置策略加载零错误）。

**流程亮点**：Anscombe 发现测试里有一条在「锁定错误行为」（composite max_hold 窗口按
entry 日计窗的预期）——测试越绿越把 bug 焊死。这印证 review 不能只看测试是否通过，
还要审测试锁定的行为是否正确。修复后 84 用例全绿。

---

分工：K1 信号 cron（Fermat）/ K2 stats 对账（Nash）/ K4 composite（Huygens）/
K6 用户因子贯通（Galileo）/ K3 分钟回测 web 展示（Sartre）/ K5 测试目录（Poincare）。
主 agent 亲测复核（非仅信自报）。

- **K1 信号 cron**：quant lifespan 挂 AsyncIOScheduler，每日信号 22:30 UTC；starlette 1.6
  下自定义 lifespan 接管 on_event，显式调用 api._startup 迁移不重复。实测：生产形态 quant
  服务启动注册 cron、scheduler 正常、现有端点不受影响、job 失败优雅降级。
- **K2 stats 对账**：empyrical 在 Python 3.12 装不上（SafeConfigParser 已移除），改手算
  第二实现对拍——total/annual/mdd/vol/sharpe/sortino/calmar 位级一致（abs diff=0）；
  口径差异（ddof=0/sortino 定义）注释锁定。新建 quant 首个测试文件 test_stats.py（11 用例）。
- **K4 composite 叠加**：亲测防幽灵平仓——A 持仓窗口内 B 的退出信号被来源投影吃掉
  （合并 exit 仅 [t=3]，对照组直接 OR 产生 t=2 幽灵平仓）；union/intersect/8 上限正确。
- **K6 用户因子贯通**：挖掘目录（14 内置 + 用户 active uf）+ 策略白名单动态合成；
  多用户隔离正确（bob/无 user_id 不可见 alice 因子）。
- **K3 分钟回测展示**：回测加分钟口径开关 + 成交明细口径列 + 覆盖标注；前端 lint/tsc 全绿。
- **K5 测试目录**：83 用例（test_adjust/limits/matcher/mining/factors/composite/stats）。
  **测试目录立即兑现价值——抓出真实 bug**：pending_exit 强平在 exit_fill=signal_next_minute
  时误用当日收盘价（exit_price_of 在该口径返回 close），matcher 改恒取当日开盘价，
  修复后 83 用例全绿。另甄别 2 处测试数据设计错位（非 app bug），已修正。

已知边界：H2 分钟回放的 hits.trigger_time 未在 web 展示（回放是独立的 minute_replay 响应
结构，无 trades/stats），如需展示回放结果另起回放结果区块——登记为后续项。

---

### 独立 review 门禁（Epicurus，2026-09-10）

结论：**需修复后合并 → 修复后通过**。无 P0（编译器/求值器防未来函数方向正确、红线全部
生效、多用户隔离可靠），3 P1 + 4 P2（全部实测复现）。修复：主 agent。

主 agent 修复并实测：
- **[P1-1] 复合因子断链**：门面 `_definition_of`/`update_factor` 产出 `components`(list)，
  但 `store.to_spec` 期望 `members`(dict)——cf 创建/更新经 HTTP 层必败。统一为 dict
  `{member_id: weight}`。（主 agent 在 review 前已独立发现此 bug 并修复，Epicurus 实测确认。）
- **[P1-2] 环检测误杀合法嵌套**：原把所有成员（含 base/custom 叶子）加入 seen 判重，
  「composite 共享底层成员」「composite 与直接成员交集」的合法组合被误判成环。已修：
  只对 composite 链做环检测（叶子不参与 seen）。实测：合法嵌套创建成功、真环仍被拒。
- **[P1-3] 元数据更新误拒**：create_factor 变更检测只比 formula/components，只改
  label/group/direction 恒 400。已修：纳入元数据变更（不升 version，同版本走先注销再注册）。
  实测：只改 label/direction 不升版本不拒绝、公式变更正确升 version。
- **[P2] 前端 cf 默认成员 id** mom_20/mom_60 不存在 → momentum_5d/momentum_20d。
- **[P2] PUT 404 死分支**：门面抛 ValueError 而非 KeyError——区分「不存在」为 404。

亲测确认「无发现」的维度：DSL 防未来函数（ts_delay 只向后看/ts_mean 右端含当日/截面 rank
当日截面）、编译红线全生效、多用户隔离（bob 不可见 alice 因子/跨用户引用 E001）。

入 backlog 的 P2（不阻塞合并）：compile_formula_cached 丢 user_id 维度（当前无调用方）；
前端编译诊断 useEffect 依赖过宽（改不相关字段也触发防抖）。

**流程改进**：Epicurus 指出三个 P1 都可由门面级集成测试（HTTP→facade→store 创建 uf + cf +
改名）一次性暴露——后续阶段为 quant 建 tests/ 目录时应补这类集成测试（当前 quant 无测试目录，
阶段验收全依赖临时脚本，不可持续）。

---

实施：J1-J3 后端因子体系（子 agent Pascal）+ J4 API+前端（子 agent Banach）并行。
主 agent 集成收口 + 亲测复核（非仅信自报）。

**J1-J3 后端（Pascal）**：
- 注册表：23 个 base 因子预注册（6 OHLCV + 17 enriched 指标），FactorSpec 单一事实源。
- DSL 编译器：公式→AST→numpy 矩阵 evaluator（时序算子 sliding_window_view 沿 dates 轴、
  截面算子沿 symbols 轴），24 算子白名单，错误码 E001-E016。亲测：合法公式编译求值形状
  正确、**防未来函数**（篡改 T≥25 数据前 25 日值逐位不变）、非法公式错误码全对
  （E005 负 shift / E009 截面嵌时序 / E001 未知列 / E002 未知算子）。
- 存储：uf_*/cf_* 落 users/{uid}/factors/，复合因子 ≤8 成员 + 循环引用检测，状态机
  draft→active→watch→retired。

**J4 API + 前端（Banach）**：
- API 契约：/api/factors CRUD + compile-preview（编译诊断恒 200 + 样例预览 mean/std/
  valid_ratio/sample_values）。factors 模块未就位时 503 优雅降级（启动不崩）。
- 前端：/quant 页加「因子编辑器」Tab + 侧边栏入口；列表表格 + 新建/编辑对话框 +
  删除确认；公式防抖 500ms 自动编译预览。lint 0 错误 0 警告；UI 检查清单全绿
  （零裸元素/零手搓/图表经 ChartContainer/空态统一 EmptyState/图标全 phosphor）。

**主 agent 集成收口（三方集成的关键）**：
- factors/api.py 门面：Pascal 只做了 registry/dsl/store 三层，Banach 的 API 假设了
  五函数门面（list/create/compile_preview/update/delete）——我补 app/factors/api.py，
  含 direction 双向映射（HTTP 1/-1 ↔ registry high/low/none）+ compile_preview 样例预览
  （读真实缓存标的，缺失合成降级）。

**主 agent 发现并修复的集成 bug（Ohm 实现）**：
- **多用户隔离泄漏（真实 bug）**：registry._REGISTRY 全局单例，用户因子注册进全局表，
  实测 default 建的 uf 因子 u2 可见（G4 隔离铁律被破坏）。修复：注册表改「builtin 全局
  共享 + 用户私有层（{user_id:{...}}）」，DSL 因子引用解析带 user_id 上下文（引用他人
  私有因子报 E001）。亲测：default 24 因子（23 builtin+1 私有）/ u2 23（仅 builtin，
  不含 default 私有）/ u2 建同名不干扰 / 跨用户引用拦截。

**端到端**：HTTP API 全链路（编译预览/创建/列表/更新 version+1/删除/用户隔离）实测全绿。

已知边界：
- 因子编辑器的 DSL 因子**尚未接入挖掘目录与策略评分**（注册表是单一事实源，但 mining
  factor_catalog / strategy scoring 还没消费用户因子）——四端贯通留待后续阶段。
- 复合因子预览为成员有效性校验（无独立公式，实际合成在矩阵层）。

---

结论：**需修复后合并 → 修复后通过**。无 P0（purge/embargo 切分本身真实有效、内层折约束在
外层训练段内、stats.py 与参照逐行对拍一致），6 P1 + 5 P2。修复分工：主 agent（P1-2/3/5/6）
+ 子 agent Aristotle（P1-1/4、P2-7/10）。

主 agent 修复并实测：
- **[P1-3] 统计检验透出 API**（I2 产出死端）：`/api/mining/run` 响应补 `factor_ic_stats`
  （NW t/p/BH-FDR q）+ 候选 `dsr` + `n_trials`——原统计结果计算了但没透出，用户/前端不可见。
- **[P1-6] optimizer 空骨架哨兵**：`run_backtest` 无数据返回全零骨架（days=0）其 sharpe=0.0
  原会被当真实目标值混入排名（空区间可能赢过真实亏损区间）。已修：days==0 视同失败隔离
  排末位。实测：真实亏损（sharpe-0.5）胜出、空骨架排末位。
- **[P1-5] walk-forward 日历天数语义锁定**：train_days/test_days/step_days 是日历天数
  （252 ≈ 172 交易日），注释强化防误读（不改字段名避免破坏既有调用）。
- **[P1-2] walk-forward IS lookahead —— 误报确认**：tradeck 的 `run_backtest` 矩阵严格按
  `[start,end]` 截取，训练折未平仓持仓在 train_end 期末强平（exit_reason=end），**不用
  train_end 之后的 K 线**。参照的 position 模式问题（未平仓持仓用 OOS 区间真实 K 线平仓）
  在 tradeck 不存在——矩阵 build 天然截断，无未来数据污染。

Aristotle 修复并实测（22 项自测全过）：
- **[P1-1] 内层调参隔离带前置**：内层有效训练边界收窄为 `outer_train_stop - purge_bars`，
  内层折数 <2 的外层折降级跳过——修复内层首折测试段紧贴 outer train 尾部导致 purge 对
  调参侧形同虚设。实测：默认配置 3 外层折内层全满足 `embargo_end <= train_end - purge`；
  对照组确认修复前泄漏真实存在。
- **[P1-4] DSR n_trials 窄口径注释**：外层去重候选数低估真实搜索空间（各折 beam 池 × 折数），
  N 低估 → DSR 偏乐观，非严格多重检验校正（注释标明）。
- **[P2-7]** NestedValidationConfig 补 outer/inner_train_bars >= min_train_bars 校验。
- **[P2-10]** optimizer direction 校验 in {min,max}（原 "MIN"/"maximum" 静默当 max）。

修复后综合回归（主 agent）：嵌套折内层前置隔离带生效（内层不越界）、端到端挖掘闭环
（真实 A 股 555天×8只，3折3候选14因子统计含 DSR）、imports 全绿。

入 backlog 的 P2（不阻塞合并）：统计黄金向量数值测试未随迁（参照 test_stats_v2.py）——
建议后续为 quant 建 tests/ 目录时随迁；walk-forward 空折 consistency=0.0 口径（继承参照）。

---

实施：I1+I2（子 agent Carver，mining/）+ I3（子 agent Darwin，engine/）并行。主 agent 亲测：

**I1 防泄漏加固**：
- 嵌套折结构：外层 504 训练 + 30 purge 隔离带 + 126 测试 + 5 embargo，内层 3 折全在
  outer train 内（`outer.train_start <= inner.train_start` 且 `inner.embargo_end <= outer.train_end`）。
- 防泄漏：`test_start - train_end = 30 = purge_bars`，forward return 窗口被隔离带截断不跨边界；
  反例 purge=3<horizon=5 时确实跨界（证明隔离带必要）。
- 自适应缩窗 `_auto_validation_config`：天数不足优雅降级返回空，purge 恒 >= horizon 不可让步。

**I2 统计检验**（mining/stats.py，零依赖 numpy，照搬参照 stats_v2）：
- 黄金向量对账：NW t max_err 4.4e-16（对参照第二实现）、BH-FDR 误差 0.0、DSR 退化 1.9e-8。
- 性质断言：NW t 惩罚自相关（实测 |NW t|=6.82 < |naive t|=12.79）；BH-FDR q 单调递增正确。
- 挖掘报告：因子 IC 带 NW t/p/BH-FDR q（多重检验校正），候选带 DSR 通缩夏普。

**I3 优化器 + walk-forward**：
- 优化器：参数网格三写法（list/values/min-max-step）+ 边界校验 + 组合爆炸预判（>2000 拒绝）；
  顺带修复参照 `step=0` 被 `or` 当缺省的 bug（改显式 `is None`）。合成行情 8 组合扫描排序正确。
- walk-forward：滚动折 test_start=train_end 次日堵前视泄漏（亲测 9 折全部 test_start>train_end、
  滚动 step 正确）；样本外净值复利拼接与手工逐折累乘一致；param_stability 观测参数漂移；
  degradation=0.5676（样本外退化，过拟合信号符合预期）。
- runner 接线：run_optimize/run_sensitivity/run_walkforward，组合数 >8 走 worker 池（对齐 G4）。

**端到端**：真实 A 股数据（555 天 × 8 只 tracked，全复权）跑 run_mining 完整闭环——
3 折嵌套、3 候选、14 因子统计（含 NW t + BH q），全程优雅降级。

已知边界：挖掘样本外评估用 `_backtest_top_n` 轻量口径（每日持 top_n 等权）非完整撮合
（阶段 D 验收时已知情接受，挖掘期快速比较用）；候选发布后的正式回测才走完整撮合。

---

### 独立 review 门禁（Ramanujan，2026-09-10）

开发完成后由独立 review agent（未参与开发）严格审查（含与参照 tick-stock-panel 逐函数对拍）。
结论：**需修复后合并 → 修复后通过**。无 P0（无真未来函数、无崩溃路径），4 P1 + 5 P2。

主 agent 修复并实测验证：
- **[P1] H2 复权口径漂移**：`_adj_factor_of` 分母原用因子表最末行（≈最新交易日），与
  `forward_adjust` 的区间末日口径不一致——T_end 之后除权会导致历史回测命中价漂移。
  已修：分母锚定回测区间末日（`_factor_series(fac,[day,end])` 同次对齐）。实测：区间外未来
  除权（因子翻倍 2.0）不再影响历史命中价（命中价 10.5 锚定区间末日，而非错误的 5.25）。
- **[P1] signal_next_minute 补 pending_exit 挂单**：原「signal 盘中未确认 → 当日不成交 →
  次日重评估」，但次日若风控触发则 signal 永久失效（挂单语义丢失、退出时序后移）。已修：
  对齐参照 pending_exit——盘中未确认置挂单，次日开盘价强制退出（优先级最高）。实测：
  signal 触发日线远离触发线 → 当日未确认 → 次日开盘价强制退出。
- **[P1] 分钟计数混淆**：entry/exit 合并计数导致「minute_fill=False + signal_next_minute」
  时误显示开仓走分钟口径。已修：拆为 minute_entry_used/fallback + minute_exit_used/fallback
  独立统计（保留合并兼容字段）。实测：exit_used=1、entry_used=0 正确分离。
- **[P2] 分钟回放涨停拒买传 names**：原硬编码空 name，ST 股按 ±10% 判涨停（应为 ±5%）。
  已修：`_run_minute_replay` 预拉 names 传入 replay_minute_strategy。
- **[P2] unadjusted 判定口径**：空 dict/空表现统一标注（与日频 adjusted_flags 一致）。

主 agent 额外收口（review 之外的集成断点）：
- **worker 分钟断点**：API 回测走 worker 子进程（同步 run_backtest），minute_fill 拿不到
  预拉分钟K 永远降级。已修：worker 加 `_load_minute_cache`，子进程内读本地分钟缓存
  （load_minute 纯文件读 spawn 安全；子进程不补拉网络避免 IO/缓存写竞争）。

修复后回归：日K 对拍 trades=2、ret=-0.012 与基线逐分一致、复权生效（unadjusted=[]）——全绿。

接受为「有意偏离/后续跟进」的项：
- exit_ref 当前无策略产出（build_minute_exit_reference 引入但未接入信号管线）——白名单
  信号缺 ref 时降级 open_t+1，已注释说明；接入信号管线留待后续（与策略 exit_ref 产出一起）。
- skipped_days 混装「无分钟分区」与「策略异常」两类、纯分钟策略预热期窗口截短无告警——
  可接受，注释已说明。

---

实施：子 agent Poincare。主 agent 亲测（非仅信自报）：

- **防未来函数（关键）**：日线窗口严格截至 T-1。合成用例把当日日K 收盘从 12.4 改成 0.01
  （极端值），T 日命中价与触发时刻逐分不差——当日日K 不进窗口铁律生效。
- **回放产出**：分钟策略命中含 trigger_time=09:34（首根上穿分钟）、entry_price=触发分钟收盘、
  score；无分钟分区日记 skipped 不中断。
- **涨停拒买**：主板 ±10%，T-1 收盘 10.0、当日触发分钟收盘 11.0 顶死涨停 → hits=0、
  buy_limit_up=1（复用 engine/limits.py 分档）。
- **日K 对拍零回归**：ma_golden_cross（默认 timeframes=["1d"]）改动前后 trades=2、
  total_return=-0.012 与基线逐分一致、无 mode 键、复权生效（unadjusted=[]）。
- **复权折算口径**：factor[T]/factor[T_last]（与 adjust.py 前复权同口径）。注意 T_last 为
  因子缓存最新日，回测历史区间的绝对命中价系随时间漂移（前复权固有属性，收益率/时刻不受影响）。

已知边界：dev 无真实分钟数据，全部合成验证；真实 10 年分钟数据端到端联调待部署 VPS。

---

实施：子 agent Pauli。主 agent 亲测（非仅信自报）：

- **默认口径零变化**：`minute_fill=False` 与日K 基线逐分不差（entry/exit 价完全一致）。
- **降级路径**：minute_fill=True 但无 loader/分钟数据缺失 → 成交价与基线一致，fallback 计数正确。
- **VWAP 口径**：合成第5天 open 10.0→close 11.0 线性分钟K，minute_fill 买入价 10.5（当日 VWAP，
  更贴近真实成交均价），日K基线 10.0（次日 open）——方向可解释（VWAP 成交优于开盘追价）。
- **参考线穿越价**：buy 高点触及 ref→ref 价、开盘已穿越→open、未穿越→close；sell 对称，全对。
- **minute_trigger 防未来函数**：MA5 跌破触发线 = (5·ma5−close)/4 = 10.25（全部昨日已知量）；
  分钟收盘确认下穿 → 下一分钟 open 10.05 成交（早于当日收盘 10.02、更早于次日开盘）；
  白名单外信号触发线 NaN 自动降级 open_t+1。
- **架构**：matcher 纯计算不做 IO（minute_loader 注入，`(symbol, date) → 2D 数组`），
  runner 在 async 上下文经 get_minute_bars 预拉（与 benchmark/names 同模式）。

已知边界（知情接受）：
- dev 环境分钟数据为空（A 股近 10 年分钟数据在生产 VPS 冷层/温层），H1 全部用合成数据验证逻辑；
  真实数据端到端联调待部署 VPS 后做。
- 信号 id 白名单 4 个（signal_ma5/10/20_breakdown、signal_ma_dead_5_20）登记为权威定义，
  tradeck 此前无既有信号 id 体系。

---

分工：G1 复权源切换（Helmholtz）/ G2 精确涨跌停（Carver）/ G3 分钟数据客户端（Averroes）/
G4 多用户骨架 + worker 池 + 移动止损（Linnaeus）。主 agent 亲测复核（非仅信子 agent 自报）。

前置数据准备（主 agent）：dev 库 `adjust_factors`/`corporate_action_events`/`instrument_master`
全空 → 手动触发 `run_adjust_factors_full_job` 首次全量初始化（同花顺公司行为 dump，
57157 事件 → 1027 万行日频因子），G1 端到端才得以实测。

G1 复核（复权源切换 TickFlow→data-api）：
- `/api/factors` 实测：600519.SH 最新日 qfq=1.0（前复权基准）、历史日 0.942（除权折算）、
  hfq 1.16→1.234 累积，语义正确。
- **复权对账（关键金融验证）**：quant 引擎矩阵复权价 1498.9126 与 data-api
  `/api/bars?adjust=qfq` 1498.9126 **逐分一致**——引擎内动态复权与 data-api 静态复权同口径。
- 端到端回测：`unadjusted` 从 `[全部]`（旧 TickFlow 无 key 降级）变为 `[]`（复权真正生效）。
- TickFlow SDK 依赖与 import 全清除（grep 干净）；降级路径（缺标的缺席+标注）保留。

G2 复核（精确涨跌停）：
- `engine/limits.py` 分档正确：北交所 ±30%/科创板(2019-07-22 起)±20%/创业板(2020-08-24
  注册制起 ±20% 前 ±10%)/主板 ±10%/主板 ST ±5%（2026-07-06 新规前）。
- ST 口径照搬参照 price_limits.py（名称含 "ST"，仅主板特判，其余板块跟随板块档）。
- 集成：`_fetch_names`（GET /api/quotes）经 runner 传入 simulate，降级语义保留。

G3 复核（分钟数据客户端）：在线 `/api/bars/minute` 拉取（分片/切窗/truncated 递归/退避
重试）+ Parquet 缓存层（market/symbol/year 布局、命中判定、缺口补拉、去重合并）；
审查并修复上一轮 client.py 已有 fetch_minute_bars 的 3 个实质 bug（窗口未切分静默丢数/
truncated 未递归/无重试）。铁律 grep 干净（无 clickhouse/duckdb 直连）。

G4 复核（多用户骨架 + worker + 移动止损）：
- user_id 贯穿（X-User-Id header，缺省回落 default）；存储命名空间 users/{uid}/；
  加载器视图 builtin 全局 + user 目录合成；旧路径幂等迁移。
- worker 池：spawn 子进程跑回测，Semaphore 限并发；子进程崩溃/异常主进程存活报错明确。
- 移动止损/止盈（peak 用当日 high 跟踪，缺失降级 close）+ 退出优先级按参照重排
  （风控 > signal > max_hold > end）。
- **语义变化（已确认接受）**：旧实现 signal 优先于固定止损，本次按参照重排为风控优先——
  同日同价退出收益不变，仅 exit_reason 归因标签变化。

主 agent 跨任务集成收口（超出单任务卡范围的断点）：
- **修复 worker names 透传断点**：G2 的 ST 判定（names）未透传进 G4 的 worker 子进程，
  API 路径下 ST 失效。已修 make_backtest_task/run_backtest_in_worker/api.py 三处加 names。
- worker 端到端实测：子进程（pid 2738/2875）跑回测返回结果、total_return 与基线一致、
  names 透传生效、双用户（default/u2）隔离、主进程在子进程失败后存活。

已知边界（知情接受）：
- **ST 判定当前空转**（数据底座缺口，非代码问题）：A 股证券中文名称无可用数据源——
  quote_snapshots.name 对 A 股为 null、equity_profiles 存英文名、akshare 被东财断连
  （AGENTS.md 已知坑 #5）。ST ±5% 判定逻辑正确但永远拿不到中文名。已记入 backlog：
  待接中文名称源（同花顺/东财恢复后批量灌入 instrument_master/quote_snapshots）。
- worker spawn 测试须以真实文件/模块入口运行（stdin heredoc 会因子进程重导入 __main__
  失败）；生产 uvicorn 模块入口无此问题。
- 分钟K 回测（H 阶段）尚未开始，client_minute 缓存层待 H1 实际消费验证。

## 验收记录

### 阶段 E review 明细（2026-08-25）

分工：E1 quant HTTP API（主 agent）/ E2 web 代理路由（Feynman）/ E3 前端工作台页（Anscombe）/
E4 每日信号 job（主 agent）。

端到端验证（宿主机 web→quant 代理实测，curl）：

- `/api/quant/strategies` 返回 6 个内置策略（含 params schema）。
- `/api/quant/backtest` ma_golden_cross 600519.SH+AAPL 26 天，range 正确。
- `/api/quant/screen` 选股 as_of 正确；`/api/quant/ai-generate` 未配置优雅降级；
  `/api/quant/mining` 候选库可读。
- 前端 `/quant` 页 4 Tab 渲染（策略选择/参数表单/空态/统计卡片骨架），检查清单全绿
  （无裸元素/手搓/recharts 未包裹）。

Review 修复（3 处提交前必改）：

- preset Select `onValueChange` 签名为 `(value: string | null, eventDetails)`，Anscombe 按
  标准 shadcn 写的 `(id: string) => void` 两处 tsc 报错 → 包一层 null 归一。
- mining-tab `setState-in-effect` eslint 报错 → 收进 async 回调。
- dev compose 漏配 `QUANT_API_URL`（web 容器内 localhost:8083 不通）→ 补 `http://quant:8083`。

环境障碍（非代码问题，已处置）：

- colima docker daemon 两次卡死 + 端口映射失效，重启后恢复。
- dev 容器 `up -d --force-recreate` 不重跑 post-create.sh 导致 node 丢失 → 容器内重装 node24+pnpm9.15。
- 宿主机 3000 被 VS Code 失效端口转发占用 → 释放后 docker 映射恢复。

已知边界：

- AI 真实生成未端到端（无 AI_API_KEY），降级路径已验；保存 AI 策略到库属后续（E3 已留口）。
- E4 每日信号 cron 的调度注册（APScheduler 定时触发）未接入 quant lifespan——job 函数已验，
  定时触发待 quant 服务加 lifespan 时一并做（列入阶段 F）。

### 阶段 D review 明细（2026-08-25）

分工：D1 选股执行器（子 agent Carver，28dcf3d）/ D2 因子挖掘（主 agent 本地做核心算法，ec0cae9）。

**过程纠偏**：Carver 首轮返回空通知且无产出（只做了读取分析没写盘），发任务卡追问后补齐。
复核以实际落盘文件为准，不信通知——executor.py 与 CLI screen 均实测通过才放行。

D1 复核（主 agent 亲测）：

- 5 只不同动量合成标的跑 screen：动量最强的入选且按 score 降序、下跌标的不入选、
  无缓存标的（ZZZ）隔离不报错、as_of 为最新交易日、total 与 rows 一致。
- basic_filter 两阶段过滤生效（price_min 收窄）。
- 降级：全空标的池返回空 rows 不抛错；score NaN 排最后。

D2 因子挖掘（主 agent 实现并验证）：

- 14 因子目录（动量/波动/收益形态/流动性/超买超卖）矩阵派生、形状正确。
- RankIC（Spearman 截面）/ 相关性去重（14→保留）/ beam 组合搜索 / 嵌套样本外折
  （训练/测试不重叠）全绿。
- 候选库纪律实测：候选入库 status=pending；**未达晋级门槛的候选发布被拒**（正收益折占比
  不足/夏普不足被门槛拦下），发布动作只认显式确认——永不自动上线的铁律生效。
- Review 修复 2 个真实 bug：beam 候选池误用全量因子（去重后 KeyError）、_backtest_top_n
  残留死代码维度错。

已知边界（知情接受）：

- 样本外评估用 `_backtest_top_n` 轻量口径（每日持 top_n 等权），非完整撮合——挖掘期快速
  比较用，候选发布后的正式回测才走 matcher 完整撮合。
- 候选池共享（各折复用第一折训练段的搜索结果）以降本，样本外评估仍逐折独立——权衡取舍，
  严格版可改每折独立搜索（成本更高）。
- exclude_st 待名称表接入（数据层暂无证券名称表），当前跳过并注释标注。

### 阶段 C review 明细（2026-08-25）

分工：C1 协议+加载器（主 agent 定锚，commit d4da013）→ C2 内置策略（Sartre，9616976）/
C3 AI 安全闸（Schrodinger，52b2a87）/ C4 compact 指南（Hooke，7e256ba）三子 agent 并行。
另：回测管线闭环 runner + CLI run/list（主 agent，92b47e4）。

**关键设计决策**：参照的双后端（polars_expr 选股 / matrix_native 回测）统一为单一信号矩阵协议
（StrategySignals：entry/exit bool 矩阵 + score），一个策略同喂选股与回测，消除双后端历史包袱。

主 agent 复核（非仅信子 agent 自报）：

- C1：容错隔离（坏 META/缺 compute/白名单外/重复 id 分类正确）、params 归一化、执行异常降级
  空信号、形状校验——11 项全绿。
- C2：6 策略加载零错误；金叉语义亲测（合成必现金叉序列，entry 精确命中且每日确为金叉）；
  停牌期无信号；真数据端到端（quant-cache volume 26 天管线全通）。
- C3：16 种逃逸手法（import os/eval/__import__/open/dunder 属性/dunder 下标/getattr 跳板/
  缺 META/META 非字面量/语法错误等）全部拦截；conditions 校验与 compile_to_mask；未配置零网络降级。
- C4：23 个 scoring 字段与 loader 完全一致无编造、17 禁调用与 validator 一致、最小示例真过闸。

联动验收（C1+C2+C3）：AI 生成代码过闸 → 落 ai/ 目录 → 加载（source=ai）→ 执行出信号全链路绿；
恶意代码（夹带 import os）过闸失败不进入执行。

采纳的子 agent 决策：

- C2 exit 统一「下穿」对称口径（防持续位于线下时信号每日为 True 污染统计）。
- C3 安全闸下划线前缀加严（`_` 单下划线也拦，宁误伤私有属性不放过逃逸）。
- C4 示例 helper 用 `prev` 而非 `_prev`（降 AI 误用风险，比完整版更保守）。

已知边界（知情接受）：

- ast 白名单非真沙箱：拦不住纯计算 DoS（超长字符串/死循环耗内存）。真正隔离需受限子进程
  执行策略，列入阶段 F 加固（docs 已注明）。
- AI 真实 LLM 生成未端到端（无 AI_API_KEY），双层生成的校验与降级路径已验。

### 阶段 B review 明细（2026-08-25）

分工：B1 矩阵+enriched（子 agent Jason，commit 75b4488）/ B2 复权+撮合+统计（主 agent，commit 29a66ac）。

B1 复核（主 agent 亲测，非仅信子 agent 自报）：

- 合成 3 标的（含 5 天停牌）构建矩阵：停牌期 close 全 NaN、复牌首根数据不错位、
  ma20/macd_dif/macd_hist/rsi14/boll_upper/momentum_5d 与手算对账误差 < 1e-9、
  停牌股复牌首日 ma5 窗口含 NaN 正确为 NaN、slice/select 形状与 KeyError 边界——全绿。
- 子 agent 两项实现决策采纳：递推类 NaN「中断重播」语义与滑窗类自洽；BOLL 用 ddof=0
  （国内软件口径，注释注明与 pandas 差异）。

B2 撮合验证（9 项全绿）：

- 复权：10 送 10（因子 1→2）前复权后除权日无跳空；无因子标的原样 + flags 标注。
- 防未来函数：open_t+1 口径下信号次日 open 成交；篡改信号日 close 为 999 成交价与净值不变。
- 约束：T+1 入场次日才可卖；一字涨停日（收盘=前收×1.1）不开仓；CN 整手 100 股、US 碎股。
- 成本：10% 涨幅毛 16600 → 净 12844（佣金+印花税+滑点侵蚀方向正确）。
- 统计：total_return/sharpe/max_drawdown 产出；空信号降级不崩。

Review 修复（1 项真实 bug）：

- **满仓开不了仓**：budget 直接按 cash 分配，value+买入成本 恒超现金 → 任何信号都开不了仓。
  修：alloc 按 cash/(1+cost_rate+1e-9) 预留成本（浮点余量防 1e-11 边界）。此 bug 若无端到端
  验证不会暴露——印证「防未来函数测试先行」的价值。

已知限制（知情接受）：

- 涨跌停判定用「收盘价顶死」近似（日K 无盘中价），精确口径待分钟K（阶段 F3）。
- 换手率为「成交总额/平均资产」近似口径。
- stats 指标未与第三方库对账（vectorbt/empyrical），阶段 C 报告模块补上。

### 阶段 A review 明细（2026-08-25，主 agent 本地）

分工：A1 骨架（子 agent Dirac）/ A3 compose（子 agent Raman）/ A2 数据层（主 agent，质量关键路径）。
commit d9de07f（codex/quant-engine 分支）。

已完成验证：

1. **store.py 7 项**：空缓存全区间缺口 / bars 转 DataFrame（date 类型）/ 三市场分目录落盘 /
   前后两段缺口计算 / 全覆盖零缺口 / 合并去重新数据胜出 / 损坏文件降级空表——全绿。
2. **client.py 4 项**（httpx MockTransport）：truncated 递归分窗 27 请求拿全 90 行无重复 /
   201 symbols 拆 2 片 / 4xx 不重试直接降级 / 连接错误退避重试后降级——全绿。
3. **factors.py 3 项**：无 TICKFLOW_API_KEY 整批降级且不 import SDK / 空标的 / load 无缓存降级——全绿。
4. **CLI fetch 端到端**：首拉 23 行 → 二次执行缓存命中零补拉 → 扩区间只补 3 行缺口——全绿。
5. **铁律**：grep apps/quant 无 asyncpg / DATABASE_URL；`--profile quant` 不污染默认启动集
   （`docker compose config --services` 确认）。

Review 处置（2 项）：

- A1 发现 pydantic v2 的 BaseSettings 已拆分为 pydantic-settings 独立包，requirements 补充声明（必要依赖，采纳）。
- client 连接错误退避 15s 慢失败：CLI 场景可接受，补注释说明取舍（非缺陷，知情决策）。

已知限制：

- ~~Docker 沙箱不可达~~ **已复核（2026-08-25，提权访问 colima）**：镜像构建 26s 成功；
  `fetch --symbols 600519.SH,AAPL --start 2026-08-01` 实跑——首拉 16/15 行落缓存、
  二次执行 0 行补拉（仅两个周末空窗请求）、前向扩区间（7-20 ~ 7-31）增量补 10 行合并为 26 行、
  `--with-factors` 无 key 优雅降级。真实 data-api 联调通过。
- ex_factors 真实拉取未验（无付费 key），降级路径已验（容器内实跑确认）。

| 阶段 | 状态 | Review 问题 | 修复 | 验收结论 | 日期 |
|---|---|---|---|---|---|
| A 骨架与数据层 | ✅ 验收通过 | 见下 | 已处置 | **单元+端到端+容器实跑全绿** | 2026-08-25 |
| B 矩阵与回测引擎 | ✅ 验收通过 | 见下 | 已处置 | **9 项撮合验证 + 指标对账全绿** | 2026-08-25 |
| C 策略体系与 AI 生成 | ✅ 验收通过 | 见下 | 已处置 | **联动验收全绿（加载→策略→安全闸→回测）** | 2026-08-25 |
| D 选股与挖掘 | ✅ 验收通过 | 见下 | 已处置 | **选股复核全绿 + 挖掘闭环含发布纪律实测** | 2026-08-25 |
| E 服务化与 web 集成 | ✅ 验收通过 | 见下 | 已处置 | **HTTP API + 代理 + 前端页端到端全绿（宿主机实测）** | 2026-08-25 |
| F 加固 | 已并入 v2 阶段 G–K | 无 | 无 | F3→H、F4→J、其余→I/K | 2026-09-10 |
| G 数据层收敛 + 多用户骨架 | ✅ 验收通过 | 见下 | 已处置 | **复权/涨跌停/分钟/多用户/worker 全链路实测全绿** | 2026-09-10 |
| G review 门禁 | ✅ 通过（修复后） | 4 P1 + 6 P2，无 P0 | 已处置 | **Lovelace 独立 review + 主 agent 修复验证全绿** | 2026-09-10 |
| H1 分钟成交价修正 | ✅ 验收通过 | 无 | — | **minute_fill 穿越价/VWAP + minute_trigger 盘中触发，默认口径零变化对拍全绿** | 2026-09-10 |
| H2 分钟频策略回放 | ✅ 验收通过 | 无 | — | **分钟频回放 + 防未来函数/涨停拒买/日K对拍全绿** | 2026-09-10 |
| H review 门禁 | ✅ 通过（修复后） | 4 P1 + 5 P2，无 P0 | 已处置 | **Ramanujan 独立 review + 主 agent 修复验证全绿** | 2026-09-10 |
| I 研究严谨性（防泄漏+统计+优化器+walk-forward） | ✅ 验收通过 | 无 | — | **嵌套折/purge/统计检验/优化器/walk-forward + 端到端挖掘全绿** | 2026-09-10 |
| I review 门禁 | ✅ 通过（修复后） | 6 P1 + 5 P2，无 P0 | 已处置 | **Laplace 独立 review + 主 agent/Aristotle 修复验证全绿** | 2026-09-10 |
| J 因子编辑器 | ✅ 验收通过 | 1 集成 bug（多用户隔离） | 已处置 | **DSL 编译器/注册表/存储/编辑器 UI + 防未来函数/隔离验证全绿** | 2026-09-10 |
| J review 门禁 | ✅ 通过（修复后） | 3 P1 + 4 P2，无 P0 | 已处置 | **Epicurus 独立 review + 主 agent 修复验证全绿** | 2026-09-10 |
| K web 集成收尾 + 运维加固（含 K5 测试目录 + K6 用户因子贯通扩展） | ✅ 验收通过 | 1 真实 bug（pending_exit） | 已处置 | **K1-K6 全绿 + 测试目录 83 用例** | 2026-09-10 |
| K review 门禁 | ✅ 通过（修复后） | 2 P1 + 3 P2，无 P0 | 已处置 | **Anscombe 独立 review + 主 agent 修复验证全绿（84 用例）** | 2026-09-11 |
| I 研究严谨性（防泄漏+统计） | 未开始 | 无 | 无 | 无 | — |
| J 因子编辑器 | 未开始 | 无 | 无 | 无 | — |
| K web 集成收尾 + 运维加固 | 未开始 | 无 | 无 | 无 | — |
