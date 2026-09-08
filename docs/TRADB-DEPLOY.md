# tradb 独立部署切换指南（VPS 操作手册）

> 把数据服务从「tradeck 内嵌 collector/data-api」切换为「tradb 独立 compose 部署」。
> 任务清单与验收见 `plans/TASKS-TRADB-DEPLOY.md`；架构见 `docs/DATA-SERVICE.md`。
> 本文是 VPS 上的分步操作手册，含回滚与排障。命令假设两个仓库都已 clone 到 VPS。

## 拓扑

```
tradeck (web/quant)                      tradb (独立 compose)
  web  ─┐                                  postgres  :5432 (内部, 不映射)
  quant ─┼─ host.docker.internal ──▶ 127.0.0.1:8080  data-api  (唯一读出口, 鉴权)
        └─ (回环)                            127.0.0.1:8082  collector (唯一写者, 运维API)
                                             127.0.0.1:6900  openbb    (数据源代理)
                                             clickhouse :8123 (温层, 内部, 不映射)
```

要点：tradb 全服务只绑 `127.0.0.1` 回环；tradeck 经 `host.docker.internal:host-gateway`
（compose 已配）访问宿主机 localhost 上的 tradb。postgres/clickhouse 不映射宿主机端口。

## 前置

1. VPS 已 clone：`tradeck`（本仓库）与 `tradb`（`git clone https://github.com/VirtualFormat/tradb.git`）。
2. tradb 镜像已构建发布（CI `app-images.yml`，GHCR `ghcr.nju.edu.cn/virtualformat/tradb-*`）。
3. 准备 token：每个消费方一把 `openssl rand -hex 32`，web 与 quant 各一。

## 步骤 1 — 配置 tradb `.env`

```bash
cd tradb
cp .env.example .env
```

编辑 `.env`（关键项）：
- `POSTGRES_PASSWORD`：生产强密码（替换开发默认值）。
- `SERVICE_TOKENS={"<web_token>":"web-bff","<quant_token>":"quant"}`：填入刚生成的 token。
- `DATA_SYNC_TOKEN`：数据中心手动同步令牌（与 tradeck 侧一致）。
- 数据源密钥：`FINDB_KEY` / `HITHINK_FINANCE_API_KEY` / `TICKFLOW_API_KEY` 等（从 tradeck 现 `.env` 平移）。

## 步骤 2 — 数据迁移决策（二选一）

- **A. 新卷从零采集（推荐，最简）**：tradb 用全新 PG 卷 + 新 data-pool，启动后 collector
  自动全量初始化（日K ~250 天 + 分钟K 缺口追赶）。首次就绪需数十分钟，期间 data-api 优雅降级。
- **B. 复用现有数据**：把 tradeck 的 PG 数据目录与 `data-pool/` 挂到 tradb（停 tradeck 内嵌
  postgres 后），tradb 的 `./data-pool` 指向同一目录、PG 卷复用。省去重新采集，但要小心
  两套服务不能同时写同一库（铁律二单一写者）。

> 建议先 A 跑通，稳定后再考虑是否迁移历史数据。

## 步骤 3 — 启动 tradb

```bash
cd tradb
bash deploy/deploy-cn.sh        # 拉镜像 + compose up（经南京大学镜像站）
docker compose ps                # 5 容器健康：postgres/clickhouse/openbb/collector/data-api
curl http://127.0.0.1:8080/health            # -> {"status":"ok"}
curl http://127.0.0.1:8080/api/quotes        # -> 401（鉴权生效）
curl -H "X-Service-Token: <web_token>" http://127.0.0.1:8080/api/quotes   # -> 200（可能空，采集中）
```

## 步骤 4 — 切换 tradeck 到 tradb

编辑 tradeck `.env`：
```bash
TRADB_API_URL=http://host.docker.internal:8080
TRADB_COLLECTOR_URL=http://host.docker.internal:8082
TRADB_SERVICE_TOKEN=<web_token>
QUANT_SERVICE_TOKEN=<quant_token>
```

重启 web/quant：
```bash
cd tradeck
bash deploy/deploy-cn.sh        # 或 docker compose up -d web quant
```

验证：web 首页/个股页/宏观页渲染正常、数据中心面板任务状态正常（数据来自 tradb）。

## 步骤 5 — 停用 tradeck 内嵌数据服务

确认步骤 4 全链路正常后：
```bash
cd tradeck
docker compose stop collector data-api postgres clickhouse
# 观察 web 仍正常后，可选 docker compose rm -f collector data-api
```

> ⚠️ 若步骤 2 选 B（复用 PG/data-pool），不要删卷；仅停容器。

## 回滚

- **步骤 4 出问题**：把 tradeck `.env` 的 `TRADB_API_URL`/`TRADB_COLLECTOR_URL` 删去（回退默认
  值 `http://data-api:8080` 同 compose 服务名），重启 web/quant 即回到内嵌模式。内嵌服务在
  步骤 5 前一直保持运行，回滚零数据风险。
- **步骤 5 后回滚**：`docker compose up -d collector data-api postgres clickhouse` 重启内嵌服务 +
  回退 `.env`。

## 排障

| 现象 | 排查 |
|---|---|
| web 全站 401 | tradeck `.env` 的 `TRADB_SERVICE_TOKEN` 与 tradb `SERVICE_TOKENS` 的 web-bff token 不一致 |
| web 取数为空但无 401 | tradb collector 还在初始化采集（看 `docker logs tradb-collector`）；或数据源限流 |
| web 连不上 tradb | `docker exec tradeck-web curl -s http://host.docker.internal:8080/health`；确认 extra_hosts host-gateway 生效 |
| tradb data-api 起不来 | `docker logs tradb-data-api`；多为 PG 未健康或 DATABASE_URL 密码错 |
| collector 不写库 | `docker logs tradb-collector`；确认 DATA_MODE=live、scheduler 已注册 job |

## 切换后

- tradeck 仓库内嵌 `apps/backend` / `apps/data-collector` 代码退役删除（另一迭代，见任务 12）。
- 分钟K 冷层暂留本地 `tradb/data-pool`，数据量上来后迁 COS（4.2b，见 `docs/DATA-STORAGE-TIERED.md`）。
