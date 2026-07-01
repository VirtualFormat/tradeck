# CODEBUDDY.md

本文件为 CodeBuddy / 协作者提供项目上下文。后续开发将在 **WSL Ubuntu** 中进行。

## 项目是什么

Tradeck —— 小团队内部共享的市场数据仪表盘（深色专业终端风）。Trade + Deck（驾驶舱式看板）。
**定位收敛为：纯市场行情信息展示**（非量化交易平台、不要秒级、当前阶段只做数据源查询+展示）。
功能：市场数据可视化、指标卡片、可插拔数据源、资讯文章信息流。

- **定位**：内部团队工具，非对外 SaaS。无多租户、无计费。务实优先，避免过度设计。
- **架构**：**Serverless / 边缘**（Cloudflare Pages + Workers）。**完整方案见 `docs/ARCHITECTURE.md`（serverless 版定稿，2026-07-01）。动手前先读它**。

## 当前状态

- **serverless 脚手架已落地**（2026-07-01）：`packages/{shared, api, web}` 三包 + `.devcontainer` 单容器已建。旧的 NestJS/PG/Redis/东方财富实现已存档到 `archive/nestjs-eastmoney` 分支后推倒重来。
  - `shared`：标准模型（MarketTick/OHLCV/FeedItem/GenericMetric）+ zod + 固定 watchlist/RSS 源。
  - `api`：Hono on Workers，路由 `/api/quote`(Yahoo,失败降级 Mock) `/api/chart`(历史) `/api/feed`(RSS)，带 `s-maxage` 缓存头。
  - `web`：Vite React + Tailwind 深色终端风，TanStack Query `refetchInterval` 轮询自家 API，vite proxy `/api`→`localhost:8787`。
- **注意**：WSL 下 Docker 容器默认无 DNS，`.devcontainer/docker-compose.yml` 已给 dev 服务加 `dns: [1.1.1.1, 8.8.8.8]` 解决。
- 下一步：跑通端到端后按 ARCHITECTURE.md 阶段二推进（历史面板、更多源、阈值标红、个性化）。

## 技术栈（serverless 版定稿，勿擅自更换）

| 层 | 选型 |
|---|---|
| 仓库结构 | pnpm monorepo：`packages/{shared, web, api}`，npm scope `@tradeck/*` |
| 前端 | React18 + TS + Vite → **Cloudflare Pages**；TanStack Query（轮询/缓存，用 `refetchInterval`）；Lightweight-Charts(K线) + ECharts(热力/关系/3D)；Tailwind + shadcn/ui；react-grid-layout |
| 后端 | **Cloudflare Workers + Hono**（一组无状态 API 函数，代理拉取+归一化）；**Wrangler** 开发/部署 |
| 刷新 | **前端定时轮询**（TanStack Query `refetchInterval`），**无 SSE / 无 WS / 无推送** |
| 数据 | **无 DB / 无 Redis**；共享与限流靠**边缘缓存**（响应头 `Cache-Control: s-maxage`，进阶可 Cron Triggers + KV） |
| 部署 | Cloudflare Pages（前端）+ Workers（API）。**无 Docker Compose** |

## 关键约定（来自架构方案）

- **⚠️ 前端绝不直连外部源**：浏览器 CORS 会拦截 Yahoo/RSS（它们不返回跨域头）。前端只 fetch **自家 Worker API（同源）**，由 Worker 服务端去拉外网。这是 serverless 方案成立的前提。
- **数据流**：`前端 setInterval/refetchInterval → 自家 Worker API → Worker 拉 Yahoo/RSS + normalize() + s-maxage 边缘缓存 → 返回 JSON → 前端渲染`。详见 ARCHITECTURE.md §1/§2。
- **shared 标准模型**（`packages/shared`）：`MarketTick` / `OHLCV` / `FeedItem` / `GenericMetric`（自定义 HTTP 源兜底）。所有 `normalize()` 必须输出这四类之一。shared 同时被 web（类型）与 api（运行）引用，是前后端契约单一来源。
- **归一化抽象**：采集模式只剩 **Pull 型**（serverless 无常驻进程，不做 WS Push）。每个源 = `fetchOnce()` + `normalize()` 纯逻辑，由 Worker 路由按请求调用。源封装在 `packages/api/src/connectors/`。
- **数据职责**：所有数据都是「请求来的」，统一由 **TanStack Query** 管（`refetchInterval` 周期刷新）。旧的「Zustand 管推送流」一路已取消，Zustand 降级为可选纯 UI 状态工具。
- **无持久化**：当前不落库；历史面板（若做）由前端临时调 `/api/chart` → Worker 现拉 Yahoo。将来任何持久化都用 **serverless 友好存储（localStorage / KV / D1 / R2）**，不引入常驻 DB。
- **MVP 范围铁律**：只做「拉取行情/资讯 + 展示」。无登录、无 DB、无 SSE、无告警引擎、无自建文章。派生指标/自定义源/告警/个性化全部延后，勿提前实现。
- **MVP 取舍（用户已拍板，2026-07-01）**：
  ① **架构 serverless**，后续即使加用户注册/关注股票/布局配置也**继续沿用 serverless**；
  ② **登录暂不做**，关注列表与布局**先固定**；
  ③ **无 Redis**（非分布式，单边缘函数 + 边缘缓存足够）；
  ④ **无 DB**（纯展示），历史临时查 Yahoo；
  ⑤ 首批源 = **Yahoo Finance（主，quote/chart）** + Mock 兜底 + RSS（占位：新浪财经 `https://rss.sina.com.cn/roll/finance/hot_roll.xml`，可随时换）；**Binance WS 延后**（WS 不适合 serverless）。

## WSL Ubuntu 开发说明

后续在 WSL Ubuntu 中开发，注意：

- **代码放在 WSL 文件系统内**（如 `~/projects/tradeck`），不要放在 `/mnt/d/...`。跨 `/mnt` 访问 Windows 盘的 IO 极慢，会拖垮 pnpm install / Vite HMR / 文件监听。
- **行尾**：仓库统一 LF。建议加 `.gitattributes`：`* text=auto eol=lf`；Windows 侧 `git config core.autocrlf input`。
- **运行时**：Node **24**（用 nvm 装；根目录放 `.nvmrc` 内容 `24`，`engines` 钉死 `>=24 <25`），包管理用 **pnpm**（`corepack enable && corepack prepare pnpm@latest --activate`）。
  ```bash
  nvm install 24 && nvm alias default 24
  corepack enable && corepack prepare pnpm@latest --activate
  ```
- **端口**：容器内 `wrangler dev` / `vite dev` 端口 forward 出来后，可从 Windows 浏览器经 `localhost` 访问（WSL2 自动转发）。

### 容器内开发铁律（重要，serverless 版）

> **环境拓扑**：Windows 上 CodeBuddy IDE 远程打开 WSL Ubuntu 裸机目录；WSL 只装 git/docker 等必要工具。"宿主/不要污染" 指的就是这个 WSL。

- **仍用 Dev Container 开发，以不污染 WSL**（用户硬诉求，serverless 不改变这一点）。`wrangler dev` 本质是 Node 进程（底层跑 `workerd`），照样要 `node_modules`、照样要 `pnpm install`；在 WSL 裸机装就污染了裸机，所以放容器里。
- **与旧方案的区别**：Dev Container 从"复用多服务 compose（api+web+postgres+redis）"**简化为单个 node+pnpm+wrangler 开发容器**——serverless 无 DB/Redis，不需要那些 service。
- **原则不变**：
  - 项目运行/调试全部在容器内（`wrangler dev` + `vite dev`），不污染 WSL。
  - **不在 WSL 裸机跑 `pnpm/npm install`**；所有 Node 命令（install/dev/build/test/deploy）在容器内执行。
  - 源码 **bind mount** 进容器，**node_modules 放容器内的卷**（命名卷/匿名卷，避免回写 WSL）。
  - IDE「Reopen in Container」→ 语言服务读容器卷里的 node_modules，跳转/补全/类型检查可用。
- **部署不经容器**：直接 `wrangler deploy`（Worker）+ Pages 构建（前端），无需自建镜像/Compose。开发容器只服务本地开发。
- 镜像选多架构（amd64+arm64）官方 node 镜像，保持多平台兼容。
- GitHub 仓库为 **private**。

## 常用命令（脚手架建立后补充实际命令）

> 项目尚未初始化，以下为规划中的命令，待脚手架落地后**以实际 package.json scripts 为准**。
> 所有 Node 命令在**开发容器内**执行（见上「容器内开发铁律」），不要在 WSL 裸机直接跑。

```bash
# 进开发容器后执行（或 IDE Reopen in Container 后在集成终端）
pnpm install                 # 安装依赖（装进容器卷，不落 WSL）

# 本地开发
pnpm -F @tradeck/api dev     # Worker 本地：wrangler dev（模拟 Cloudflare 运行时）
pnpm -F @tradeck/web dev     # 前端：vite dev

# 构建 / 部署
pnpm -F @tradeck/web build   # 前端构建静态产物（部署 Pages）
pnpm -F @tradeck/api deploy  # wrangler deploy 部署 Worker

# 跑测试（脚手架定测试框架后以实际为准，示例 vitest）
pnpm -F @tradeck/api test -- <文件或用例名>
```
