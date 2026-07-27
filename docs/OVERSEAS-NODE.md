# 海外节点部署（韩国瘦 OpenBB）

## 1. 为什么

国内 VPS 访问 OpenBB 海外数据源（yfinance/sec/fred/federal_reserve/oecd）受限。
在韩国机器部署一个**瘦 OpenBB**（不含 akshare），国内 backend 按数据源分流：
海外源走韩国，akshare 走国内。

```
国内 backend
  ├─ 海外 provider → https://<CF域名> → CF橙云 → 韩国 nginx(校验 X-OpenBB-Token) → 韩国瘦 OpenBB → 海外源
  └─ akshare       → 国内 openbb:6900 → akshare 直连
```

分流逻辑内聚在 `apps/backend/app/openbb_client.py` 的 `fetch_openbb`，按 `params["provider"]` 判定。
不配置海外节点时全部回落国内，行为不变。

## 2. 生成鉴权 token

backend 请求头带 `X-OpenBB-Token`，韩国 nginx 逐字比对，一致才放行到瘦 OpenBB，否则 401。
同一个 token 填两处（韩国 nginx + 国内 backend `.env`），必须完全一致。

```bash
openssl rand -hex 32
```

产出 64 位十六进制串（256 bit 熵）。用 `-hex` 而非 `-base64`：纯 `[0-9a-f]`，
避免特殊字符在 nginx/shell/URL 里转义踩坑。

> token 明文只存 backend 运行环境的 `.env` 和韩国 nginx conf，**不写入受 git 追踪的文件**（本仓库 public）。
> 轮换：重新 `openssl rand -hex 32`，改下面两处并各自 reload/重启即可，无需重建容器。

## 3. 韩国机器部署

前置：机器已装 Docker，域名已挂 Cloudflare 橙云（代理模式），已有一套 nginx（本节点**复用现有共享 nginx**，不另起）。

瘦 OpenBB 镜像由 CI 多架构构建（amd64+arm64）发布到 `ghcr.io/virtualformat/tradeck-openbb-overseas`，
韩国机直接 pull 预构建镜像，不本地 build（package 为 public 时免登录）。

**起瘦 OpenBB 容器**（`~/apps/openbb/`，6900 只绑 127.0.0.1，供 nginx upstream）：

```yaml
# ~/apps/openbb/docker-compose.yml
services:
  openbb:
    image: ghcr.io/virtualformat/tradeck-openbb-overseas:edge
    container_name: openbb-overseas
    restart: unless-stopped
    ports: ["127.0.0.1:6900:6900"]
    env_file: .env          # 海外源 key，免费源可留空
    volumes: ["openbb-config:/root/.openbb_platform"]
volumes: { openbb-config: {} }
```

```bash
cd ~/apps/openbb
docker compose pull && docker compose up -d
curl -s http://127.0.0.1:6900/openapi.json -o /dev/null -w "%{http_code}\n"   # 期望 200
```

**加 nginx 站点**（复用共享 nginx 的通配证书 + snippet），`~/apps/nginx/conf.d/openbb.conf`：

```nginx
upstream openbb_overseas { server 127.0.0.1:6900; keepalive 16; }

server {
    listen 80; listen [::]:80;
    server_name <CF域名>;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl; listen [::]:443 ssl; http2 on;
    server_name <CF域名>;

    ssl_certificate     /etc/nginx/certs/origin.pem;
    ssl_certificate_key /etc/nginx/certs/origin.key;
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/security-headers.conf;

    # 用 if 直接比对，勿用 map：64hex 键会撞 map_hash_bucket_size 限制
    if ($http_x_openbb_token != "<TOKEN>") { return 401; }

    location / {
        proxy_pass http://openbb_overseas;
        include /etc/nginx/snippets/proxy-common.conf;   # 已含 300s 超时
    }
}
```

```bash
docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

Cloudflare：DNS 指向该机器（橙云开启），SSL 模式 **Full**（复用现有 CF Origin 证书）。

## 4. 国内 backend 接入

在 VPS 项目根 `.env`（被 gitignore 忽略）注入：

```bash
OPENBB_OVERSEAS_API_URL=https://<你的CF域名>
OPENBB_OVERSEAS_TOKEN=<与韩国 nginx 一致的 token>
```

`docker-compose.yml` 已用 `${OPENBB_OVERSEAS_TOKEN:-}` 透传到 backend，重启生效：

```bash
docker compose up -d backend
```

## 5. 验证

- 触发海外源 job（如 macro / yfinance quotes），确认数据落库。
- 触发 akshare job，确认仍走国内、不受影响。
- 填错 token：backend 收到 401 → `fetch_openbb` 返回空 results，不抛异常、不影响 akshare（降级：不回退，等下周期重试）。

具体验证命令：

```bash
# 韩国机器本地（应 200）
curl -s http://127.0.0.1:6900/openapi.json -o /dev/null -w "%{http_code}\n"

# 经 nginx + 正确 token（应 200）
curl -s -H "X-OpenBB-Token: <TOKEN>" https://<CF域名>/api/v1/equity/price/quote?provider=yfinance\&symbol=AAPL -o /dev/null -w "%{http_code}\n"

# 无 token / 错 token（应 401）
curl -s https://<CF域名>/api/v1/equity/price/quote?provider=yfinance\&symbol=AAPL -o /dev/null -w "%{http_code}\n"

# 国内 backend 侧确认海外源落库
docker compose logs -f backend | grep -iE "macro|quotes|overseas"
```

## 6. 回滚

海外节点异常时，国内**无需改代码**即可回落：

```bash
# 方式一：清空海外配置，海外源自动回落国内 openbb（行为同未部署）
# 在 VPS .env 注释掉 OPENBB_OVERSEAS_API_URL / OPENBB_OVERSEAS_TOKEN
docker compose up -d backend

# 方式二：仅停韩国节点（backend 收到连接失败 → 返回空 results，等下周期）
# 韩国机器：
cd ~/apps/openbb && docker compose down
```

> 回落后海外源（yfinance/sec/fred/federal_reserve/oecd）改由国内 openbb 直接取，国内网络受限时这些源可能超时/空，但**不影响 akshare（A股）**。

## 7. 故障排查

| 现象 | 排查 |
|---|---|
| backend 海外源全空 | 查 `OPENBB_OVERSEAS_API_URL` 是否配、CF 域名是否解析到韩国机器（橙云开启）、`curl https://<CF域名>` 是否通 |
| 全部 401 | token 不一致：核对 VPS `OPENBB_OVERSEAS_TOKEN` == 韩国 nginx conf 里 `if` 比对的值 |
| CF 报 502/521 | origin 未起或 SSL 模式不匹配：`docker ps` 确认 openbb-overseas 6900 存活；CF SSL 模式与 nginx listen 端口对齐（Full=origin HTTPS） |
| 韩国本地 6900 不通 | `cd ~/apps/openbb && docker compose logs openbb`；OpenBB 无 `/health`，用 `/openapi.json` 判活 |
| nginx -t 报 map_hash | 勿用 `map` 匹配 64hex token（撞 `map_hash_bucket_size`）；改用 `if ($http_x_openbb_token != "...")` |
| 跨境取数超时 | nginx `proxy-common.conf` 读超时 300s；backend 侧海外超时 20s（`openbb_client.py` `OVERSEAS_TIMEOUT`），必要时调大 |
| A股受影响 | 不应发生。akshare 不在 `OVERSEAS_PROVIDERS`，永远走国内。若受影响先查是否误改分流集合 |

## 8. 相关文件

| 文件 | 作用 |
|---|---|
| `apps/backend/app/openbb_client.py` | 按 provider 分流（海外带 `X-OpenBB-Token`，超时 20s） |
| `apps/backend/app/config.py` | 读 `OPENBB_OVERSEAS_API_URL` / `OPENBB_OVERSEAS_TOKEN` |
| `docker/openbb/Dockerfile.overseas` | 瘦 OpenBB 镜像（无 akshare） |
| `.github/workflows/openbb-images.yml` | CI 多架构构建并发布主/从镜像到 GHCR（amd64+arm64） |
