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

## 5. 相关文件

| 文件 | 作用 |
|---|---|
| `apps/backend/app/openbb_client.py` | 按 provider 分流（海外带 `X-OpenBB-Token`，超时 20s） |
| `apps/backend/app/config.py` | 读 `OPENBB_OVERSEAS_API_URL` / `OPENBB_OVERSEAS_TOKEN` |
| `docker/openbb/Dockerfile.overseas` | 瘦 OpenBB 镜像（无 akshare） |
| `docker/openbb/docker-compose.overseas.yml` | 韩国节点 compose |
| `docker/openbb/nginx.overseas.conf.example` | nginx token 鉴权示例 |
