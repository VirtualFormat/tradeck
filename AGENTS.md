# AGENTS.md — tradeck 项目指南

> 供 AI 编码代理阅读。假设读者对本项目一无所知。
> 本文档基于仓库实际内容编写；另有 `CODEBUDDY.md`（开发规范）与 `docs/`（设计文档）可交叉参考。

## 项目概览

**tradeck** 是一个全球股票市场资讯看板（market dashboard），展示美股 / A 股 / 港股的行情、涨跌榜、新闻、宏观数据、基本面等。它是规划中三个独立项目里的「项目 1」，其数据层（OpenBB Platform）设计为可被后续项目复用。

核心设计：**前端不直连数据源**。backend 通过 APScheduler 定时从 OpenBB 拉数据写入 PostgreSQL，前端 Server Components 从 backend API 读库（毫秒级），实现页面秒开（改造前直连 OpenBB 需 10-30s，改造后 <200ms，详见 `docs/PIPELINE-MIGRATION-COMPLETE.md`）。

## 架构与数据流

```
OpenBB Platform (:6900)          ← 数据源层（yfinance / akshare / sec / oecd / federal_reserve）
    ▲
    │ ① 定时拉取（APScheduler cron，全部 UTC 时区）
    │
backend (FastAPI, :8080) ──写入──▶ PostgreSQL 16 (:5432, 24 张表)
    ▲
    │ ② REST API（/api/*，从 DB 读，<50ms）
    │
web (Next.js, :3000)             ← Server Components 通过 backendFetch 读
```

4 个 docker service：`postgres`、`openbb`、`backend`、`web`。全部通过 docker compose 编排，无 Kubernetes、无 CI/CD 配置。

## 目录结构

```
tradeck/
├── .devcontainer/               ← 开发环境（强制使用，见下）
│   ├── devcontainer.json
│   ├── docker-compose.yml       ← dev 用 compose（dev + postgres + backend + openbb）
│   └── post-create.sh           ← 容器创建后装 Node/pnpm/OpenBB/前端依赖
├── apps/
│   ├── web/                     ← Next.js 前端（pnpm 包：tradeck-web）
│   │   ├── src/app/             ← App Router 页面：/（全球概览）/global（全球宏观）/markets/{cn,us,hk} /macro /news /screener /stocks/[symbol]
│   │   ├── src/app/api/         ← Next API 路由（quotes/screener，仅代理 backend）
│   │   ├── src/components/      ← 业务组件（看板/图表/导航）
│   │   ├── src/components/ui/   ← shadcn/ui 组件
│   │   ├── src/lib/openbb.ts    ← 数据访问层（全部走 backendFetch，勿直连 OpenBB）
│   │   └── src/lib/utils.ts     ← cn() 等工具
│   └── backend/                 ← FastAPI 后端（数据管道 + API 服务）
│       ├── app/api/             ← 16 个路由模块（quotes/historical/indices/movers/news/macro/profile/fundamentals/analyst/sentiment/boards/fundflow/calendar/technicals/cn_extras/cross_asset）
│       ├── app/jobs/            ← 22 个定时任务（daily_kline/realtime_quotes/indices/movers/news/macro/fundamentals/analyst_consensus/earnings_calendar/economic_calendar/announcements/research_reports/market_breadth/macro_assets/cleanup 等）
│       ├── app/main.py          ← FastAPI 入口 + lifespan（连 DB、起调度器）
│       ├── app/scheduler.py     ← APScheduler 任务注册
│       ├── app/db.py            ← asyncpg 连接池（min 2 / max 10）
│       ├── app/openbb_client.py ← OpenBB HTTP 客户端（失败降级返回空 results）
│       ├── app/markets.py       ← pick_provider / pick_market（按 symbol 后缀）
│       ├── app/config.py        ← 环境变量（DATABASE_URL / OPENBB_API_URL）
│       └── init.sql             ← 24 张表 DDL（postgres 容器首次启动自动执行）
├── packages/
│   └── openbb-akshare-provider/ ← 自写 OpenBB Provider 扩展（A 股深度数据，poetry 包）
├── docker/openbb/               ← OpenBB Platform Dockerfile + verify.sh + .env.example
├── docs/                        ← TECH-PLAN.md（活文档）、PIPELINE-DESIGN.md、PIPELINE-MIGRATION-COMPLETE.md
├── docker-compose.yml           ← prod 用 compose（仅 prod 部署 + 部署前本地验证）
└── CODEBUDDY.md                 ← 开发规范（devcontainer 强制等）
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16.2.10（App Router + RSC）、React 19、TypeScript 5、Tailwind CSS v4、shadcn/ui（preset `b2fms620zo`：nova 风格 + mist 主题 + phosphor 图标）、recharts 3.8（preset 锁定；注意其 RadialBar stackId 只渲染首段的缺陷，堆叠环用 Pie 半环实现）、lightweight-charts 5（TradingView 开源 K 线库）、@tanstack/react-table、dnd-kit、framer-motion、zod 4 |
| 后端 | Python 3.12、FastAPI、uvicorn、asyncpg、APScheduler 3、httpx、pydantic 2 |
| 数据层 | OpenBB Platform（pip 安装，FastAPI via uvicorn，4 workers）+ 自写 akshare provider（akshare>=1.12, openbb-core>=1.6.10） |
| 数据库 | PostgreSQL 16-alpine |
| 包管理 | Node 24（`.nvmrc`）+ pnpm 9.15.0（锁死，pnpm 10+ 的 approve-builds 太严格） |
| 部署 | docker compose（VPS），无 CI/CD |

## 开发环境（devcontainer，强制）

**所有开发在 devcontainer 内完成，不污染宿主机**。宿主机只需要 Docker + VS Code（Dev Containers 扩展）。

```bash
# 方式 1: VS Code 打开项目 → F1 → "Dev Containers: Reopen in Container"
# 方式 2: 命令行
devcontainer up --workspace-folder .
```

`post-create.sh` 自动安装：Node 24 + pnpm 9.15.0、Python 依赖（openbb + akshare + 本地 provider + `openbb-build`）、`apps/web` 前端依赖。

规则（来自 `CODEBUDDY.md`）：
- ❌ 不要在宿主机跑 `pnpm install` / `pip install`
- ✅ 所有依赖装在 devcontainer 内
- 改了 `packages/openbb-akshare-provider` → 需重装 + `openbb-build` + 重启 openbb 容器才生效

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

启动时 lifespan 会连 DB、起调度器，并**后台触发全部 job 跑一遍**（不阻塞 API 就绪，数据随后补齐，页面优雅降级）。

### 假数据种子（dev 专用）

本地数据源被限流/封锁（yfinance 限流、东财封 IP）时，填充逼真假数据看页面效果：

```bash
docker exec tradeck-dev-backend python -m app.seed_mock
```

`app/seed_mock.py` 覆盖 20 张表（UPSERT，可重复执行）；真数据到达后会被正常 job 覆盖。**勿在 prod 执行**。

### OpenBB Provider（`packages/openbb-akshare-provider/`）

```bash
pip install -e packages/openbb-akshare-provider
openbb-build                 # 重建静态资产，注册 provider，必做
```

### 数据层验证

```bash
bash docker/openbb/verify.sh   # 8 项检查：路由数/provider 数/美股 A 股港股报价/财报/国债/Swagger
```

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
- 写库统一 `INSERT ... ON CONFLICT ... DO UPDATE`（UPSERT）；日期字符串用 `_parse_date()` 转成 `date` 对象（asyncpg 不接受字符串）。
- job 约定：log 打 `=== xxx job start/done: N rows ===`，返回写入条数。
- `markets.py` 的市场/provider 判定规则：symbol 以 `.SS/.SZ/.BJ` 结尾 → akshare + CN 市场；`.HK` 结尾 → HK；其余 → yfinance + US。
- 配置只从环境变量读（`app/config.py`）：`DATABASE_URL`、`OPENBB_API_URL`。

定时任务（全部 UTC）：

| 任务 | Cron | 数据源 | 写表 |
|---|---|---|---|
| 日 K 线（美股/A 股） | 16:00 / 08:00 每天 | yfinance/akshare | daily_prices |
| 实时报价 | 每 30 分钟 | yfinance/akshare | quote_snapshots |
| 指数历史（^GSPC ^IXIC ^DJI ^HSI ^HSCEI 000001.SS 399001.SZ 399006.SZ ^N225 ^STOXX50E ^VIX + GC=F CL=F SI=F HG=F BTC-USD，共 16 个符号） | 17:00 每天 | yfinance | index_prices |
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
| 数据清理（TTL） | 03:00 每天 | — | 各表 |

跟踪标的定义在 `app/jobs/daily_kline.py` 的 `TRACKED_SYMBOLS`（100 只：美股 60 + A 股 30 + 港股 10）。

注：**OpenBB REST API 只暴露标准模型**（quote/historical/index），akshare provider 里的自定义模型（ConceptBoards/NorthFlow/MarginTrading/DragonTigerList）只有 Python SDK 能用。backend 需要这类数据时（如板块热度 job）在 `requirements.txt` 装了 akshare 直接调用，不经 OpenBB。同理，`/equity/calendar/earnings` 仅 fmp 付费源可用，财报日历 job 直调 yfinance 库（A 股财报日历无免费源：yfinance 无数据、akshare `stock_yysj_em` 因东财改格式解析失败，暂跳过）。

注 2：**榜单类表是「每日快照」模型**（movers_cache / fund_flow / board_heat / board_sentiment 均带 `snapshot_date`）：同日重跑只覆盖当天，历史日期保留 30 天（cleanup TTL）。所有榜单 API 支持 `?date=YYYY-MM-DD`（默认最近快照日），前端首页/热力图页有 DatePicker 快照回看（`?date=` URL 参数）。

### 前端（apps/web）

- 路径别名 `@/*` → `./src/*`。
- **数据访问只走 `src/lib/openbb.ts` 的 `backendFetch`**（管道迁移已完成，不要新增直连 OpenBB 的 `fetchJSON` 调用）；失败时返回空数组降级。
- 页面为 Server Component，板块用独立 `<Suspense>` + Skeleton 分块加载（参考 `src/app/page.tsx`）；首页按 `?market=global|us|cn|hk` 过滤。
- 样式：基于 preset mist 主题的深色模式（`<html class="dark">` 强制开启），令牌定义在 `src/app/globals.css`；**红涨绿跌**（A 股习惯，`--up: #f0556b` 红 / `--down: #20cd8d` 绿，preset 之外的业务扩展色），不要反过来。
- 组件用 shadcn/ui（preset `b2fms620zo`：nova 风格、mist 主题、phosphor 图标、CSS 变量模式，详见「UI 强制规则」）；类名合并用 `cn()`（`@/lib/utils`）。
- K 线蜡烛图用 lightweight-charts（`tradingview-chart.tsx`，TradingView 开源库，本地渲染无 CDN 依赖；曾因 s3.tradingview.com 不可达放弃官方 iframe widget）；个股预览弹窗为 shadcn Dialog（`stock-preview-dialog.tsx`，榜单行点击触发）。
- 环境变量：`BACKEND_API_URL`（默认 `http://localhost:8080`）；`OPENBB_API_URL` 保留给个别未迁移场景。
- `next.config.ts` 有 `outputFileTracingRoot: "/workspace/apps/web"`（devcontainer 路径）和 `serverExternalPackages: ["undici"]`（绕开 Server Component 的 DNS 解析问题）——改动需谨慎。

### OpenBB Provider（packages/openbb-akshare-provider）

- 标准三件套模式：每个数据类型一个文件，`XxxQueryParams`（继承 OpenBB 标准模型）+ `XxxData`（`__alias_dict__` 映射 akshare 中文列名）+ `XxxFetcher`（`transform_query` / `aextract_data` / `transform_data`）。
- 在 `openbb_akshare_provider/__init__.py` 的 `fetcher_dict` 注册，靠 poetry 插件入口 `openbb_provider_extension` 被 OpenBB 发现。
- 已实现：EquityQuote、EquityHistorical、IndexHistorical、NorthFlow、MarginTrading、DragonTigerList、ConceptBoards。
- **改完必须** `pip install -e . && openbb-build` 并重启 openbb 容器，否则不生效。

## 数据库

PostgreSQL 16，24 张表，DDL 在 `apps/backend/init.sql`：`daily_prices`、`quote_snapshots`、`index_prices`、`movers_cache`、`news_articles`、`macro_indicators`、`income_statements`、`equity_profiles`、`fundamental_metrics`、`board_heat`、`symbol_board_map`、`board_sentiment`、`fund_flow`、`analyst_consensus`、`balance_sheets`、`cash_flow_statements`、`earnings_calendar`、`economic_calendar`、`technical_indicators`、`announcements`、`research_reports`、`market_breadth`、`macro_asset_prices`、`yield_curve_rates`（表结构见 init.sql 或 `docs/PIPELINE-MIGRATION-COMPLETE.md`）。

⚠️ `init.sql` 由 postgres 容器**首次启动**时执行（`docker-entrypoint-initdb.d`）。改表结构后，已存在的数据卷不会自动重跑——需手动执行 SQL 或删数据卷重建。

## 测试与验证

- **仓库目前没有自动化测试套件**（无 pytest/vitest/测试文件），也没有 CI。
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
5. **数据源限流/封锁**：本地环境 yfinance 常被限流（profile/metrics/news 可能为空）、akshare 被东方财富封 IP（A 股日 K 线可能为空）——属已知限制，不是代码 bug，VPS 上需另行验证。
6. **`scheduler.py` 里「实时报价」注释写「每 30 秒」，实际 cron 是每 30 分钟**——以 cron 为准。
7. OpenBB 的 news 端点只支持 benzinga/fmp/intrinio/tiingo（需 key），yfinance 不支持 news。

## 相关文档

- `CODEBUDDY.md` — 开发规范（devcontainer 强制、prod compose 用途）
- `docs/TECH-PLAN.md` — 三项目规划 + 任务拆解（活文档）
- `docs/PIPELINE-DESIGN.md` — 数据管道设计
- `docs/PIPELINE-MIGRATION-COMPLETE.md` — 管道迁移完成文档（DB schema、API 端点、性能数据，最实用的参考）
