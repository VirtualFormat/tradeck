# CODEBUDDY.md

本文件为 CodeBuddy / 协作者提供项目上下文。后续开发将在 **WSL Ubuntu** 中进行。

## 项目是什么

Tradeck —— 小团队内部共享的实时市场数据仪表盘（深色专业终端风）。Trade + Deck（驾驶舱式看板）。
功能：自定义市场数据可视化、重要指标卡片 + 阈值告警、可插拔数据源接入、资讯文章信息流。

- **定位**：内部团队工具，非对外 SaaS。无多租户、无计费。务实优先，避免过度设计。
- **完整架构方案**：见 `docs/ARCHITECTURE.md`（已定稿，2026-06-25）。**动手前先读它**。

## 当前状态

- 架构方案已定稿，**尚未开始编码**。目录仅含 `docs/` 与本文件。
- 下一步（待开始）：搭 monorepo 脚手架 + Docker Compose + 跑通一条端到端实时链路（MVP 阶段一）。

## 技术栈（定稿，勿擅自更换）

| 层 | 选型 |
|---|---|
| 仓库结构 | pnpm monorepo：`packages/{shared, web, api}`，npm scope `@tradeck/*` |
| 前端 | React18 + TS + Vite，TanStack Query(请求数据) + Zustand(实时流数据)，Lightweight-Charts(K线) + ECharts(3D/关系图/热力图)，Tailwind + shadcn/ui，react-grid-layout |
| 后端 | NestJS modular monolith（不拆微服务），Drizzle ORM |
| 实时 | SSE（单向；realtime 做成可替换网关，将来需双向再换 ws）。不用 Socket.IO |
| 数据 | PostgreSQL 主库；Redis(快照/pub-sub扇出/限流)；TimescaleDB **延后** |
| 部署 | Docker Compose 单机（web/api/postgres/redis） |

## 关键约定（来自架构方案）

- **职责切分铁律**：TanStack Query 管「请求来的数据」，Zustand 管「推送来的实时数据」，两者不混用。
- **Connector 框架**：所有数据源实现统一接口（`init/start/stop/health` + `onData/onError/onStatus`），Push 型(WS) 与 Pull 型(REST/RSS/HTTP) 统一出口，`normalize()` 映射到 `packages/shared` 的标准模型（MarketTick/OHLCV/FeedItem/GenericMetric）。Connector 只负责采集+归一化+emit，不直接写库/推前端。
- **shared 标准模型**（`packages/shared`）：`MarketTick` / `OHLCV` / `FeedItem` / `GenericMetric`（自定义 HTTP 源兜底）。所有 `normalize()` 必须输出这四类之一。
- **自定义 HTTP 源**：用 `http-json` 通用 Connector + JSONPath 字段映射，免代码接入。
- **写库节流**：高频 tick 必须批量/节流落 PG（如每秒聚合一次），Redis 存最新快照。
- **实时链路**：`Connector.emit → Ingestion(去重→Redis快照→节流落PG→Alert评估→Redis PUBLISH) → 订阅Hub → SSE → 前端Zustand → 图表局部更新`。首屏/历史走 TanStack Query（`GET /api/ohlcv`），实时增量走 SSE，两路在图表组件汇合。详见 ARCHITECTURE.md §3。
- **后端模块边界**（`packages/api/src/modules/`）：`auth` / `connectors`(registry+manager+base+实现) / `ingestion`(归一化出口→快照→落库→扇出) / `realtime`(SSE 网关+订阅 hub，可替换) / `market`(ohlcv/快照查询) / `alerts` / `feed` / `dashboards`；基础设施在 `infra/`(drizzle/redis/config)。
- **MVP 范围铁律**：只做阈值告警(`>/<`)、SSE 单向、纯 PG(不上 Timescale)、采集内嵌 api 进程(不拆 worker)。派生指标/复杂表达式/独立 worker/全文搜索全部延后，勿提前实现。
- **MVP 取舍（用户已拍板）**：① 登录用**用户名+密码**（非邮箱）；② **MVP 不做通知**（前端推送+Webhook 延后到阶段二）；③ 首批源 = Binance 公开 WS + Mock 兜底 + RSS（占位：新浪财经 `https://rss.sina.com.cn/roll/finance/hot_roll.xml`，可随时换）。

## WSL Ubuntu 开发说明

后续在 WSL Ubuntu 中开发，注意：

- **代码放在 WSL 文件系统内**（如 `~/projects/tradeck`），不要放在 `/mnt/d/...`。跨 `/mnt` 访问 Windows 盘的 IO 极慢，会拖垮 pnpm install / Vite HMR / 文件监听。
  - 迁移方式：在 WSL 里 `cp -r /mnt/d/Code/projects/tradeck ~/projects/`，或重新 `git clone` 到 WSL home。
- **行尾**：仓库统一 LF。建议加 `.gitattributes`：`* text=auto eol=lf`；Windows 侧 `git config core.autocrlf input`。
- **运行时**：Node **24**（用 nvm 装；根目录放 `.nvmrc` 内容 `24`，`engines` 钉死 `>=24 <25`），包管理用 **pnpm**（`corepack enable && corepack prepare pnpm@latest --activate`）。
  ```bash
  nvm install 24 && nvm alias default 24
  corepack enable && corepack prepare pnpm@latest --activate
  ```
- **Docker**：用 Docker Desktop 的 WSL 集成，或在 Ubuntu 内装 docker engine。
- **端口**：WSL 服务可直接从 Windows 浏览器经 `localhost` 访问（WSL2 自动转发）。

### 容器内开发铁律（重要）

- **环境拓扑**：Windows 上的 CodeBuddy IDE 远程打开 WSL Ubuntu 裸机目录；WSL 只装 git/docker 等必要工具。"宿主/不要污染" 指的就是这个 WSL。
- **开发用 Dev Container，部署用 docker compose**（两套配置独立）。
  - 开发：CodeBuddy IDE「Reopen in Container」→ IDE backend 跑在 `api` 容器内，语言服务读容器卷里的 node_modules，跳转/补全/类型检查可用，且**不污染 WSL**。配置见 `.devcontainer/devcontainer.json`（复用根 `docker-compose.yml`，service=api，`postCreateCommand` 自动 `pnpm install`）。
  - 部署：`docker compose`（用各 Dockerfile 的 prod target）。
- **项目运行/调试全部在容器内进行**，不污染 WSL。
- **不要在 WSL 里跑 `pnpm/npm install` 生成 node_modules**，也不要在 WSL 安装多余工具。所有 Node 相关命令（install/dev/build/test/db）都在容器里执行。
- compose 配置：源码 **bind mount** 进容器，**node_modules 放在容器内的卷里**（命名卷/匿名卷，避免回写 WSL）。
- 镜像选 **多架构（amd64+arm64）官方镜像**，保持多平台兼容（便于将来部署到 ARM 主机）。
- GitHub 仓库为 **private**。

## 常用命令（脚手架建立后补充实际命令）

> 项目尚未初始化，以下为规划中的命令，待脚手架落地后**以实际 package.json scripts / compose service 名为准**。
> 所有 Node 命令都在容器内执行（见上「容器内开发铁律」），不要在 WSL 直接跑。

```bash
docker compose up -d              # 起全栈（web/api/postgres/redis）
docker compose logs -f api        # 看后端日志

# 在容器内执行（service 名以 compose 实际定义为准，下面假设为 api / web）
docker compose exec api pnpm install            # 安装依赖（装进容器卷，不落 WSL）
docker compose exec api pnpm -F @tradeck/api dev    # 后端 NestJS watch
docker compose exec web pnpm -F @tradeck/web dev    # 前端 Vite
docker compose exec api pnpm -F @tradeck/api db:push  # Drizzle 推送 schema

# 跑单个测试（脚手架定测试框架后以实际为准，示例 vitest/jest）
docker compose exec api pnpm -F @tradeck/api test -- <文件或用例名>
```
