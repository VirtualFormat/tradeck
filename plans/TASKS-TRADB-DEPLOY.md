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
| 7 | 【VPS】克隆/拉取 tradb 仓库 + 填 `.env`（SERVICE_TOKENS / 数据源密钥 / POSTGRES 密码） | 【VPS】 | tradb `.env` 就绪 | ⬜ |
| 8 | 【VPS】数据迁移决策：tradb 用新卷从零采集，还是挂载/迁移现有 PG + data-pool | 【VPS】 | 决策记录 + 数据可用 | ⬜ |
| 9 | 【VPS】起 tradb（`deploy/deploy-cn.sh`），确认 5 容器健康 + data-api 带 token 通 | 【VPS】 | health 全绿 + token 冒烟通过 | ⬜ |
| 10 | 【VPS】tradeck 切到 tradb：改 `.env` 的 TRADB_* + token，`deploy/deploy-cn.sh` 重启 web/quant | 【VPS】 | web 首页/个股页渲染正常、数据来自 tradb | ⬜ |
| 11 | 【VPS】停掉 tradeck 内嵌 collector/data-api/postgres/clickhouse（确认 tradb 接管后） | 【VPS】 | 内嵌服务已停、web 仍正常 | ⬜ |
| 12 | tradeck 仓库退役内嵌 data-api/collector 代码（tradb 稳定运行后；另一迭代） | 【我准备】 | 代码删除 + CI 调整 | ⬜ |

## 回滚方案（贯穿 9-11）

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

### 【VPS】7-11

待 VPS 执行（按 `docs/TRADB-DEPLOY.md` 操作）。
