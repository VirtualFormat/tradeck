# 银河星耀数智 AmazingData 接入 — 任务拆解与验收

> 主 agent（项目经理角色）按此文件派活；每个阶段完成后执行 review → 修复 → 验收，全绿才进入下一阶段。
> 本文是施工文件，验收结果逐阶段回填到「验收记录」。SDK 文档在仓库外 `../xysz`（不入库），接口细节以 `xysz/WealthManager/ad_skills/ad_api/SKILL.md` 与 `xysz/xysz_tools/AmazingData开发手册.md` 为准。

## 0. 背景与定位

**AmazingData 是什么**：中国银河证券「星耀数智」量化平台的官方数据 SDK（`AmazingData` 纯 Python 封装 + `tgw` 预编译 C++ 通道库）。数据面覆盖 A 股（沪深北）Level-1 快照/实时订阅、1m~年线 K 线（2013 至今）、代码表/交易日历/复权因子/停复牌、三大报表 + 业绩快报/预告、股东/分红/解禁、两融/龙虎榜/大宗、指数成分权重、行业日行情、上市公司公告明细 + PDF、可转债/ETF/期权。

**在本项目的定位（2026-09-02 定）**：A 股（沪深北）数据的**主用官方源 + akshare 的容灾兜底**，接入对象是独立的 `apps/data-collector`（单点数据服务）。日K 主线**不迁**（同花顺 dump + TickFlow 已成熟），AmazingData 日K 仅作交叉校验/兜底。

它直接消化 backlog 里的几条存量痛点：
- akshare 被东财封/断连时的 A 股报价、板块热度、资金流兜底；
- A 股财报日历（akshare `stock_yysj_em` 已失效，现跳过）；
- A 股公告、业绩预告/快报、市场宽度的稳定官方源。

**为什么能当主力（三个前提已确认）**：
1. 数据服务本就是单点（collector 单实例、APScheduler 内嵌、`--workers 1`），与 AmazingData「单点登录」天然契合；
2. prod 是 x86-64，`tgw` 有对应 `linux_py312_x64_package/libtgw_python312.so`；
3. 已有账号（AD_USERNAME / AD_PASSWORD / AD_HOST / AD_PORT）。

## 1. 约束与风险（贯穿所有阶段，review 必查）

### 1.1 平台约束：x86-64 only，本地 Apple Silicon 调不通

`tgw` wheel 只含 `win_py36~314_x64` 与 `linux_py36~314_x64` 预编译库，**无 ARM**。本机是 arm64 Mac，devcontainer 在本机是 arm64 Linux，**无法加载**。

- **开发/联调在 x86 环境做**：x86 VPS 或 x86 容器。本地 arm64 devcontainer 下门面必须**优雅降级**（import 失败 → 源不可用，job 空跑不炸），绝不让 import 错误冒到 scheduler。
- 可选提速：本机 `DOCKER_DEFAULT_PLATFORM=linux/amd64` 走 Rosetta 跑 x86 容器，但闭源 `.so` 在模拟层下稳定性未验证，**不作主路径**，仅作临时调试手段。
- collector 镜像构建需确保 x86（CI/prod 构建机为 x86 即可；arm 构建机须 `--platform linux/amd64`）。

### 1.2 单点登录：单例 + 互斥 + 重连

「同一时间只能有一个登录链接」，且重启时旧会话未释放干净会导致再次登录失败。

- 门面内**进程级单例**：懒加载 `ad.login()` 一次，全程复用；加登录互斥锁，防止 reload/并发重连时重复 login 互踢。
- **连接保活 + 断线重连**：检测到连接失效（取数抛连接类异常）时，退避后重登；重登失败不抛，按降级返回空。
- collector 单实例纪律不变（`--workers 1`、单进程），不新增第二个会 login 的进程。

### 1.3 闭源 SDK：不可审计，全靠降级兜底

`tgw` 是闭源 C++、`AmazingData` 核心全是 `.pyc`。出 bug 无法自查，只能等厂商。

- 所有调用包在与 `call_akshare` 等价的门面里：**限流闸 + 超时 + 退避重试 + 失败返回空 `[]` / `{"results": []}`**，任何异常不冒泡到 scheduler。
- 关键 job 保留**多源回退**（AmazingData 主 → akshare/findb/同花顺 兜），不单点依赖闭源通道。

### 1.4 授权与合规：仅个人使用，数据不出库

SDK 授权为「仅供个人使用」，不得「转移、出售、公开给任何第三人」。

- AmazingData 取到的数据**只进自己的 PostgreSQL、只喂自己的看板**，不得出现在任何对外/公开 API 或页面。
- 现阶段 data-api CORS `allow_origins=["*"]` 为公开行情，若混入 AmazingData 数据需评估越权风险；在 `docs/DATA-LAYER.md` 标注该源的个人使用边界。
- 账号密码走环境变量，**不进代码、不进仓库**；wheel 包也不入库（见 1.5）。

### 1.5 依赖分发：wheel 不入 git，构建期注入

`tgw` wheel 约 67MB、`AmazingData` 约 380KB。xysz 仓库是 AGPL，但 `tgw` 本身是**银河专有二进制**（METADATA `License: chinastock_tgw_sdk_python`），随项目分发的合规性不确定，故：

- wheel **不入 tradeck git**（避免二进制 blob + 专有再分发风险）。
- collector Dockerfile 在**构建期**从私有制品库/受控 URL 拉取 wheel 后 `pip install`；URL 走构建变量/密钥，不写死在 README。
- `.env.example` 登记 4 个变量（占位），wheel 获取方式在 `docs/DATA-LAYER.md` 说明。

## 2. 目标架构

```
AmazingData(tgw, x86, 单点登录)
        ▲ ad.login + 单例连接（门面内保活/重连/限流/降级）
        │
apps/data-collector  app/datasource/amazingdata_source.py   ← 唯一接触 SDK 的薄门面
        ▲ 各 job 经门面取数（主用官方源 / akshare 兜底），UPSERT 写库
        │
   PostgreSQL（现有表，不新增对外暴露面）
        ▲
   data-api（只读）→ web
```

设计要点：
- **唯一接触点**：全项目只有 `amazingdata_source.py` import `AmazingData`；jobs 只调门面函数，不直接碰 SDK（对齐 TickFlow/findb 门面模式）。
- **门面函数对齐现有约定**：返回扁平 `list[dict]` / `{"results": []}`，失败降级不抛；symbol 用项目规范 `.SH/.SZ/.BJ`（`.SS` 仅 yfinance 指数用），SDK 出向/入向各做一次映射。
- **复用现有表**：quotes→`quote_snapshots`、日K→`daily_prices`、财务→`income_statements`/`balance_sheets`/`cash_flow_statements`、公告→`announcements`、财报日历→`earnings_calendar`、板块→`board_heat`、资金流→`fund_flow`、市场宽度→`market_breadth`。**不新增对外 API 暴露面**（铁律）。

## 3. 阶段拆解

## 阶段 0：x86 环境冒烟验证（先做，阻塞后续）

**目标**：在 x86 环境证明「能装、能登录、能取到数、权限覆盖所需数据」。任一不过则中止集成，回退为「仅文档」。

**环境**：x86 VPS（或 x86 云主机/CI runner）+ `python:3.12-slim` 容器。

| 任务 | 内容 | 验收 |
|---|---|---|
| 0.1 装包 | 容器内 pip 装 `tgw==1.0.9.2`、`AmazingData==1.1.9`（cp312） | `python -c "import AmazingData"` 无 ImportError |
| 0.2 登录 | 用真实 AD_* 环境变量 `ad.login()` | 登录成功，无互踢报错 |
| 0.3 日K | `MarketData(calendar).query_kline([一只沪深A股], period=day, 近5日)` | 返回非空 DataFrame，字段含 OHLCV/amount |
| 0.4 快照 | `query_snapshot` 或 `SubscribeData` 取一只 A 股快照 | 返回 last/pre_close/bid/ask 等 Level-1 字段 |
| 0.5 权限面 | 各试一条：财务 `get_income`、公告 `get_announcement_stock_list`、行业 `get_industry_daily`、两融 `get_margin_summary` | 记录哪些可用/哪些报权限不足，回填到「验收记录」 |

**产出**：阶段 0 验收记录（可用接口清单 + 权限缺口 + 取数样例字段）。**这步过不了，后续阶段不启动。**

## 阶段 1：数据层门面 `amazingdata_source.py`

**目标**：封装出与现有门面同形态的薄 adapter，import 失败/登录失败/取数失败全降级，arm64 下不炸。

| 任务 | 内容 | 写范围 |
|---|---|---|
| 1.1 门面骨架 | 新建 `app/datasource/amazingdata_source.py`：懒加载单例、登录互斥锁、限流闸、超时、退避重连、失败返回空；import 用 try/except 包住，arm64 下 `AD_AVAILABLE=False` 优雅降级 | `apps/data-collector/app/datasource/amazingdata_source.py` |
| 1.2 行情两接口 | `get_daily_kline(symbol, count)`（query_kline day）、`get_quote(symbol)`（query_snapshot 当 snapshot 支持当日，否则用最近一根 K 近似）；symbol `.SH/.SZ/.BJ` ↔ SDK 出向映射 | 同上 |
| 1.3 环境变量 | `config.py` 加 `AD_USERNAME/AD_PASSWORD/AD_HOST/AD_PORT`（默认空串 → 源未配置即不可用，降级）；`.env.example` 登记占位 | `apps/data-collector/app/config.py`、`.env.example` |
| 1.4 Dockerfile 注入 | collector Dockerfile 构建期从受控 URL 拉 wheel + pip install（ARG/secret），本地无 URL 时跳过该源 | `apps/data-collector/Dockerfile` |

**验收标准**：
- arm64 本地：collector 正常启动、日志提示 AmazingData 源不可用、其余 job 不受影响（降级不炸）。
- x86：门面两接口对一只沪深 A 股取数成功，失败路径（错密码/断网）返回空且日志有 warning，无未捕获异常。
- review：单例+互斥+降级符合 1.2/1.3；`.env` 无真实密钥入库。

## 阶段 2：A 股实时报价兜底/主源切换

**目标**：消化「A 股报价兜底」backlog；akshare 被东财封时 A 股报价不断流。

| 任务 | 内容 | 写范围 |
|---|---|---|
| 2.1 报价接入 | `realtime_quotes.py` 的 A 股路径加入 AmazingData 回退：`call_akshare` 空/失败时回落 `amazingdata_source.get_quote`，UPSERT `quote_snapshots` | `apps/data-collector/app/jobs/realtime_quotes.py` |
| 2.2 主备可配 | 加配置开关（如 `CN_QUOTE_PRIMARY=hithink/akshare/amazingdata`），默认维持现状，AmazingData 仅兜底；主源切换留运维决策 | `app/config.py`、`realtime_quotes.py` |

**验收标准**：
- akshare 全失败（可临时断网模拟）时，A 股 tracked 标的报价仍写入 `quote_snapshots`，`last_price_time` 合理。
- 主源正常时 AmazingData 不被多余调用（限流闸计数/日志可证）。
- CN 涨跌榜/换手榜/个股报价页恢复（读库 <200ms）。

## 阶段 3：A 股深度数据迁移（akshare 痛点消化）

**目标**：把被东财封/格式失效的 akshare 直调迁到 AmazingData 官方源，逐项验收。**各项互相独立，可并行。**

| 任务 | 内容 | 写范围 |
|---|---|---|
| 3.1 财报日历 | `earnings_calendar` A 股路径：用业绩快报/预告（`get_profit_express`/`get_profit_notice`）或公告定期报告日，替代已失效的 `stock_yysj_em`；写 `earnings_calendar` | `jobs/earnings_calendar.py`、门面 |
| 3.2 公告 | `announcements` A 股路径：`get_announcement_stock_list`（明细）替换东财公告接口；写 `announcements` | `jobs/announcements.py`、门面 |
| 3.3 板块热度 | `board_heat`：行业指数日行情 `get_industry_daily` + 成分 `get_industry_constituent`，替代东财概念/行业板块 | `jobs/board_heat.py`、门面 |
| 3.4 市场宽度 | `market_breadth` A 股：快照涨跌统计替代乐咕接口 | `jobs/market_breadth.py`、门面 |
| 3.5 资金流 | `fund_flow`：评估 AmazingData 是否有对应字段（Level-1 无资金流，若无则保留 findb/akshare，本项降级为「不可迁」并回填结论） | `jobs/fund_flow.py`、门面 |

**验收标准**：
- 各项：对应表在 akshare 断连下仍有新鲜数据（`snapshot_date`/时间戳为当日）；UPSERT 幂等，重跑不产生重复/冲突。
- 3.5 若无数据源，明确记录「资金流留 findb/akshare」，不强行迁。
- review：每项失败仍降级回 akshare/findb（多源回退，不单点依赖闭源通道）。

## 阶段 4：交叉校验与文档回填

**目标**：日K 双源对账 + 长期文档沉淀。

| 任务 | 内容 | 写范围 |
|---|---|---|
| 4.1 日K 对账 | 抽查若干 tracked A 股，AmazingData 日K vs 同花顺/TickFlow 收盘/成交量偏差 < 阈值；记录复权口径差异（AmazingData 复权因子 vs 现有） | 校验脚本（plans 或 collector quality/） |
| 4.2 文档 | `docs/DATA-LAYER.md` 增「AmazingData（银河星耀数智）」源：覆盖范围、x86/单点登录/个人使用边界、wheel 获取方式、降级链 | `docs/DATA-LAYER.md` |
| 4.3 AGENTS/backlog | 更新 AGENTS.md 数据层/定时任务表；删除已消化的 backlog 行（A 股报价兜底、板块/资金流东财替代、A 股财报日历） | `AGENTS.md` |

**验收标准**：
- 日K 双源对账报告落档，偏差与复权口径差异有结论。
- DATA-LAYER.md 边界说明完整（x86、单点、个人使用、wheel 不入库）。
- backlog 已消化项删除，AGENTS.md 与代码一致。

## 4. 验收记录

> 逐阶段回填。记录：日期 / 环境（x86 主机） / 结果 / 遗留问题。

| 阶段 | 日期 | 环境 | 结果 | 遗留 |
|---|---|---|---|---|
| 0 冒烟 | 2026-09-03 | 本地 x86_64 Docker / Python 3.12 | 部分通过：SDK import、TCP、登录、A 股代码表（5555）成功；findb health/日K/1min/复权成功 | 按手册原样调用 `get_calendar`/`get_adj_factor` 时，服务端返回空并触发 SDK `TypeError`；行情查询阻塞，尚不能对拍日K/1min/复权。PDF 未定义试用权限或 PermissionCode 映射，需厂商核查账号授权、服务端状态及 SDK 版本兼容性 |
| 1 门面 | 2026-09-03 | 本地 x86_64 Docker / Python 3.12 | 已实现进程隔离门面：native SDK 仅在 spawn worker 内加载；超时/崩溃杀 worker，collector 主进程继续；代码表成功、行情权限失败降级已验 | 尚未接入业务 job；等待权限补齐 |
| 2 报价 | 未开始 | — | — | — |
| 3 深度数据 | 未开始 | — | — | — |
| 4 校验/文档 | 未开始 | — | — | — |

## 5. 待决策项（开工前需拍板）

1. **A 股报价定位**：2026-09-03 暂定维持现有 hithink/findb 主链，AmazingData 不接业务 job。当前环境只验证了代码表，无法证明行情/复权质量；厂商确认试用授权与 SDK 版本、接口恢复并完成逐值对拍后，再评估 AmazingData 主用、findb fallback。
2. **wheel 分发渠道**：受控 URL 放哪（私有制品库 / GHCR OCI artifact / VPS 固定路径）？需先有一个可拉取的位置才能做阶段 1.4。
3. **权限覆盖**：阶段 0.5 若财务/两融/行业报权限不足，对应阶段 3 子项降级为「保留 akshare/findb」。
