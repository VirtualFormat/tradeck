# CD 提速方案（tradeck / tradb → host-thu）

> 过程性方案文件。2026-11-06 起草，含实测数据；定案实施后把结论沉淀到 `docs/TRADB-DEPLOY.md`。

## 现状与瓶颈

| 环节 | 实测耗时 | 说明 |
|---|---|---|
| CI 构建（GitHub runner） | 2–3 分钟 | 已有 gha 层缓存，不是瓶颈 |
| ~~sync-tcr~~ | 17 分钟 – 2.5 小时 | prod 不用 TCR，已于 749d47c 删除 |
| CD：prod 经 `ghcr.nju.edu.cn` 拉镜像 | 缓存命中 ~2 分钟；**新镜像卡死** | NJU 未缓存时要回源 ghcr.io，11-06 实测 0 KB/s 持续 10 分钟以上；当天 CD 因拉 api 超时失败 |
| prod 直连 ghcr.io | — | 实测 **6–17 KB/s**，不可用 |

瓶颈只在「大陆 prod 获取新镜像层」这一段。

## 候选方案

### ① prod 临时 registry + runner 经 SSH 隧道推增量层
prod 跑只监听回环的 `registry:2`，GitHub runner `ssh -L` 后 push，prod 从 `127.0.0.1:端口` 拉。
跨境只传变化的层；但走「美国 runner → 大陆」上传方向（与已删除的 sync-tcr 同方向，历史上很慢），**未实测**。

### ② 大陆 self-hosted runner 只跑 deploy job
把一台连 ghcr.io 线路好的大陆机器注册成 runner，执行 `deploy/ship-images.sh` 的逻辑。
开发机实测 save|ssh|load 两个镜像 71 秒；代价是 runner 长期在线与维护。

### ③ 维持现状 + 手动兜底
CD 失败后在开发机执行 `deploy/ship-images.sh`（d5d13f3 / tradb 196d14b）。

### ④ oracle-arm（韩国春川，152.69.239.4）做 GHCR 中转（新增）

#### 实测（2026-11-06，同一个 137 MB 的 ghcr blob：tradb-data-api 最大层）

| 链路 | 结果 |
|---|---|
| oracle-arm → ghcr.io | 冷缓存 3.6 MB/s，热缓存 221 MB/s |
| host-thu ↔ oracle-arm 网络 | RTT 40 ms，丢包 0–20%；host-thu 侧 cubic，oracle 侧 bbr+fq |
| oracle-arm → host-thu 单连接（ssh 管道） | 25 MB：2.8–4 秒（**6–9 MB/s**）；一次 100 MB 遇线路抖动降到 0.55 MB/s |
| oracle-arm → host-thu 4 路并行 | 4×25 MB 共 8.5 秒（合计 **11.7 MB/s**） |
| host-thu → oracle-arm 上行 | 50 MB 3.9 秒（12.7 MB/s） |
| **端到端：host-thu 经 oracle-arm SOCKS 代理下载 ghcr blob** | 3 次 34–39 秒，**3.5–4.0 MB/s**（直连的约 250 倍） |

结论：可行。docker 默认 3 层并行下载，预计整体 ~10 MB/s：tradeck 4 镜像冷拉几分钟，日常增量层几秒到几十秒。
线路偶发抖动（单连接掉到 0.5 MB/s），并行与重试可吸收。

#### 实现方式（推荐 4b）

- **4a 代理 dockerd**：oracle-arm 现有 3x-ui(xray) 开一个入站，prod 跑 xray 客户端，systemd drop-in 给 dockerd 配 `HTTPS_PROXY` + `NO_PROXY`。
  缺点：改 dockerd 环境需重启 dockerd，未开 `live-restore` 时会重启 prod 全部容器；且所有 daemon 出网流量都绕韩国。
- **4b pull-through 缓存 registry（推荐）**：oracle-arm 跑 `registry:2`（`proxy.remoteurl=https://ghcr.io`，缓存落 `/home/ubuntu/apps/ghcr-cache`，96G 盘仅用 5%），
  经现有宿主 nginx 443 暴露为如 `ghcr.zqg.cc.cd`：
  - DNS **灰云直连**（实测走的就是直连链路；橙云回源绕 CF 到大陆的速度未知）→ 证书需 Let's Encrypt，CF Origin CA 不被 docker 信任；
  - nginx `allow 81.68.69.250; deny all;` 只放行 prod，避免被当公共镜像代理滥用；
  - prod 侧零改造：compose 已是 `${GHCR_REGISTRY:-ghcr.nju.edu.cn}`，部署时设 `GHCR_REGISTRY=ghcr.zqg.cc.cd`，不重启 dockerd。
  - 注意 `deploy/deploy-cn.sh` 会 `export GHCR_REGISTRY="${GHCR_REGISTRY:-ghcr.nju.edu.cn}"`，只写进 prod `.env` 不生效（shell 导出变量优先于 .env），需改脚本默认值或在 `deploy.yml` 里传入。
  - 需实测：`latest` tag 更新后缓存能否拿到新 manifest（distribution proxy 对 tag 会回源校验，但要验证）；NJU 保留为回退源。

#### 与其他方案对比

| | ① 隧道推增量 | ② 大陆 runner | ④b oracle 缓存 |
|---|---|---|---|
| 保留 GitHub 托管 CD | 是 | 否（自托管 runner） | 是 |
| 跨境方向 | 美→大陆上传（未测，历史慢） | 无 | 韩→大陆下载（实测 3.5–4 MB/s 单连接） |
| 新增维护 | prod 上临时 registry | 常驻 runner | oracle-arm 上一个容器 + 证书 |
| prod 改动 | 部署脚本 | 部署流程 | 只换 `GHCR_REGISTRY` |

推荐 ④b，③ 保留为手动兜底。
