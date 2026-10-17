# tradb 独立部署切换 — 任务列表与验收

> 目标：把数据服务从「tradeck 内嵌 collector/data-api」切换为「tradb 独立 compose 部署」，
> tradeck web/quant 经宿主机回环（host.docker.internal）+ service token 访问 tradb。
> 执行方标注：【我准备】= 主 agent 在本地/仓库完成；【VPS】= 需在 VPS 上执行（用户或授权后）。
> 每项带验收标准，逐项推进、逐项回填状态。

## 前置事实（2026-09-08 已确认）

- tradb 仓库已上线：`VirtualFormat/tradb`（私有，main 分支），CI 已构建成功（3 镜像）。
- 镜像命名空间沿用 `ghcr.nju.edu.cn/virtualformat/`：`tradb-data-api` / `tradb-collector` / `tradb-mock`。
- 鉴权：data-api 配置 `SERVICE_TOKENS` 后全接口强制 `X-Service-Token`；web/quant 已带 token 能力。
- 部署方式：VPS 上跑 `deploy/deploy-cn.sh`（经南京大学镜像站拉 GHCR + compose up）。
- **回环形态**：tradb 独立 compose 全服务只绑 127.0.0.1；tradeck web/quant 经
  `host.docker.internal:host-gateway` 访问宿主机 localhost 上的 tradb。

## 任务列表

| # | 任务 | 执行方 | 验收标准 | 状态 |
|---|---|---|---|---|
| 1 | 生成 service token 对（web/quant 各一），写入 tradeck 与 tradb 的 `.env.example` 注释（真实值只进 VPS `.env`，不入库） | 【我准备】 | token 生成方法 + 两仓库 .env.example 契约一致 | ✅ |
| 2 | tradb 版部署脚本 `deploy/deploy-cn.sh`（拉 tradb 镜像 + compose up），与 tradeck 版并存 | 【我准备】 | 脚本静态校验通过、拉取服务清单正确 | ✅ |
| 3 | tradb compose 增加 mock-seed 一致性核对 + openbb config 目录说明 | 【我准备】 | compose config 通过、openbb 配置目录占位 | ✅ |
| 4 | 本地预演：起 tradb 独立 compose（postgres+clickhouse+openbb+collector+data-api），data-api 鉴权冒烟（无 token 401 / 带 token 200） | 【我准备】 | 容器健康 + 鉴权行为正确 | ✅ |
| 5 | tradeck compose 切到「tradb 独立」模式：web/quant 的 `TRADB_API_URL`/`TRADB_COLLECTOR_URL` 指向 host.docker.internal，内嵌 collector/data-api 标注退役 | 【我准备】 | compose config 通过、退役服务加注释 | ✅ |
| 6 | 迁移指南文档（VPS 操作步骤 + 回滚方案）写入 docs/ | 【我准备】 | 文档含切换/回滚/排障 | ✅ |
| 7 | 【VPS】克隆/拉取 tradb 仓库 + 填 `.env`（SERVICE_TOKENS / 数据源密钥 / POSTGRES 密码） | 【VPS】 | tradb `.env` 就绪 | ✅ |
| 8 | 【VPS】数据迁移决策：tradb 用新卷从零采集，还是挂载/迁移现有 PG + data-pool | 【VPS】 | 决策记录 + 数据可用 | ✅ |
| 9 | 【VPS】起 tradb（`deploy/deploy-cn.sh`），确认 5 容器健康 + data-api 带 token 通 | 【VPS】 | health 全绿 + token 冒烟通过 | ✅ |
| 10 | 【VPS】tradeck 切到 tradb：改 `.env` 的 TRADB_* + token，`deploy/deploy-cn.sh` 重启 web/quant | 【VPS】 | web 首页/个股页渲染正常、数据来自 tradb | ✅ |
| 11 | 【VPS】停掉 tradeck 内嵌 collector/data-api/postgres/clickhouse（确认 tradb 接管后） | 【VPS】 | 内嵌服务已停、web 仍正常 | ✅ |
| 12 | tradeck 仓库退役内嵌 data-api/collector 代码（tradb 稳定运行后；另一迭代） | 【我准备】 | 代码删除 + CI 调整 | ⬜ |

## 回滚方案（贯穿 9-11）

> **已失效（2026-09-12）**：tradeck 根 compose 已删除全部内嵌数据服务，
> 以下「改回默认值即回滚」的路径不再存在。回滚需先恢复旧 compose
> （`git show eb5e188:docker-compose.yml`），详见 `docs/TRADB-DEPLOY.md` 回滚一节。

- tradb 与 tradeck 内嵌数据服务**并行存在期**：tradeck `.env` 的 `TRADB_API_URL` 默认值回退
  到同 compose 的 `data-api` 服务名，改回默认值 + 重启即回滚到内嵌模式。
- 步骤 11（停内嵌服务）前必须确认步骤 10 web 全链路正常；步骤 11 可逆（重新 up 即可）。

## 验收记录

### 【我准备】1-6（2026-09-08 完成）

- **任务 1**：token 生成方法（`openssl rand -hex 32`）+ tradeck/tradb `.env.example` 契约一致
  （web-bff ↔ TRADB_SERVICE_TOKEN、quant ↔ QUANT_SERVICE_TOKEN）。
- **任务 2**：tradb `deploy/deploy-cn.sh`（拉 openbb/collector/data-api + postgres/clickhouse，
  经南京大学镜像站），bash -n 通过。
- **任务 3**：tradb openbb/config 目录占位（.gitkeep），compose config 通过。
- **任务 4 本地预演**：起独立 PG（挂 init.sql 建 34 表）+ CH + tradb-data-api（本地 build，
  绑 127.0.0.1 + SERVICE_TOKENS）。结果全绿：`/health` 200、无 token 401、错 token 401、
  对 token 空表优雅降级 200 `[]`。首次 500 为预览 PG 未挂 init.sql 的环境因素（UndefinedTable），
  挂 init.sql 后正常——真实部署 compose 已挂 init.sql，非 bug。预览环境已清理。
- **任务 5**：tradeck prod compose 的 web/quant 已配 `TRADB_API_URL`/`TRADB_COLLECTOR_URL`
  （默认回退同 compose 服务名）+ `extra_hosts: host-gateway`；内嵌 collector/data-api 加【过渡/待退役】注释。
  compose config 通过。
- **任务 6**：`docs/TRADB-DEPLOY.md`（拓扑/前置/5 步切换/回滚/排障表/切换后事项）。

### 【VPS】7-11（2026-09-08 完成，生产环境 host-thu 实跑）

- **任务 7**：VPS 配 git 凭证（token 存 `~/.git-credentials` 600）→ clone `VirtualFormat/tradb`
  到 `/data/apps/tradb`；从 tradeck `.env` 平移数据源密钥 + 生成 web/quant token 配对写入 tradb `.env`（600）。
- **任务 8 决策**：**复用现有数据**（不从零采集）——VPS 有 122G data-pool（分钟K 冷层 + findb
  全量包）+ 6G PG，全部 bind mount，复用成本远低于重灌。tradb 用 `docker-compose.prod.yml`
  （复用现有 PG 数据目录 + data-pool + 运行中的 openbb）。
- **任务 9**：写者切换窗口——停 tradeck collector/data-api（PG 仍在跑保数据）→ 停 tradeck-postgres
  → 起 tradb 全栈。**数据完整接管**（35 表、daily_prices 1372 万行）。踩坑并修复：
  - PG 密码不匹配（tradb `.env` 新密码 ≠ 现有 PG 用户的 `tradeck_dev`，存量数据不改密码）→ 改回。
  - GHCR 镜像私有拉不到（token 无 read:packages）→ 改为 public 后经 nju 代理拉取成功（与 tradeck 一致）。
  - 验：collector 接管写者（跑 indices/news job）、data-api `/health` 200 + 无 token 401 + 对 token 200 返回真实数据。
- **任务 10**：tradeck `.env` 加 TRADB_* + token，compose 同步。**踩坑并修复（真实架构问题）**：
  - web/quant `depends_on: data-api` 连带拉起已停的内嵌 postgres/clickhouse → depends_on 收敛为只依赖 openbb。
  - **loopback 冲突**：tradb data-api 绑 127.0.0.1，web 经 host-gateway（bridge IP）访问不到
    （loopback 仅监听本机）→ 改为 web/quant 加入 tradb 外部网络 `tradb_default`，经容器别名
    `tradb-data-api`/`tradb-collector` 直连，tradb 保持回环绑定不变。
  - web/quant 旧镜像无 token 注入 → 拉含 service-auth 的新镜像重建。
  - 终验：web 代理真实取到 AAPL 数据（带 token）、数据中心面板 200、quant 通 tradb 200、5 关键页面全 200。
- **任务 11**：停 tradeck 内嵌 data-api/collector/postgres/clickhouse。最终形态：
  tradb 全家（postgres/clickhouse/collector/data-api）+ tradeck 消费方（web/quant/nginx/openbb）。
  **端口收窄确认**：data-api 8080 / collector 8082 / web 3000 均只绑 127.0.0.1，对外仅 nginx 443
  （修复了切换前 data-api `0.0.0.0:8080` 全接口暴露无鉴权的问题）。数据持续增长（写者正常）。
- 清理：删除本地临时 token 文件；VPS 登出 GHCR（镜像 public 走 nju 代理无需认证），保留 git 凭证供 tradb 更新。

**待办/后续**：任务 12（tradeck 仓库退役内嵌 apps/backend、apps/data-collector 代码 + CI 调整，
待 tradb 稳定运行一段时间后）；分钟K 温层首启用需手动触发 `minute_warm_backfill` 回填（CH 在线窗口）。

**2026-09-12 补充**：tradeck 根 `docker-compose.yml` 内嵌数据服务（postgres/clickhouse/
openbb/collector/data-api，此前挂 legacy profile）已整体删除，prod 仅剩 web + quant；
同步清理 `clickhouse-data` 卷、web 无引用的 `OPENBB_API_URL` 与过时注释。
`docs/TRADB-DEPLOY.md` 已标注切换完成状态与新回滚前提。
