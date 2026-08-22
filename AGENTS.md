# AGENTS.md — tradeck 项目指南

> 供 AI 编码代理阅读。假设读者对本项目一无所知。
> 本文档基于仓库实际内容编写；另有 `CODEBUDDY.md`（开发规范）与 `docs/`（设计文档）可交叉参考。

## 项目概览

**tradeck** 是一个全球股票市场资讯看板（market dashboard），展示美股 / A 股 / 港股的行情、涨跌榜、新闻、宏观数据、基本面等。它是规划中三个独立项目里的「项目 1」，其数据层（OpenBB Platform）设计为可被后续项目复用。

核心设计：**前端不直连数据源**。backend 通过 APScheduler 定时从数据源拉数据写入 PostgreSQL，前端 Server Components 从 backend API 读库（毫秒级），实现页面秒开（直连数据源需 10-30s，读库 <200ms，详见 `docs/PIPELINE.md`）。

## 架构与数据流

```
数据源层（三源分工，详见 docs/DATA-LAYER.md）：
  TickFlow（官方 SDK）          ← 日K
  akshare（backend 直调）        ← A 股报价 + 深度数据
  OpenBB Platform (:6900)       ← 海外源（yfinance/sec/fred/oecd/federal_reserve，
                                  可分流韩国瘦节点，见 docs/OVERSEAS-NODE.md）
        ▲
        │ ① 定时拉取（APScheduler cron，全部 UTC 时区）
        │
backend (FastAPI, :8080) ──写入──▶ PostgreSQL 16 (:5432, 24 张表)
        ▲
        │ ② REST API（/api/*，从 DB 读，<50ms）
        │
web (Next.js, :3000)             ← Server Components 通过 backendFetch 读
```

4 个 docker service：`postgres`、`openbb`、`backend`、`web`，全部通过 docker compose 编排；CI 仅 `.github/workflows/openbb-images.yml` 构建发布 OpenBB 镜像到 GHCR（多架构 amd64+arm64），无部署流水线。

## 目录结构

```
tradeck/
├── .devcontainer/               ← 开发环境（强制使用，见下）
│   ├── devcontainer.json
│   ├── docker-compose.yml       ← dev 用 compose（dev + postgres + backend + openbb）
│   └── post-create.sh           ← 容器创建后装 Node/pnpm/Python(backend requirements)/前端依赖
├── apps/
│   ├── web/                     ← Next.js 前端（pnpm 包：tradeck-web）
│   │   ├── src/app/             ← App Router 页面：/（全球概览）/macro（宏观工作区）/markets/{cn,us,hk} /news /screener /stocks/[symbol]
│   │   ├── src/app/api/         ← Next API 路由（quotes/screener/historical，仅代理 backend）
│   │   ├── src/components/      ← 业务组件（看板/图表/导航）
│   │   ├── src/components/ui/   ← shadcn/ui 组件
│   │   ├── src/lib/openbb.ts    ← 数据访问层（全部走 backendFetch，勿直连 OpenBB）
│   │   └── src/lib/utils.ts     ← cn() 等工具
│   └── backend/                 ← FastAPI 后端（数据管道 + API 服务）
│       ├── app/api/             ← 18 个路由模块（quotes/historical/indices/movers/news/macro/profile/fundamentals/analyst/boards/fundflow/calendar/technicals/cn_extras/cross_asset/system/market_summary/search）
│       ├── app/jobs/            ← 22 个定时任务（daily_kline/realtime_quotes/indices/movers/news/macro/fundamentals/analyst_consensus/earnings_calendar/economic_calendar/announcements/research_reports/market_breadth/macro_assets/cleanup 等）
│       ├── app/main.py          ← FastAPI 入口 + lifespan（live 调度器 / mock 种子互斥）
│       ├── app/scheduler.py     ← APScheduler 任务注册
│       ├── app/db.py            ← asyncpg 连接池（min 2 / max 10）
│       ├── app/openbb_client.py ← OpenBB HTTP 客户端（失败降级返回空 results）
│       ├── app/markets.py       ← pick_provider / pick_market（按 symbol 后缀）+ to_yahoo_symbol（yfinance 出向映射）
│       ├── app/config.py        ← 环境变量（DATA_MODE / DATABASE_URL / OPENBB_API_URL / OVERSEAS 分流 / TICKFLOW_API_KEY）
│       ├── app/datasource/      ← 数据层薄门面（call_akshare 限流闸 / fetch_openbb / tickflow_source）
│       └── init.sql             ← 24 张表 DDL（postgres 容器首次启动自动执行）
├── docker/openbb/               ← OpenBB Platform Dockerfile + verify.sh + .env.example
├── docs/                        ← PIPELINE.md（管道架构）、DATA-LAYER.md（数据层特性）、OVERSEAS-NODE.md（海外节点）
├── docker-compose.yml           ← prod 用 compose（仅 prod 部署 + 部署前本地验证）
└── CODEBUDDY.md                 ← 开发规范（devcontainer 强制等）
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16.2.10（App Router + RSC）、React 19、TypeScript 5、Tailwind CSS v4、shadcn/ui（preset `b2fms620zo`：nova 风格 + mist 主题 + phosphor 图标）、recharts 3.8（preset 锁定；注意其 RadialBar stackId 只渲染首段的缺陷，堆叠环用 Pie 半环实现）、lightweight-charts 5（TradingView 开源 K 线库）、@tanstack/react-table、dnd-kit、framer-motion、zod 4 |
| 后端 | Python 3.12、FastAPI、uvicorn、asyncpg、APScheduler 3、httpx、pydantic 2 |
| 数据层 | OpenBB Platform（海外源，uvicorn 4 workers）+ backend 直调 akshare + TickFlow SDK（日K） |
| 数据库 | PostgreSQL 16-alpine |
| 包管理 | Node 24（`.nvmrc`）+ pnpm 9.15.0（锁死，pnpm 10+ 的 approve-builds 太严格） |
| 部署 | docker compose（VPS）；CI 仅构建 OpenBB 镜像（GHCR） |

## 开发环境（devcontainer，强制）

**所有开发在 devcontainer 内完成，不污染宿主机**。宿主机只需要 Docker + VS Code（Dev Containers 扩展）。

```bash
# 方式 1: VS Code 打开项目 → F1 → "Dev Containers: Reopen in Container"
# 方式 2: 命令行
devcontainer up --workspace-folder .
```

`post-create.sh` 自动安装：Node 24 + pnpm 9.15.0、Python 依赖（backend `requirements.txt`：akshare / yfinance / tickflow 等，OpenBB Platform 跑在独立容器，不在此安装）、`apps/web` 前端依赖。

规则（来自 `CODEBUDDY.md`）：
- ❌ 不要在宿主机跑 `pnpm install` / `pip install`
- ✅ 所有依赖装在 devcontainer 内
- 改了 backend `requirements.txt` → 在 backend 容器内重装依赖后重启生效

## 常用命令

### 前端（在 devcontainer 内，`apps/web/`）

```bash
pnpm dev        # 开发服务器 :3000（注意：用 next dev --webpack，非 Turbopack，见「已知坑」）
pnpm build      # 生产构建
pnpm lint       # ESLint（eslint-config-next core-web-vitals + typescript）
```

### 后端（在 devcontainer 内，`apps/backend/`）

```bash
# dev compose 已起 backend 服务（uvicorn --reload，映射到宿主机 8081）
# 手动跑（dev 容器内）：
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

默认 `DATA_MODE=live`：启动时 lifespan 会连 DB、起调度器，并**后台触发全部 job 跑一遍**（不阻塞 API 就绪，数据随后补齐，页面优雅降级）。

### 数据运行模式（live / mock 互斥）

dev 与 prod 均默认 `DATA_MODE=live`。live 模式只启动 scheduler 和真实数据 job，绝不执行 mock seed。数据库内有持久化 mode marker，data-api/collector 会在任何 seed/scheduler 前校验；marker 与 `DATA_MODE` 不一致时直接拒绝启动。需要纯模拟页面时，先用独立 Job 容器灌种子，再以 mock 模式重建 dev、postgres、data-api：

```bash
# ① 先灌 mock 种子（独立 Job 容器，跑完即退出；DATA_MODE=mock + 独立卷）
DATA_MODE=mock DEV_POSTGRES_VOLUME=tradeck-dev-postgres-mock-data \
  docker compose -f .devcontainer/docker-compose.yml --profile mock run --rm mock-seed
# ② 再以 mock 模式起开发环境
DATA_MODE=mock DEV_POSTGRES_VOLUME=tradeck-dev-postgres-mock-data \
  docker compose -f .devcontainer/docker-compose.yml up -d --force-recreate dev postgres data-api
```

mock 数据由 `mock-seed` Job 容器（`apps/mock`，一次性跑完 seed 即退出）写入；mock 模式的 data-api 只读库，同时关闭 scheduler、手动同步与读 API 的按需回源。live 沿用现有 dev 数据卷；mock 命令显式指定独立 PostgreSQL volume，两个模式不会共享存量数据。不能只修改 `DATA_MODE` 或卷名来绕过绑定：mock 连接 live 卷、live 连接 mock 卷都会 fail fast。切回 live 时也显式指定兼容旧环境的卷名，并同步重建三个服务：

```bash
DATA_MODE=live DEV_POSTGRES_VOLUME=tradeck_devcontainer_dev-postgres-data \
  docker compose -f .devcontainer/docker-compose.yml up -d --force-recreate dev postgres data-api
```

空数据库会绑定为当前 mode；已有业务数据但尚无 marker 的历史库只允许以 live 启动，并自动写入 live marker，因此升级不会丢失或改写现有数据。

需要重新灌 mock 数据时，重跑一次 mock-seed 容器即可（全部 UPSERT，幂等）：

```bash
DATA_MODE=mock DEV_POSTGRES_VOLUME=tradeck-dev-postgres-mock-data \
  docker compose -f .devcontainer/docker-compose.yml --profile mock run --rm mock-seed
```

`apps/mock/app/seed_mock.py` 在 `DATA_MODE!=mock` 时会直接拒绝执行。`DATA_MODE` 只接受 `live` / `mock`，其他值会令 data-api/collector 启动失败；prod 根 compose 未传该变量，按配置默认值保持 live。

### 数据层验证

```bash
bash docker/openbb/verify.sh   # OpenBB 侧检查：路由数/美股港股报价(yf)/财报/国债/Swagger
```

> A 股报价/深度数据已由 backend 经 `call_akshare` 直调 akshare（不再走自写 OpenBB provider）；日K 走 TickFlow。

### 服务入口

| 服务 | 地址 |
|---|---|
| 前端 | http://localhost:3000 |
| backend API（Swagger） | http://localhost:8080/docs（dev compose 映射为 8081） |
| OpenBB API（Swagger） | http://localhost:6900/docs |
| backend 健康检查 | http://localhost:8080/health |

### Prod 验证 / 部署

```bash
docker compose up -d --build   # 本地验证 prod 配置；VPS 上同命令部署
```

## 代码组织与约定

### UI 强制规则（shadcn 优先，违反一律打回）

> 任何涉及前端的任务，**开工前必须先读本节**；完成后按第 6 条检查清单验收。

**全站 UI 统一基于 shadcn preset `b2fms620zo`**（nova 风格 + mist 主题/底色 + phosphor 图标 + Roboto Slab / Public Sans 字体 + violet 图表色，`components.json` 与 `globals.css` 已按此配置）。`globals.css` 为 preset 标准结构：`:root`（mist 浅色）+ `.dark`（mist 深色），强制深色由 `layout.tsx` 的 `<html class="dark">` 开启；preset 之外的扩展仅有业务语义色（`--up`/`--down`/`--warn`）与存量别名（`--bg`/`--panel`/`--fg-dim` 等，均映射到 preset 令牌，新增颜色须走同一模式）。新环境初始化/重建用 `pnpm dlx shadcn@latest init --preset b2fms620zo --template next`；已有项目对齐 preset 用 `pnpm dlx shadcn@latest apply b2fms620zo`（会重写主题 CSS 并重装 ui 组件，执行前先提交本地改动；apply 后需检查业务扩展段是否仍完整）。禁止偏离 preset 更换风格、主题色、图标库或字体。

1. **一切 UI 元素优先使用 `src/components/ui/` 的 shadcn 组件**；官方目录（https://ui.shadcn.com/docs/components）里有但项目未装的组件（progress/empty/alert/scroll-area/accordion/spinner 等），**先 `pnpm dlx shadcn add X` 安装再使用，禁止手写 div 模拟**（进度条、Badge、空态、tooltip、tabs、卡片概莫能外）。
2. **图表必须经 `ui/chart`**（ChartContainer + ChartConfig + ChartTooltip/Legend），recharts 仅作渲染原语。豁免仅两处：`board-terrain.tsx`（Treemap 与 ChartConfig 不契合）、`tradingview-chart.tsx`（lightweight-charts K 线专用库）。新增豁免必须在本文件登记。
3. **空态统一**：`empty-state.tsx`（基于 `ui/empty` 的薄封装，phosphor 图标）是全站唯一空态入口，禁止再写「暂无数据」div。
4. **图标只用 `@phosphor-icons/react`**，禁止引入 lucide-react 等其他图标库。**Server Component 中必须从 `@phosphor-icons/react/dist/ssr` 导入**（主入口含 `createContext`，RSC 层执行会直接 500）；client 组件用主入口即可。
5. 颜色只用主题 CSS 变量（`var(--up)` 红涨 / `var(--down)` 绿跌等）；类名合并用 `cn()`；数据组件 Server Component、图表组件 `"use client"` 单独文件。
6. **提交前检查清单**（对改动文件逐个 grep，必须全绿）：
   - 裸元素：`<table`、`<button`、`<input`、`<select`、`<dialog`、`<progress`（ui/ 目录外应为 0）
   - 手搓痕迹：`title="`（悬浮提示）、`animate-spin`（除 refresh-button 已登记豁免）、「暂无」裸 div、`from "lucide-react"`
   - 图表：`from "recharts"` 的文件必须同文件出现 `ChartContainer`（豁免文件除外）

### 通用约定

- 注释、文档、commit message 用**中文**（如 `feat: 阶段 3 — 迁移所有剩余组件到 backend`）。
- 代码风格：Python 用 black（devcontainer 已配 formatOnSave）；TS/前端用 Prettier + ESLint（devcontainer 已配）。
- 各模块**优雅降级**：任何外部调用失败都返回空数据（`{"results": []}` / `[]`）而不是抛错，页面永远可渲染。

### 后端（apps/backend）

- **加一种新数据的完整链路**：`init.sql` 加表 → `app/jobs/` 加 job（拉 OpenBB + UPSERT 写库）→ `app/scheduler.py` 注册 cron → `app/api/` 加路由 → `app/main.py` `include_router` → 前端 `src/lib/openbb.ts` 加 `backendFetch` 函数。
- 路由返回**扁平数组**，不用 OpenBB 的 `{ results: [...] }` 包裹。
- **读 API 按需回源**（`app/api/_ensure.py`，per-key 锁防踩踏 + symbol 白名单）：profile/metrics/income/balance/cash/consensus/quotes 在 DB 无数据时经对应 job 函数现拉写库（首访 2-5s，此后读库）；报价仅美/港股回源（A 股 spot 为全市场接口，单标的回源太重，由 30 分钟 job 覆盖）。`/api/technicals` 对非 tracked 标的从 `daily_prices` 本地现算（复用 `compute_indicators`），不走外部源。
- 写库统一 `INSERT ... ON CONFLICT ... DO UPDATE`（UPSERT）；日期字符串用 `_parse_date()` 转成 `date` 对象（asyncpg 不接受字符串）。
- job 约定：log 打 `=== xxx job start/done: N rows ===`，返回写入条数。
- `markets.py` 的市场/provider 判定规则：symbol 以 `.SH/.SS/.SZ/.BJ` 结尾 → akshare + CN 市场（`.SH` 为沪市个股新标准；`.SS` 仅 yfinance 指数用）；`.HK` 结尾 → HK；其余 → yfinance + US。
- **symbol 规范与出向映射**：规范格式采中国数据商阵营（`.SH/.SZ/.BJ` + 港股 5 位补零 + 美股裸码，指数例外保留 `.SS`）；凡调 yfinance 必须经 `markets.to_yahoo_symbol()` 出向映射（`.SH`→`.SS`、港股 5 位→4 位），响应 symbol 映射回规范格式再写库。完整规则见 `docs/DATA-LAYER.md`「symbol 规范」；前端用户输入由 `lib/utils.ts` 的 `normalizeSymbol()` 归一（裸码补后缀/港股补零）。
- 配置只从环境变量读（`app/config.py`）：`DATA_MODE`（仅 `live` / `mock`）、`DATABASE_URL`、`OPENBB_API_URL`、`OPENBB_OVERSEAS_API_URL`、`OPENBB_OVERSEAS_TOKEN`、`TICKFLOW_API_KEY`。

定时任务（全部 UTC）：

| 任务 | Cron | 数据源 | 写表 |
|---|---|---|---|
| 日 K 线（TickFlow universe 全市场 ~2 万只：CN 5528 + HK 2841 + US 11645；100 只/片批量并发，分片失败隔离；首启按市场检查历史行数与最新交易日，缺失市场自动全量初始化 ~250 天，此后每日增量 5 天 UPSERT） | A/港 08:30、美股 21:30 每天 | TickFlow | daily_prices |
| 技术指标（本地计算，tracked 100 只） | 09:00 / 22:00 每天 | —（读 daily_prices） | technical_indicators |
| 实时报价 | 每 30 分钟 | yfinance/akshare | quote_snapshots |
| 指数历史（^GSPC ^IXIC ^DJI ^HSI ^HSCEI 000001.SS 399001.SZ 399006.SZ ^N225 ^STOXX50E ^VIX + GC=F CL=F SI=F HG=F BTC-USD，共 16 个符号） | 分市场盘后：CN 08:00、HK/JP 08:45、EU 18:00 UTC；US/VIX/商品纽约 17:30 | yfinance | index_prices |
| 宏观资产/收益率曲线（美元指数/离岸人民币/7 只 ETF + treasury_rates 11 期限） | 21:30 每天 | yfinance/federal_reserve | macro_asset_prices/yield_curve_rates |
| 涨跌榜 | 每 5 分钟 | yfinance | movers_cache |
| 新闻 | 每 30 分钟 | yfinance | news_articles |
| 宏观 | 06:00 每天 | oecd/federal_reserve | macro_indicators |
| 财报/公司信息/资产负债表/现金流量表 | 周一 07:00 | sec/yfinance | income_statements 等 5 表 |
| 分析师共识/目标价 | 21:00 每天 | yfinance | analyst_consensus |
| 财报日历（backend 直调 yfinance 库，美股/港股，A 股无源跳过） | 12:00 每天 | yfinance | earnings_calendar |
| 宏观数据日历（FRED→百度兜底，两源都允许失败） | 06:30 每天 | fred/akshare | economic_calendar |
| 板块行情热度（东财概念/行业板块，backend 直调 akshare） | 每 30 分钟 | akshare（不经 OpenBB，见注） | board_heat |
| A 股东财新闻（直调 akshare） | 每 30 分钟 | akshare | news_articles |
| 新闻情绪打分（L1 关键词，幂等） | 每 30 分钟 | —（本地规则） | news_articles.sentiment |
| 板块归属映射（东财成分股反解） | 周一 08:00 | akshare | symbol_board_map |
| 板块舆情聚合 | 每 30 分钟 | —（读库聚合） | board_sentiment |
| 个股资金流向榜（东财即时榜，直调 akshare，空结果不写库） | 每 5 分钟 | akshare | fund_flow |
| A 股公告（东财全市场公告过滤 tracked 30 只，直调 akshare；当天空则试前一自然日） | 10:30 每天 | akshare | announcements |
| A 股券商研报（30 只串行限速 0.5s，直调 akshare，只留近 90 天） | 周一 09:00 | akshare | research_reports |
| 市场宽度（乐咕涨跌家数快照，直调 akshare，UPSERT 当天行） | 每 30 分钟 | akshare | market_breadth |
| 市场宽度（US/HK，读 daily_prices 全市场计算，CROSS JOIN LATERAL 走索引） | 09:05 / 22:05 每天 | —（本地计算） | market_breadth |
| 数据清理（TTL） | 03:00 每天 | — | 各表 |

跟踪标的定义在 `app/jobs/daily_kline.py` 的 `TRACKED_SYMBOLS`（100 只：美股 60 + A 股 30 + 港股 10）。

注：**OpenBB REST API 只暴露标准模型**（quote/historical/index），板块/资金流等自定义模型 REST 不可用，backend 直接在 `requirements.txt` 装 akshare 调用，不经 OpenBB（自写 akshare provider 已退役删除）。同理，`/equity/calendar/earnings` 仅 fmp 付费源可用，财报日历 job 直调 yfinance 库（A 股财报日历无免费源：yfinance 无数据、akshare `stock_yysj_em` 因东财改格式解析失败，暂跳过）。

注 2：**榜单类表是「每日快照」模型**（movers_cache / fund_flow / board_heat / board_sentiment 均带 `snapshot_date`）：同日重跑只覆盖当天，历史日期保留 30 天（cleanup TTL）。所有榜单 API 支持 `?date=YYYY-MM-DD`（默认最近快照日），前端首页/热力图页有 DatePicker 快照回看（`?date=` URL 参数）。

### 前端（apps/web）

- 路径别名 `@/*` → `./src/*`。
- **数据访问只走 `src/lib/openbb.ts` 的 `backendFetch`**（管道迁移已完成，不要新增直连 OpenBB 的 `fetchJSON` 调用）；失败时返回空数组降级。
- 页面为 Server Component，板块用独立 `<Suspense>` + Skeleton 分块加载（参考 `src/app/page.tsx`）；首页按 `?market=global|us|cn|hk` 过滤。
- **取数约定**：Server Component 用 `lib/openbb.ts` 的 `backendFetch`（`BACKEND_API_URL` 指向 backend）；**Client Component 不能直连 backend**（浏览器侧 `process.env.BACKEND_API_URL` 为空、localhost:8080 不通容器网络），一律走 `src/app/api/` 的 Next 代理路由（如 `/api/quotes`、`/api/system/jobs`，参考 `stock-preview-dialog.tsx`、`data-sync-status.tsx`）。
- 首页顶部 `data-sync-status.tsx`（Client Component，5s 轮询 `/api/system/jobs`）：日K 全量初始化/每日更新进行中显示进度条，完成后显示一行完成提示。
- 样式：基于 preset mist 主题的深色模式（`<html class="dark">` 强制开启），令牌定义在 `src/app/globals.css`；**红涨绿跌**（A 股习惯，`--up: #f0556b` 红 / `--down: #20cd8d` 绿，preset 之外的业务扩展色），不要反过来。
- 组件用 shadcn/ui（preset `b2fms620zo`：nova 风格、mist 主题、phosphor 图标、CSS 变量模式，详见「UI 强制规则」）；类名合并用 `cn()`（`@/lib/utils`）。
- K 线蜡烛图用 lightweight-charts（`tradingview-chart.tsx`，TradingView 开源库，本地渲染无 CDN 依赖；曾因 s3.tradingview.com 不可达放弃官方 iframe widget）；个股预览弹窗为 shadcn Dialog（`stock-preview-dialog.tsx`，榜单行点击触发）。
- 环境变量：`BACKEND_API_URL`（默认 `http://localhost:8080`）；直连 OpenBB 的 `fetchJSON`/`OPENBB_API_URL` 已随管道迁移完成移除，`openbb.ts` 只走 backend。
- `next.config.ts` 有 `outputFileTracingRoot: "/workspace/apps/web"`（devcontainer 路径）和 `serverExternalPackages: ["undici"]`（绕开 Server Component 的 DNS 解析问题）——改动需谨慎。

### akshare 直调（backend 数据层门面）

- A 股报价与深度数据（板块/资金流/研报/公告/新闻/涨跌家数等）由 backend job 经 `app.datasource.call_akshare` 直调 akshare，统一走进程级 `Semaphore(4)` 限流闸 + 退避重试 + 节流；不再经 OpenBB 自写 provider（已退役）。
- 报价用 `ak.stock_zh_a_spot_em()`（一次全市场 spot → 本地按 tracked 代码过滤），港/美股报价走 yfinance（`fetch_openbb`）。
- 日K 走 TickFlow（`app.datasource.tickflow_source`）；指数历史仍走 OpenBB/yfinance；OpenBB 只留海外源（yfinance/fred/oecd 等，经韩国节点）。

## 数据库

PostgreSQL 16，24 张表，DDL 在 `apps/backend/init.sql`：`daily_prices`、`quote_snapshots`、`index_prices`、`movers_cache`、`news_articles`、`macro_indicators`、`income_statements`、`equity_profiles`、`fundamental_metrics`、`board_heat`、`symbol_board_map`、`board_sentiment`、`fund_flow`、`analyst_consensus`、`balance_sheets`、`cash_flow_statements`、`earnings_calendar`、`economic_calendar`、`technical_indicators`、`announcements`、`research_reports`、`market_breadth`、`macro_asset_prices`、`yield_curve_rates`（表结构见 init.sql）。

⚠️ `init.sql` 由 postgres 容器**首次启动**时执行（`docker-entrypoint-initdb.d`）。改表结构后，已存在的数据卷不会自动重跑——需手动执行 SQL 或删数据卷重建。

## 测试与验证

- **仓库目前没有自动化测试套件**（无 pytest/vitest/测试文件）；CI 仅构建 OpenBB 镜像（见「架构与数据流」），不跑测试。
- 验证手段：
  - `pnpm lint`（前端 ESLint）
  - `bash docker/openbb/verify.sh`（数据层 8 项冒烟检查）
  - backend `/health` + 各 `/api/*` 手测（Swagger: `:8080/docs`、`:6900/docs`）
  - 部署前本地 `docker compose up -d --build` 跑通 prod 配置自我验证
- 改代码后按上述手段自查；若引入了测试框架，请同步更新本节。

## 部署

- 项目根 `docker-compose.yml` **只用于 prod 部署和部署前本地验证**，开发不要用根 compose。
- VPS 部署：`docker compose -f docker-compose.yml up -d --build`。
- prod compose 服务依赖链：postgres/openbb 健康检查通过 → backend 启动 → web 启动。

## 安全注意事项

- `.env` 被 gitignore，**不要提交任何 API key**。OpenBB 付费源的 key 模板见 `docker/openbb/.env.example`（FMP/FRED/FINNHUB/POLYGON/TIINGO/ALPHAVANTAGE），全部可选——免费源（yfinance/sec/federal_reserve/oecd 等）不需要 key。
- compose 里的 PostgreSQL 账号密码（`tradeck`/`tradeck_dev`）是**开发专用默认值**，真实生产部署需更换。
- backend CORS 当前 `allow_origins=["*"]`，所有 API 无鉴权——现阶段都是公开行情数据，可接受；若将来加用户数据需收紧。
- 不要在代码里硬编码任何密钥；新增密钥走环境变量并登记到 `.env.example`。

## 已知坑（改动前必读）

1. **`openbb-cftc` 会导致 OpenBB 启动崩溃**——`docker/openbb/Dockerfile` 里已 `pip uninstall openbb-cftc`，不要装回去。
2. **`openbb-api` 命令不支持 `--workers`**——OpenBB 用 `uvicorn openbb_platform_api.main:app --workers 4` 直接启动。
3. **Docker bind mount 下文件监听不稳定**：前端 dev 必须用 `next dev --webpack`（非 Turbopack）+ `WATCHPACK_POLLING=true` / `CHOKIDAR_USEPOLLING=true`（Dockerfile / dev compose 已配）。
4. **pnpm 锁死 9.15.0**（10+ 的 approve-builds 机制太严格）。
5. **数据源限流/封锁**：本地环境 yfinance 常被限流（profile/metrics 可能为空）、akshare 被东方财富断连/封 IP（板块热度、A 股报价 spot、资金流等 akshare 直调数据可能为空；日K 走 TickFlow 不受影响）——属已知限制，不是代码 bug，VPS 上需另行验证。
6. **backend `uvicorn --reload` 对 bind mount 文件变更不一定触发**（macOS 宿主机 ↔ 容器 bind mount 下 watchfiles 可能漏事件；改完 backend 代码没生效时 `docker restart tradeck-dev-backend`）。
7. **APScheduler 定时任务必须传 `async def` 协程函数**——传返回协程的 lambda 不会被 await（任务静默不执行）；带参数的 job 用模块级 `async def` 包装（参考 `scheduler.py` 的 `_daily_kline_cn_hk`）。
8. **backend 必须单进程运行**——APScheduler 嵌在 FastAPI 进程内，多 worker 会把所有定时 job 跑 N 遍；progress 注册表也是进程内存。`apps/backend/Dockerfile` CMD 为 `--workers 1`，不要调大。

## 待优化项（backlog）

> 已分析定案、待实施的事项；做完一项删一行。

- [ ] **A 股报价兜底（纯数据层）**：`realtime_quotes` akshare 失败时从 `daily_prices` 最近两根日K 回填 `quote_snapshots`（延迟一天，东财实时优先）。恢复 CN 涨跌榜（预定义列表排序版）/换手榜/涨跌平 donut/个股报价。
- [ ] **板块热度/资金流的东财替代**（CVM 部署后实测 `stock_zh_a_spot_em`；被封则：降速/改 UA 自写慢分页 → 代理出口 → 接受缺失）。
- [ ] **CN 指数迁 TickFlow（可选 P3）**：`000001.SH`/`399006.SZ` 等（免费档实测可用），减少 yfinance 依赖；存量 `.SS` 数据处理需先决策。
- [ ] **个股页市值货币符号**：`fmtBigNumber` 硬编码 `$`，CNY/HKD 资产应按 currency 显示（cosmetic）。

## 相关文档

- `CODEBUDDY.md` — 开发规范（devcontainer 强制、prod compose 用途）
- `docs/PIPELINE.md` — 数据管道架构（拓扑、24 表存储、定时任务、API 端点、live/mock 模式）
- `docs/DATA-LAYER.md` — 数据层特性（三源分工、薄门面限流降级、symbol 规范、调度错峰）
- `docs/OVERSEAS-NODE.md` — 海外节点部署（韩国瘦 OpenBB、token、分流/回滚/排查）
- `docs/DATA-SERVICE.md` — 数据服务拆分技术方案（三条铁律、分层、容量、对外接口）
- `docs/TASKS-DATA-SERVICE.md` — 拆分任务拆解与验收记录（进行中项目，含 review 门禁）
