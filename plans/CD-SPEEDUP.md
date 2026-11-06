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

#### 已有设施：`ghcr.zqg.cc.cd`（2026-08 部署，橙云）

oracle-arm 上**早已运行 pull-through 缓存**：容器 `ghcr-proxy`（`registry:2`，`127.0.0.1:5000`），
宿主 nginx `conf.d/ghcr-proxy.conf` 以 `ghcr.zqg.cc.cd` 暴露，CF 橙云接入（边缘证书公网可信，docker 直接可用）。
但 prod 一直没用它：两个仓库的 `deploy-cn.sh` 和 compose 默认值仍是 `ghcr.nju.edu.cn`。

11-06 实测（host-thu 经橙云）：

| 测试 | 结果 |
|---|---|
| `/v2/` 与 manifest 请求 | 200，每次约 2.5 s（CF 往返） |
| 137 MB blob 单连接 ×3 | 47–116 秒，**1.2–2.9 MB/s**（波动大，约为灰云直连的一半） |
| 真实 `docker pull ghcr.zqg.cc.cd/virtualformat/tradeck-api:latest` | **98 秒**，镜像 ID 与当天 CI 产物一致 → `latest` 会回源刷新 |

443 已被橙云站点占用并不妨碍灰云：橙/灰是按 DNS 记录区分的，nginx 按 `server_name` 分流，同一 443 可并存。

#### 实现路线

1. **立即可用**：CD 改用 `GHCR_REGISTRY=ghcr.zqg.cc.cd`（两个仓库 `deploy-cn.sh` 默认值 / compose 默认值），NJU 降为回退。
   注意 `deploy-cn.sh` 会 `export GHCR_REGISTRY="${GHCR_REGISTRY:-ghcr.nju.edu.cn}"`，只改 prod `.env` 不生效（shell 导出变量优先于 .env）。
2. **可选提速约 2 倍**：新增灰云记录（如 `ghcr-kr.zqg.cc.cd` → 152.69.239.4，直连实测 3.5–4 MB/s），
   nginx 复用 `ghcr-proxy` upstream，证书改 Let's Encrypt（CF Origin CA 不被 docker 信任），
   并 `allow 81.68.69.250; deny all;` 只放行 prod，避免灰云暴露源站被当公共镜像代理。
3. 不推荐 4a（dockerd 走 xray 代理）：改 dockerd 环境需重启 dockerd，未开 `live-restore` 会重启 prod 全部容器。

#### 与其他方案对比

| | ① 隧道推增量 | ② 大陆 runner | ④ oracle 缓存（已有） |
|---|---|---|---|
| 保留 GitHub 托管 CD | 是 | 否（自托管 runner） | 是 |
| 跨境方向 | 美→大陆上传（未测，历史慢） | 无 | 韩→大陆下载（橙云 1.2–2.9 MB/s，灰云 3.5–4 MB/s） |
| 新增维护 | prod 上临时 registry | 常驻 runner | 无（已部署） |
| prod 改动 | 部署脚本 | 部署流程 | 只换 `GHCR_REGISTRY` |

推荐 ④：先直接切到现有 `ghcr.zqg.cc.cd`，再视需要加灰云直连；③ 保留为手动兜底。
