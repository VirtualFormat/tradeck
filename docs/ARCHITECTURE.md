# Tradeck — 架构设计方案

> 目标：小团队内部共享的市场数据仪表盘（深色专业终端风，参考 Claude Fable 5 / Mirofish）。
> 务实优先，明确标注「必须 / 可砍 / 可延后」。本文为已定稿方案（2026-06-25）。

---

## 0. 一句话结论

选型整体合理且现代。两点「踩刹车」：
1. **后端框架** → 选 **NestJS**（模块化 + DI 对 Connector 插件框架天然友好），但**不上微服务**。
2. **TimescaleDB** → **MVP 延后**，先用纯 PostgreSQL；它本身是 PG 扩展，将来 `CREATE EXTENSION timescaledb` + 把历史表转 hypertable 即可，应用代码几乎不动。

明确砍掉：Socket.IO（用 SSE）、Kafka/MQ、微服务拆分、K8s、多租户/计费。

---

## 1. 技术栈定档

### 1.1 前端
| 项 | 决策 | 说明 |
|---|---|---|
| React 18 + TS + Vite | ✅ | 标准组合 |
| TanStack Query | ✅ 必须 | 负责 REST/快照数据缓存、重试、失效 |
| Zustand | ✅ 必须 | 负责「实时流状态」（SSE 推来的价格/信号） |
| TradingView Lightweight-Charts | ✅ 必须(K线) | K线/PnL 曲线，性能远超 ECharts |
| ECharts (+echarts-gl) | ✅ 必须(通用) | 3D 山脊图、关系图谱、热力图、概率分布 |
| Tailwind + shadcn/ui | ✅ | 深色终端风用 CSS 变量定义 design token |
| react-grid-layout | ➕ 必须 | 可拖拽自定义仪表盘网格 |

**职责切分铁律**：TanStack Query 管「请求来的数据」，Zustand 管「推送来的数据」，两者不混用，避免高频更新打爆 Query 缓存。

### 1.2 后端
- **NestJS + TypeScript**，单进程 modular monolith。
- 砍掉：微服务、gRPC、Kafka/RabbitMQ。

### 1.3 数据层
- **PostgreSQL 主库**：用户、配置、仪表盘布局、数据源配置、告警规则、文章、信息流。
- **TimescaleDB**：MVP 延后。触发升级信号：单表行情行数 > 千万级 / 需要连续聚合 / 需要保留策略。
- **Redis**：仅三用途 —— (a) 最新行情快照；(b) pub/sub 扇出推送；(c) 限流/去重。不作主存储。
- **ORM**：**Drizzle**（贴近 SQL，利于后期手写 Timescale 相关 SQL）。

### 1.4 实时传输
- **SSE**：服务器→客户端单向，秒级行情足够，自动重连、走 HTTP、无握手负担。
- realtime 做成**可替换网关**，将来需双向（客户端订阅/退订特定 symbol）再换原生 **ws**。不用 Socket.IO。

### 1.5 部署
- **Docker Compose 单机**：services = `web(nginx静态)` + `api(nest)` + `postgres` + `redis`。
- 砍掉：K8s、多副本、服务网格。

### 「过度设计」清单
| 组件 | 处置 | 原因 |
|---|---|---|
| Kafka / RabbitMQ | ❌ 砍 | Redis pub/sub 对小团队足够 |
| 微服务拆分 | ❌ 砍 | 单 monolith，模块隔离即可 |
| K8s | ❌ 砍 | Compose 单机 |
| Socket.IO | ❌ 砍 | SSE 更轻 |
| TimescaleDB | ⏸ 延后 | 先纯 PG，无缝升级 |
| 多租户/计费 | ❌ 砍 | 内部共享 |
| 独立采集器服务 | ⏸ 延后 | MVP 内嵌 api 进程；源变多再拆 worker |

---

## 2. 数据源插件框架（Connector）★核心

### 2.1 目标
统一抽象，让 WS推送源 / REST轮询源 / RSS源 / 自定义HTTP源 用同一套生命周期与数据契约接入，配置驱动、热插拔。

### 2.2 核心抽象
**Connector 统一生命周期**：
- `init(config)` — 配置（凭证、URL、symbol 列表、轮询间隔）
- `start()` / `stop()` — 启停
- `health()` — 健康状态（UI 显示源在线/离线）
- 产出事件：`onData(normalizedPayload)`、`onError(err)`、`onStatus(status)`

**两种采集模式统一出口**：
- **Push 型**（交易所 WS）：维持长连接，原始帧 → `normalize()` → emit。
- **Pull 型**（REST/HTTP/RSS）：调度器按 `interval` 轮询 → `normalize()` → emit。框架提供 PollingBase（封装定时、退避、抖动、去重），Pull 型只需实现 `fetchOnce()`。

**normalize() 映射到标准内部模型**（定义在 `packages/shared`）：
- `MarketTick` { source, symbol, ts, price, volume, ... }
- `OHLCV` { source, symbol, interval, ts, o,h,l,c,v }
- `FeedItem` { source, id, title, url, summary, publishedAt, tags }
- `GenericMetric` { source, key, ts, value, meta }（兜底，给自定义 HTTP 源）

### 2.3 注册与配置驱动
- **ConnectorRegistry**：启动时注册所有类型（`binance-ws`、`mock`、`rss`、`http-json`、`generic-rest`、`polymarket`…）。
- **数据源实例 = 配置记录**（PG `data_sources` 表）：{ id, type, name, enabled, config(JSONB), schedule }。
- **ConnectorManager**：读 DB 配置 → Registry 实例化 → 管理生命周期；配置增删改后热重载（stop 旧 / start 新），无需重启进程。
- **自定义 HTTP 源** = `http-json` 通用 Connector + JSONPath 映射配置（UI 填 URL + 字段映射，如 `price <- $.data.last`），免写代码接新源。

### 2.4 出口
所有 Connector 的 `normalize()` 输出 → 统一进 Ingestion Pipeline。Connector 不直接写库、不直接推前端，只负责「采集+归一化+emit」。

---

## 3. 实时数据链路 ★核心

```
[Connector(WS/REST/RSS)]
        │ emit NormalizedEvent
        ▼
[Ingestion Pipeline] ── 1.去重/校验
        ├─→ 2. 写 Redis 最新快照 (key: latest:{source}:{symbol})
        ├─→ 3. 异步落库 (PG / 后期 Timescale)  ← 批量/节流写
        ├─→ 4. 喂给 Alert Engine 评估规则 (§4)
        └─→ 5. Redis PUBLISH channel:{symbol or topic}
                          │
                          ▼
              [Fan-out / Subscription Hub] ← 订阅 Redis channel
                          │ SSE push (按客户端订阅过滤)
                          ▼
              [前端 Zustand store] → 图表组件局部 re-render
```

### 设计要点
1. **采集隔离**：每个 Connector 各自跑 + try/catch + 自动重连退避，单源崩溃不影响其他源。
2. **归一化**：在 Connector 内完成，出口只有标准模型。
3. **快照 + 历史分离**：Redis 存每 symbol 最新值（首屏/新订阅秒出）；PG 存历史（K线回看/PnL）。**写库必须节流/批量**（如每秒聚合一次），避免高频 tick 打爆数据库。
4. **扇出**：后端订阅 Redis pub/sub，按客户端订阅的 symbol/topic 服务端过滤后推送。天然为多实例预留（MVP 单实例可走进程内 EventEmitter，二选一）。
5. **前端订阅**：一条 SSE 长连接 + 客户端声明订阅集合（当前看板可见 symbol/topic）→ 后端只推这部分 → 进 Zustand → 图表订阅 slice 局部更新。历史/首屏走 TanStack Query (`GET /api/ohlcv`)，实时增量走 SSE，两路在图表组件汇合。

---

## 4. 告警 / 指标引擎

### 4.1 规则模型（PG `alert_rules`）
`{ id, name, sourceFilter, symbol, metric, operator(>/</cross/%change), threshold, window, severity, channels[], enabled, cooldown }`
- **阈值型**：`price > 70000`、`24h涨跌幅 > 5%`。MVP 做这类。
- **派生型**：均线交叉、波动率、自定义表达式。延后。

### 4.2 流程
Ingestion Pipeline 每条归一化数据 → Alert Engine → 拉匹配该 symbol 的启用规则 → 评估命中则：写 `alert_events` → cooldown 去抖 → 通过 channels 通知（① 前端实时推送 Toast/红点，复用 §3 通道；② 可选 Webhook）。
**指标卡片** = 订阅某 symbol 快照 + 规则状态的前端组件，数据源同实时流。

### 4.3 MVP 取舍
- ✅ 阈值规则 + 前端推送 + 1 个通用 Webhook。
- ⏸ 复杂表达式引擎、回测、多通道(飞书/钉钉/邮件)、派生指标。

---

## 5. 资讯文章模块

### 5.1 聚合外部源
RSS Connector / http-json Connector 拉取 → `normalize()` 成 `FeedItem` → 入 `feed_items` 表（去重靠 `source + externalId` 唯一键）。前端信息流 = 分页/无限滚动查询，按时间/标签/来源过滤。

### 5.2 自建文章
`articles` 表 `{ id, authorId, title, body(markdown), status(draft/published), tags, publishedAt }` + Markdown 编辑器。与 `feed_items` 在 UI 合并为统一信息流（用 `type` 区分）。

### 5.3 MVP 取舍
- ✅ RSS 聚合 + 信息流展示 + 自建文章基础 CRUD。
- ⏸ 全文搜索（先 PG `tsvector`）、评论、协作编辑。

---

## 6. 项目目录结构（pnpm monorepo）

理由：前后端共享 TS 类型（标准数据模型 + DTO），避免类型漂移。不需要 Nx/Turborepo，pnpm workspace 足够。

```
tradeck/
├─ pnpm-workspace.yaml
├─ docker-compose.yml
├─ packages/
│  ├─ shared/                 # 跨端共享：标准数据模型、DTO、zod schema、常量
│  ├─ web/                    # 前端 (React + Vite)
│  │  └─ src/
│  │     ├─ app/              # 路由、布局、provider
│  │     ├─ features/         # dashboard / charts / alerts / feed / sources / auth
│  │     ├─ components/       # shadcn/ui 封装 + 通用组件
│  │     ├─ charts/           # lightweight-charts & echarts 封装
│  │     ├─ stores/           # zustand (实时流 state)
│  │     ├─ api/              # tanstack query hooks + http client + SSE client
│  │     └─ styles/           # tailwind + 深色 token
│  └─ api/                    # 后端 (NestJS)
│     └─ src/
│        ├─ modules/
│        │  ├─ auth/          # 邮箱密码登录/会话（留口接 SSO）
│        │  ├─ connectors/    # Connector 框架：registry/manager/base/各类型实现
│        │  ├─ ingestion/     # pipeline：归一化出口、快照、落库、扇出
│        │  ├─ realtime/      # SSE 网关 + 订阅 hub（可替换）
│        │  ├─ market/        # ohlcv/快照 查询 API
│        │  ├─ alerts/        # 规则 CRUD + 引擎 + 通知
│        │  ├─ feed/          # 资讯聚合 + 文章
│        │  └─ dashboards/    # 仪表盘布局/卡片配置 CRUD
│        ├─ infra/            # drizzle, redis, config
│        └─ main.ts
└─ docs/
```

---

## 7. 分阶段实施路线

### MVP（阶段一）—「能看、能登、能实时」
1. monorepo 脚手架 + Docker Compose (api/web/postgres/redis) + shared 类型包。
2. Auth：用户名+密码（单组织，无多租户；抽象留口后接 SSO）。
3. Connector 框架骨架 + **3 个 Connector**：Binance WS + Mock(兜底/演示) + RSS(新浪财经占位源)。
4. Ingestion Pipeline：归一化 → Redis 快照 → 节流落 PG → 扇出。
5. Realtime：SSE 通道 + 前端 Zustand 订阅。
6. 前端：可拖拽仪表盘(react-grid-layout) + K线(lightweight-charts) + 指标卡片 + 信息流列表。
7. TimescaleDB 不上，纯 PG。

### 阶段二 —「可配、能报警、能写」
1. 数据源配置 UI（含 http-json 自定义源 + JSONPath 映射）。
2. 告警引擎（阈值 CRUD + 前端推送 + 1 Webhook）。
3. ECharts 高级图表（热力图、关系图谱、概率分布）。
4. 自建文章 CRUD + Markdown 编辑器，与聚合流合并。
5. 团队共享仪表盘/告警规则。

### 阶段三 —「扩展与优化」（按需）
1. 接入 TimescaleDB（转 hypertable + 连续聚合 + 保留策略）。
2. 3D 山脊图(echarts-gl)、OKX 期权 / Polymarket / 链上 Connector。
3. 派生指标/信号引擎。
4. 多通知通道、全文搜索。
5. 拆独立采集 worker（靠 Redis pub/sub 解耦）。

---

## 8. 已确认决策（定稿）
1. **登录**：MVP 自建**用户名+密码**（JWT/session），auth 抽象留口后接 SSO。
2. **首批源**：Binance 公开 WebSocket + Mock 兜底 + RSS（占位源：新浪财经 `https://rss.sina.com.cn/roll/finance/hot_roll.xml`，跑通链路用，可随时换）；OKX 期权延后到阶段三做概率山脊图。
3. **ORM**：Drizzle。
4. **实时传输**：SSE（realtime 做成可替换网关）。
5. **通知通道**：**MVP 不做通知**（前端推送 + Webhook 整体延后到阶段二）；channels 设计为可扩展数组，阶段二再定具体 IM。
6. **开发与部署**：项目运行/调试在自身 Docker Compose 容器内（源码 bind mount，node_modules 留容器，不污染宿主 WSL）；镜像选多架构（amd64+arm64）保持多平台兼容；GitHub 仓库 private。

| 维度 | Binance | OKX | Mock |
|---|---|---|---|
| 鉴权 | 公开免 key | 公开免 key | 无 |
| 订阅 | URL 带流名，连上即有数据 | 连上后发 JSON 订阅+心跳 | 无 |
| 接入难度 | 最低 | 中 | 最低 |
| 适合场景 | K线/PnL/卡片 | 期权链→概率山脊图 | 跑通架构/演示 |
