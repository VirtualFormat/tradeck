# Tradeck — 架构设计方案（Serverless 版）

> 目标：小团队内部共享的市场数据仪表盘（深色专业终端风，参考 Claude Fable 5 / Mirofish）。
> 务实优先，明确标注「必须 / 可砍 / 可延后」。
> **本版为 serverless 重构定稿（2026-07-01）**，取代此前的 NestJS 常驻后端方案。

---

## 0. 一句话结论

定位收敛为**纯市场行情信息展示**（非量化、不要秒级、无历史持久化需求），架构随之大幅简化为 **Serverless / 边缘**：

- **前端**：React 18 + TS + Vite，部署到 **Cloudflare Pages**。
- **后端**：**Cloudflare Workers + Hono**，一组轻量 API 函数，**代理拉取 + 归一化** Yahoo Finance / RSS。
- **刷新节奏**：前端定时器驱动（`setInterval` 轮询自家 API），**非** SSE 推送。
- **"统一拉一次、多人共享"**：用**边缘缓存**（`Cache-Control: s-maxage`，或 Cron Triggers + KV）替代原 Redis 快照。
- **无数据库**：当前阶段不落库；历史面板（若做）由前端临时调 API 现拉 Yahoo。

### 相比旧方案砍掉的东西
| 旧组件 | 处置 | 原因 |
|---|---|---|
| NestJS 常驻进程 | ❌ 砍 | serverless 无常驻进程，请求驱动 |
| SSE 实时网关 + 订阅 hub | ❌ 砍 | 不要秒级；前端定时轮询足够，函数有执行时长限制不适合长连接 |
| 后台 `setInterval` 轮询 | ❌ 砍 | serverless 函数不常驻；改前端定时触发 + 边缘缓存 |
| PostgreSQL + Drizzle | ❌ 砍 | 纯展示无持久化需求；历史临时查 Yahoo |
| Redis（快照/扇出/限流） | ❌ 砍 | 单边缘函数 + 边缘缓存即可；非分布式系统 |
| Docker Compose 单机部署 | ❌ 砍 | 改 Cloudflare Pages + Workers 平台部署 |
| Binance 公开 WS（Push 源） | ⏸ 延后 | WS 长连接不适合 serverless；加密行情也可用 Yahoo 轮询拿到 |
| 写库节流 / 高频 tick 聚合 | ❌ 砍 | 无高频 tick、无落库 |
| Socket.IO / Kafka / 微服务 / K8s | ❌ 砍 | 旧方案已砍，继续砍 |

### 保留并复用的东西
- ✅ **shared 标准数据模型**（`MarketTick / OHLCV / FeedItem / GenericMetric`）。
- ✅ **Connector 的 `normalize()` 归一化抽象**——纯函数，搬进 Worker 里照用（采集模式只剩 Pull 型）。
- ✅ 前端可视化选型（Lightweight-Charts / ECharts / Tailwind+shadcn / react-grid-layout）。
- ✅ 分阶段实施思想（MVP → 可配 → 扩展）。

---

## 1. ⚠️ 核心约束：前端**不能**直接拉 Yahoo / RSS（CORS）

这是整个 serverless 方案成立的前提，务必理解：

- **浏览器跨域安全模型（CORS）**：Yahoo Finance 非官方接口、各 RSS 源都**不返回** `Access-Control-Allow-Origin` 头，浏览器 `fetch` 直连会被**直接拦截**，绕不过去（除非源主动允许跨域，而它们都不允许）。
- RSS 还返回 **XML**，前端需额外解析。

### 正确数据流：前端轮询的是**自家 API 函数**，函数去拉外网

```
浏览器 (setInterval 定时 fetch, 如每 15~30s)
   │  同源请求，无 CORS 问题
   ▼
你的 Cloudflare Worker API (Hono 路由)
   │  服务端发请求，不受 CORS 限制
   ├─→ 拉 Yahoo Finance（quote / chart 端点）
   ├─→ 拉 RSS（XML → 解析）
   ├─→ normalize() 归一化为 shared 标准模型
   ├─→ 加边缘缓存头 Cache-Control: s-maxage=30
   ▼
返回 JSON → 前端渲染
```

**关键点**：前端只负责"定时触发刷新"这个**节奏**；真正的外网请求发生在 **Worker 内部**。Worker 在这里是**轻量代理 + 归一化层**。

---

## 2. 技术栈定档（Serverless）

### 2.1 前端（Cloudflare Pages）
| 项 | 决策 | 说明 |
|---|---|---|
| React 18 + TS + Vite | ✅ | 标准组合，构建产物为静态站，部署 Pages |
| TanStack Query | ✅ 必须 | 负责轮询自家 API、缓存、重试、失效；用 `refetchInterval` 实现定时刷新 |
| Zustand | ➖ 可选 | 旧方案用它管 SSE 实时流；现无推送流，**轮询数据交给 TanStack Query 即可**，Zustand 仅在需要纯前端 UI 状态时用 |
| TradingView Lightweight-Charts | ✅(K线) | 历史/走势图（历史面板做时用） |
| ECharts (+echarts-gl) | ➕ 按需 | 热力图/关系图/3D，阶段二三再上 |
| Tailwind + shadcn/ui | ✅ | 深色终端风 design token |
| react-grid-layout | ➕ 必须 | 可拖拽仪表盘网格（布局配置当前固定，将来可存 localStorage） |

> **职责切分调整**：旧铁律「TanStack Query 管请求数据 / Zustand 管推送数据」中，**推送数据这一路已取消**。现在所有数据都是"请求来的"，统一由 **TanStack Query** 管（用 `refetchInterval` 周期刷新）。Zustand 降级为可选的纯 UI 状态工具。

### 2.2 后端（Cloudflare Workers + Hono）
- **Hono**：轻量、Cloudflare 原生支持的 Web 框架，写 API 路由。
- 一组**无状态 API 函数**：`/api/quote`、`/api/chart`、`/api/feed` 等，请求驱动、现拉现返。
- **Wrangler**：本地开发 + 部署 CLI。
- 归一化逻辑（`normalize()`）从 shared 复用，纯函数。

### 2.3 数据层（无 DB）
- **当前阶段：无持久化**。行情/资讯都是现拉现返。
- **共享与限流**：靠**边缘缓存**——
  - 简易：响应头 `Cache-Control: s-maxage=N`，Cloudflare 边缘自动缓存，多人同时看只穿透 Yahoo 一次。
  - 进阶（可选）：**Cron Triggers** 定时（如每 30s）拉 Yahoo 写入 **KV**，前端读 KV——把"后台轮询"用 serverless 方式实现，进一步削减对源的请求。MVP 可先不用，用 `s-maxage` 足够。
- **历史面板（若做）**：前端临时调 `/api/chart` → Worker 现拉 Yahoo chart 端点返回，不缓存或短缓存即可。

### 2.4 实时传输
- **无**。不要秒级，前端定时轮询（TanStack Query `refetchInterval`）即可。realtime/SSE 整模块取消。

### 2.5 部署与开发
- **部署**：**Cloudflare Pages**（前端静态站）+ **Cloudflare Workers**（API），经 `wrangler deploy` / Pages 构建。砍掉：**部署用的** Docker Compose、自托管常驻服务、K8s。
- **本地开发**：仍在 **Dev Container** 内进行（不污染 WSL 裸机——用户硬诉求），容器内跑 `wrangler dev`（Worker）+ `vite dev`（前端）。开发容器从旧的多服务 compose 简化为**单个 node+pnpm+wrangler 容器**（serverless 无 DB/Redis，不需要 pg/redis service）。详见 CODEBUDDY.md「容器内开发铁律」。

---

## 3. 数据源接入（简化版 Connector）

### 3.1 仍用统一归一化契约
所有源经 `normalize()` 输出 shared 标准模型，便于将来加源/换源不动前端：
- `MarketTick` { source, symbol, ts, price, volume, ... }
- `OHLCV` { source, symbol, interval, ts, o,h,l,c,v }
- `FeedItem` { source, id, title, url, summary, publishedAt, tags }
- `GenericMetric` { source, key, ts, value, meta }（自定义 HTTP 源兜底）

### 3.2 采集模式只剩 Pull 型
serverless 下不再有 Push(WS) 型。每个源 = 一个 `fetchOnce()` + `normalize()` 纯逻辑，由 Worker 路由按请求调用：
- **Yahoo Finance**（主源）：quote（最新报价）、chart（历史 K 线）。注意是非官方端点，可能变动，封装在一处便于维护。
- **Mock**（兜底/开发）：本地假数据，断网/源挂时仍能跑通前端。
- **RSS**（资讯流）：拉 XML → 解析 → `FeedItem`。占位源：新浪财经 `https://rss.sina.com.cn/roll/finance/hot_roll.xml`，可随时换。

### 3.3 自定义 HTTP 源（延后）
`http-json` 通用源 + JSONPath 映射，免代码接新源 → 阶段二再做（serverless 下表现为一个带配置参数的通用 Worker 路由）。

---

## 4. 配置与登录（当前固定，留口）

- **登录**：当前**不做**。架构留口——将来做用户注册/登录，**继续沿用 serverless**（用 Cloudflare Access、或 Worker + KV/D1 存账号、或第三方 Auth）。
- **关注的标的列表 / 看板布局**：当前**写死/固定**（代码内常量或前端配置文件）。
  - 将来个性化时的 serverless 选项：前端 `localStorage`（最轻）→ Cloudflare **KV / D1**（需跨设备共享时）。
- 原则：**任何后续持久化都用 serverless 友好的存储（KV / D1 / R2），不引入常驻 DB**。

---

## 5. 指标卡片 / 告警（阶段二，serverless 形态）

- **指标卡片** = 前端组件，定时轮询 `/api/quote` 渲染当前值 + 涨跌幅。
- **阈值告警**（阶段二）：纯展示场景下，最简做法是**前端在轮询到的数据上做阈值判断 + UI 标红/Toast**，无需后端告警引擎、无需持久化规则（规则可先固定/存 localStorage）。
- 需要服务端告警/通知再说，仍走 serverless（Cron Trigger 评估 + Webhook）。

---

## 6. 资讯文章模块

- **聚合 RSS**：Worker `/api/feed` 拉 RSS → 解析 → `FeedItem` → 加缓存返回。前端信息流分页/滚动展示，按时间/来源过滤（前端做）。
- **自建文章**：当前不做。将来要做用 serverless 存储（KV/D1/R2）+ 前端 Markdown 编辑器。

---

## 7. 项目目录结构（pnpm monorepo）

理由：前后端共享 TS 类型（标准模型）+ 共享 `normalize()` 纯逻辑，避免类型漂移。

```
tradeck/
├─ pnpm-workspace.yaml
├─ packages/
│  ├─ shared/                 # 标准数据模型、DTO、zod schema、normalize 纯函数、常量
│  ├─ web/                    # 前端 (React + Vite) → Cloudflare Pages
│  │  └─ src/
│  │     ├─ app/              # 路由、布局、provider
│  │     ├─ features/         # dashboard / charts / feed / sources
│  │     ├─ components/       # shadcn/ui 封装 + 通用组件
│  │     ├─ charts/           # lightweight-charts & echarts 封装
│  │     ├─ api/              # tanstack query hooks（refetchInterval 轮询）+ http client
│  │     └─ styles/           # tailwind + 深色 token
│  └─ api/                    # 后端 (Hono on Cloudflare Workers)
│     ├─ src/
│     │  ├─ routes/           # quote / chart / feed 等 API 路由
│     │  ├─ connectors/       # yahoo / mock / rss 的 fetchOnce + normalize 调用
│     │  └─ index.ts          # Hono app 入口
│     └─ wrangler.toml        # Worker 配置（路由、KV 绑定、Cron Triggers）
└─ docs/
```

> shared 的 `normalize()` 同时被 web（类型）与 api（运行）引用，是前后端契约的单一来源。

---

## 8. 分阶段实施路线

### MVP（阶段一）—「能看实时行情 + 资讯流」
1. monorepo 脚手架（pnpm workspace）+ shared 标准模型/normalize。
2. **api（Hono Worker）**：`/api/quote`（Yahoo 报价）、`/api/feed`（RSS）、Mock 兜底；响应加 `s-maxage` 边缘缓存；`wrangler dev` 本地跑通。
3. **web（Vite React）**：TanStack Query `refetchInterval` 定时拉 `/api/*`；指标卡片 + 信息流列表；深色终端风。
4. 关注列表/布局**固定**，无登录、无 DB、无 SSE。
5. 部署：web→Pages，api→Workers。

### 阶段二 —「更多源 + 历史图 + 简单告警 + 个性化」
1. `/api/chart` 历史 K 线（Yahoo chart）+ Lightweight-Charts 历史面板。
2. 前端阈值标红/Toast（规则存 localStorage）。
3. 关注列表/布局个性化（localStorage 或 KV）。
4. `http-json` 自定义源 + JSONPath。
5. （可选）Cron Triggers + KV 服务端定时缓存，削减源请求。

### 阶段三 —「扩展」（按需）
1. 用户注册/登录（Cloudflare Access 或 Worker+KV/D1），仍 serverless。
2. ECharts 高级图表（热力图/关系图/3D）。
3. 自建文章（KV/D1/R2 + Markdown）。
4. 更多数据源、Webhook 通知。

---

## 9. 已确认决策（serverless 版定稿）

1. **定位**：纯市场行情信息展示，非量化，不要秒级。
2. **架构**：Serverless / 边缘 —— Cloudflare **Pages（前端 Vite React）** + **Workers（Hono API）**。后续即使加登录/个性化也**继续沿用 serverless**。
3. **数据流**：前端定时器（TanStack Query `refetchInterval`）触发 → 调自家 Worker API → Worker 代理拉 Yahoo/RSS + `normalize()` + 边缘缓存 → 返回 JSON。**前端不直连外部源（CORS）**。
4. **首批源**：Yahoo Finance（主，quote/chart）+ Mock（兜底/开发）+ RSS（新浪财经占位，可换）。Binance WS **延后**（不适合 serverless）。
5. **数据层**：当前**无 DB、无 Redis、无 SSE**；共享/限流用边缘缓存（`s-maxage`，进阶 Cron+KV）；历史临时查 Yahoo。
6. **登录/配置**：当前不做登录、关注列表与布局固定；将来个性化用 serverless 存储（localStorage / KV / D1）。
7. **保留**：shared 标准模型（MarketTick/OHLCV/FeedItem/GenericMetric）+ `normalize()` 归一化抽象 + 前端可视化选型。
