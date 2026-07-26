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

## 2. 韩国机器部署

前置：机器已装 Docker，域名已挂 Cloudflare 橙云（代理模式），已装 nginx。

```bash
# 1. 拉代码
git clone <repo> && cd tradeck/docker/openbb

# 2. 配海外源 key（免费源可留空）
cp .env.example .env && vim .env

# 3. 起瘦 OpenBB（6900 只绑 127.0.0.1）
docker compose -f docker-compose.overseas.yml up -d --build
curl http://127.0.0.1:6900/openapi.json   # 验证

# 4. 配 nginx（token 鉴权 + 反代）
cp nginx.overseas.conf.example /etc/nginx/conf.d/openbb-overseas.conf
vim /etc/nginx/conf.d/openbb-overseas.conf   # 改 <REPLACE_WITH_TOKEN> 和 server_name
nginx -t && systemctl reload nginx
```

Cloudflare：DNS 指向该机器（橙云开启），SSL 模式建议 **Full**（配 Origin 证书）。

## 3. 国内 backend 接入

在 VPS 的 `.env`（或部署环境）注入：

```bash
OPENBB_OVERSEAS_API_URL=https://<你的CF域名>
OPENBB_OVERSEAS_TOKEN=<与韩国 nginx 一致的 token>
```

`docker-compose.yml` 已透传这两个变量到 backend，重启 backend 生效：

```bash
docker compose up -d backend
```

## 4. 验证

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

## 5. 回滚

海外节点异常时，国内**无需改代码**即可回落：

```bash
# 方式一：清空海外配置，海外源自动回落国内 openbb（行为同未部署）
# 在 VPS .env 注释掉 OPENBB_OVERSEAS_API_URL / OPENBB_OVERSEAS_TOKEN
docker compose up -d backend

# 方式二：仅停韩国节点（backend 收到连接失败 → 返回空 results，等下周期）
# 韩国机器：
docker compose -f docker-compose.overseas.yml down
```

> 回落后海外源（yfinance/sec/fred/federal_reserve/oecd）改由国内 openbb 直接取，国内网络受限时这些源可能超时/空，但**不影响 akshare（A股）**。

## 6. 故障排查

| 现象 | 排查 |
|---|---|
| backend 海外源全空 | 查 `OPENBB_OVERSEAS_API_URL` 是否配、CF 域名是否解析到韩国机器（橙云开启）、`curl https://<CF域名>` 是否通 |
| 全部 401 | token 不一致：核对 VPS `OPENBB_OVERSEAS_TOKEN` == 韩国 nginx `map` 里的值 |
| CF 报 502/521 | origin 未起或 SSL 模式不匹配：`docker compose -f docker-compose.overseas.yml ps` 确认 6900 存活；CF SSL 模式(Flexible=origin HTTP / Full=origin HTTPS)与 nginx listen 端口对齐 |
| 韩国本地 6900 不通 | `docker compose -f docker-compose.overseas.yml logs openbb`；OpenBB 无 `/health`，用 `/openapi.json` 判活 |
| 跨境取数超时 | nginx `proxy_read_timeout` 已放宽到 60s；backend 侧海外超时 20s（`openbb_client.py` `OVERSEAS_TIMEOUT`），必要时调大 |
| A股受影响 | 不应发生。akshare 不在 `OVERSEAS_PROVIDERS`，永远走国内。若受影响先查是否误改分流集合 |

## 7. 相关文件

| 文件 | 作用 |
|---|---|
| `apps/backend/app/openbb_client.py` | 按 provider 分流（海外带 `X-OpenBB-Token`，超时 20s） |
| `apps/backend/app/config.py` | 读 `OPENBB_OVERSEAS_API_URL` / `OPENBB_OVERSEAS_TOKEN` |
| `docker/openbb/Dockerfile.overseas` | 瘦 OpenBB 镜像（无 akshare） |
| `docker/openbb/docker-compose.overseas.yml` | 韩国节点 compose |
| `docker/openbb/nginx.overseas.conf.example` | nginx token 鉴权示例 |
