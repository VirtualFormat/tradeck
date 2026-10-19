# MCP 接入（策略上传与回测）

> 定案方案。小范围（2-3 名受邀用户）经 MCP 客户端以个人访问令牌（PAT）连接 quant，
> 完成「读指南 → 校验 → 保存策略 → 任务化回测 → 取结果」闭环。
> 配套文件：任务拆解与验收见 `plans/TASKS-MCP.md`；用户身份体系见 `AUTH.md`。

## 定位

quant 此前只服务 web（浏览器 → web BFF → quant），且存在三处「仅靠内网 + 邀请制登录挡住」的假设：
quant 不鉴权来访者、`X-User-Id` 头无条件采信、用户策略在 quant 进程内直接 `exec`。
MCP 令牌长期有效、存于客户端配置、由 agent 自动调用（可能被提示注入操纵），泄露面远大于浏览器 session，
因此本方案分两部分：**先加固 quant（P0），再开放 MCP（P1 令牌 + P2 服务）**。

设计取向：

- **独立 MCP 服务**（`apps/mcp`）：公网入口与计算服务分离，quant 只留内网；鉴权、配额、审计、故障域与 quant 隔离。
- **PAT 而非 OAuth**：沿用 `AUTH.md` 的「服务端可撤销、DB 只存哈希」理念；OAuth 2.1 留待 AUTH P2 统一规划。
- **轻量沙箱**：小范围可信用户，防护重点是「令牌泄露后不能直接拿到密钥与 root 执行」，不追求防恶意租户的强隔离。

## 架构

```
MCP 客户端（IDE / CLI agent）
  │  HTTPS  Authorization: Bearer tdk_pat_xxx
  ▼
Cloudflare → nginx（host-thu，host 网络）
  ├─ /                                      → web  127.0.0.1:3000
  └─ /mcp、/.well-known/oauth-protected-resource/mcp → mcp  127.0.0.1:8084
                                               │ ① POST api:8080/api/auth/tokens/verify（X-Service-Token: mcp）
                                               │    → {user_id, scopes, expires_at}
                                               │ ② quant:8083（X-Service-Token: mcp + X-User-Id: u<id>）
                                               ▼
浏览器 → web BFF ──（X-Service-Token: web-bff + X-User-Id: u<id>）──→ quant :8083（仅容器网络 / 回环）
                                               │
                                               └─ 用户策略只在 worker 子进程执行（干净环境 + nobody）
```

链路要点：

- mcp 只接 default 网络（与 api/quant 同网），不接 tradb_net；宿主机端口只绑回环，经 nginx 对外。
- **用户身份只来自令牌**：mcp 从 verify 结果取 `user_id`，绝不从工具参数读用户。
- quant 只采信持有效入站服务令牌的 `X-User-Id`；web 与 mcp 是仅有的两个消费方。

## 三层身份

| 层 | 凭证 | 回答的问题 | 校验方 |
|---|---|---|---|
| 用户 session | `tdk_session` cookie | 浏览器后面是谁 | api `/api/auth/session` |
| 个人访问令牌 | `tdk_pat_<随机串>` Bearer | MCP 客户端代表谁、能做什么（scope） | api `/api/auth/tokens/verify` |
| 服务令牌 | `X-Service-Token` | 哪个服务在调（web-bff / mcp） | quant 入站中间件、api `SERVICE_TOKENS` |

用户 id 统一为 `u<auth.users.id>`（满足 quant `^[A-Za-z0-9_-]{1,32}$`），web 与 mcp 同口径，
同一用户经两条链路看到同一套策略/因子/候选库。

## P0 quant 加固

| 项 | 内容 |
|---|---|
| 端口收口 | prod compose quant 端口改 `127.0.0.1:8083:8083`（Docker 端口映射绕过宿主机防火墙，0.0.0.0 即公网可达，取决于云安全组）；`deploy-cn.sh` 健康检查本就走回环 |
| 入站鉴权 | `INBOUND_SERVICE_TOKENS`（JSON `{"<token>": "<consumer>"}`，与 api `SERVICE_TOKENS` 同格式；prod `.env` 变量名 `QUANT_INBOUND_SERVICE_TOKENS`）。配置后除 `/health` 外一律要求有效 `X-Service-Token`，且必须带 `X-User-Id`（不再回落 default）；为空时放行并保持旧回落行为（dev 兼容）；**非空但非法时 fail-closed**（非探活请求 503，启动日志 error），不静默降级为放行 |
| 用户透传 | web 新增 `quantFetch()`，统一注入服务令牌 + `X-User-Id: u<id>`；全部 `/api/quant/*` 代理路由改用它 |
| default 迁移 | `QUANT_MIGRATE_DEFAULT_TO=u<id>`：启动时把 `users/default/` 整目录改名为目标用户目录（目标已存在则跳过并告警，幂等） |
| 任务归属 | 回测/AI 任务登记 owner；poll/cancel 非本人一律 404（不泄露存在性）；每用户活跃任务上限 `QUANT_MAX_CONCURRENT_PER_USER`（默认 2）。额度按「执行协程仍在」计：运行中任务被取消后额度保留到协程退出（防创建→取消循环堆积 LLM 调用）；`/api/backtest/run` 在预拉前**预占**名额；同步 `/api/backtest` 同样计入额度。web 代理对 4xx（含 429）原样透传，前端只在网关错误时回退旧接口 |
| 轻量沙箱 | 见下节 |
| validator 修正 | scoring 允许本人 active 用户因子；放行 `params["__user_factor_values__"]` 下标；禁止一切双下划线名称（`__builtins__["exec"]` 可绕过调用名检查直取 exec；`__name__ = "__main__"` 可让自测块在加载时执行），`if __name__ == "__main__"` 给出专门提示 |
| symbol 白名单 | 请求 symbols 必须匹配 `^[A-Z0-9.-]{1,20}$`（与 tradb data-api 同规则）：symbol 直接拼进缓存文件名，未收口时可路径穿越写到缓存目录外（MCP review 发现，web 链路同样可触发）；web `parseSymbols` 同步归一大写 |
| 新接口 | `POST /api/strategies/validate`（校验 + 沙箱试加载，不落盘）；`GET /api/strategies/errors`（本人 custom/ai 加载错误，只给文件名）；`GET /api/strategies/guide`（精简指南，供 MCP `get_strategy_guide`）。不改 `/api/strategies` 响应结构 |

### 轻量沙箱

威胁：validator 是纯 AST 白名单，挡不住 numpy/polars 自身的能力。已实测可过静态校验的写法包括
`np.ctypeslib.ctypes.CDLL(None)`（任意 libc 调用）、`np.loadtxt("/proc/self/environ")`、
`pl.read_csv("/etc/passwd")`、`np.save(任意路径)`。原状下用户代码在 quant 主进程（root、持有
`AI_API_KEY` / tradb `SERVICE_TOKEN`）中执行，且保存失败时异常原文回显，可作为数据外带通道。
另外旧 worker 用 multiprocessing Queue（pickle）回传结果：被攻破的子进程可伪造 pickle 消息，
在父进程反序列化时执行任意代码——只给子进程降权不够，回传通道必须换。

实现（`app/sandbox.py`）：

1. **主进程不执行 custom/ai 策略代码**：API / 定时 job 的注册表为 `sandbox=True`，custom/ai 只用
   AST 解析 META，`compute_fn` 为占位函数——主进程误调抛 `SandboxViolation`，且
   `registry.run` 不把它吞成空信号（漏改的路径会立刻暴露）。builtin 照旧 import。
2. **执行路径一律进沙箱子进程**：回测（同步/任务）、选股、优化/敏感性/walk-forward
   （用户策略取消小网格进程内捷径）、保存与校验的试加载（真实 import + 80×3 合成矩阵试跑
   compute，校验返回类型与形状）、每日信号 job、含非 builtin 子策略的 composite。
   判定入口 `StrategyRegistry.needs_sandbox()`。
3. **子进程**：`subprocess.Popen` 以 `python -E -B -m app.sandbox` 启动——环境变量从白名单重建
   （密钥不进子进程）；quant 为 root 时 `user/group=QUANT_SANDBOX_UID`、`extra_groups=[]`
   在 exec 前降权（默认 65534）；独立进程组，取消/超时整组 SIGKILL；子进程最先设置
   `RLIMIT_FSIZE=0`（禁写文件内容）与 `RLIMIT_CORE=0`。
4. **协议**：父 → 子 pickle（子进程信任父进程）；子 → 父只走独立管道上的 JSON 行，
   父进程只还原日期标记，不构造任何其他类型；单条消息有上限。
5. 错误回显截断到 2KB（便于 agent 自修，又不成为大块外带通道）；`/api/strategies/errors`
   只返回文件名，不暴露服务端路径。
6. **池位与线程桥**：worker 池并发闸为进程级 `threading.BoundedSemaphore`（跨事件循环有效；旧的按 loop
   重建 asyncio.Semaphore 会被优化路径打穿）；异常经参数传回事件循环（旧闭包引用 except 变量会在
   回调里 NameError，future 永不完成 → 池位与任务永久泄漏，review 确认的 critical）。
7. **试加载**：260×40 合成矩阵；compute 运行期异常与运行时同口径只告警（不拒存）；返回类型/形状不符、
   执行后 META 与静态解析不一致才拒；独立并发闸 2（繁忙 429）、超时 15s。validator 另禁止重复定义或
   修改 META。
8. **资源**：单条回传消息上限 32MB；Popen 失败关闭管道读端；子进程 WARNING 日志回收转写父进程 logger。
9. **注册表并发**：poll/cancel 同步端点在线程池执行，与事件循环上的执行协程真并发，任务注册表所有公开方法经
   同一把 `threading.RLock` 串行化。
10. **validator 补充**：导入名与 `as` 别名同样拦下划线前缀（`from numpy import __builtins__ as b` 曾可绕过）、
    禁通配导入；声明式 composite 不要求 compute。保存时 custom/ai 与 builtin 同 id 一律 409。

已在 quant 镜像内以 root 验收：子进程 uid=65534、环境变量仅 5 个白名单项、读不到
`/proc/1/environ`、写不了缓存目录；root 落盘的策略与缓存（0644/0755）可被子进程读取，回测正常。

已知边界（小范围可接受，后续收紧）：子进程仍可访问网络；可读全部缓存（行情 + 他人策略源码，文件 644）；
写坏的策略可占满 worker 池（单 worker 串行，由超时与容器 2g 内存兜底）；非 builtin 策略每次
选股/试加载多一次子进程启动开销（约 0.2s + 矩阵构建）。
后续方向：seccomp 禁 socket/execve、独立 `network_mode: none` 沙箱容器 + 缓存只读挂载、按用户目录权限。

## P1 个人访问令牌

表结构（`auth_main.py` `_SCHEMA_DDL` 幂等建表，`init.sql` auth 段同步）：

```sql
CREATE TABLE IF NOT EXISTS auth.api_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL,        -- 展示用，如 tdk_pat_ab12
    token_hash TEXT NOT NULL UNIQUE,   -- sha256(token) hex，绝不存明文
    scopes TEXT[] NOT NULL,            -- strategy:read / strategy:write / backtest
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,   -- 默认 90 天，上限 365 天
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
```

| 端点 | 鉴权 | 说明 |
|---|---|---|
| `POST /api/auth/tokens` | session | 签发；明文仅本次返回；每人有效令牌 ≤5 |
| `GET /api/auth/tokens` | session | 列出本人令牌（前缀/scope/到期/最近使用） |
| `DELETE /api/auth/tokens/{id}` | session | 只能撤销自己的 |
| `POST /api/auth/tokens/verify` | 服务令牌，消费方须为 `mcp`（env 与 DB 两条服务令牌通道都校验） | 返回 user_id/scopes/expires_at/token_id；格式不符/已撤销/过期/用户禁用/名单外一律 401 同文案；`last_used_at` 节流到每分钟一次 |

- 令牌格式 `tdk_pat_` 前缀 + 32 字节 urlsafe 随机串：固定前缀便于密钥扫描识别，与 session token 区分。
- `PAT_ALLOWED_USER_IDS`（逗号分隔 auth.users.id）：非空时仅名单内用户可签发——小范围使用的门禁。
- web 「API 令牌」设置页 `/settings/tokens`（用户菜单入口）：shadcn Table/Dialog/Checkbox/Select，空态走 `empty-state.tsx`；
  BFF 路由 `/api/account/tokens`（不放 `/api/auth/*`：middleware 豁免该前缀，放那里就失去登录保护）。
- `PAT_ALLOWED_USER_IDS` 语义：未配置 = 全部登录用户；配置了但无合法 id = 拒绝所有人（fail-closed，防误写成 `u1` 形态导致门禁静默失效）。

## P2 MCP 服务（apps/mcp）

选型：Python 3.12 + 官方 MCP SDK v2（锁定 `mcp==2.3.0`；v1 的 `mcp.server.fastmcp` 在 v2 已移除，
导入 `from mcp.server.mcpserver import MCPServer`；HTTP 客户端随 SDK 用 `httpx2`）。镜像以非 root（uid 10001）运行。

- `MCPServer(..., token_verifier=PatVerifier(), auth=AuthSettings(issuer_url, resource_server_url, validate_token_resource=True))`，
  两参数必须同时传。
- `streamable_http_app(stateless_http=True, json_response=True, transport_security=TransportSecuritySettings(allowed_hosts=[公网域名]))`：
  **不配 allowed_hosts 时带真实 Host 的请求一律 421**。无状态 + JSON 响应，不依赖长连接，过 CF 稳定。
- 挂载到外层 Starlette 时 lifespan 必须 `async with mcp.session_manager.run()`。
- 工具内 `get_access_token()` 取身份（verifier 把 `u<id>` 放在 `subject`/`client_id`）。
- `/health` 挂外层 app（不鉴权，供 `deploy-cn.sh` 探活）。
- verify 结果按 token 哈希缓存 30 秒（失败缓存 5 秒）：撤销最迟 30 秒生效。
- 超时预算：PAT 校验 10s + quant 读 70s ≤ nginx 90s < CF 100s；`get_backtest_result` 长轮询单独 20s/请求。
  超时与「不可用」分开提示（超时时 save/run 可能已在后台执行，提示先查再重试）。
- quant 401/403（mcp 自身服务令牌配错）对 agent 只回通用「暂不可用」，详情只进日志。
- `required_scopes` 不全局设置（否则 HTTP 层对 `tools/list` 也 403），每个工具内按 scope 校验。
- server `instructions` 写明：先调 `get_strategy_guide`；import 仅 polars/numpy/datetime；先 validate 再 save；回测提交后轮询。

### 工具

| 工具 | scope | quant 端点 | 说明 |
|---|---|---|---|
| `get_strategy_guide` | strategy:read | `GET /api/strategies/guide` | 策略协议 + import 白名单（精简指南单一来源在 quant） |
| `list_strategies` | strategy:read | `GET /api/strategies` + `/api/strategies/errors` | 附本人加载错误 |
| `get_strategy_code` | strategy:read | `GET /api/strategies/{id}/code` | |
| `validate_strategy` | strategy:write | `POST /api/strategies/validate` | 不落盘；会执行代码故归 write；代码 ≤200KB |
| `save_strategy` | strategy:write | `POST /api/strategies/save` | `overwrite_id` 覆盖/改名；builtin 409 透传 |
| `run_backtest` | backtest | `POST /api/backtest/run` | 立即返回 task_id；禁 `universe=all`；symbols 本地白名单 + 大写去重；两者都空时显式下发 `hs300`（与 web 默认一致） |
| `get_backtest_result` | backtest | `GET /api/backtest/task/{id}` | `wait_seconds≤50` 长轮询；默认摘要（≤10KB），`section=trades|per_symbol|equity` + `offset/limit` 分页 |
| `cancel_backtest` | backtest | `POST /api/backtest/task/{id}/cancel` | |

回测走「提交 + 轮询」而非一次挂住：全市场回测分钟级，CF 免费版 100 秒断连接。
结果默认裁剪：原始结果含逐日净值、逐笔交易、数百标的统计，整包会撑爆 agent 上下文。

### 配额

| 维度 | 上限 | 落点 |
|---|---|---|
| 每令牌调用 | 60 次/分钟 | mcp 进程内 |
| 每用户回测提交 | 30 次/小时 | mcp 进程内 |
| 每用户活跃任务 | 2（`QUANT_MAX_CONCURRENT_PER_USER`，回测 + AI 生成合计） | quant 任务注册表（web 同样受益） |
| universe | 禁 `all` | mcp 工具参数校验（全市场矩阵曾 OOM，2026-09-22） |

### 部署

- compose：`mcp` 服务（mem_limit 256m，`127.0.0.1:8084:8084`，只接 default 网络，`depends_on: api healthy`）。
- CI：`app-images.yml` 三处镜像矩阵加 `tradeck-mcp`；`deploy-cn.sh` 拉取循环与健康检查加 mcp。
- nginx：`location /mcp` 与 `location = /.well-known/oauth-protected-resource/mcp` 反代 8084，
  `proxy_read_timeout 90s`（短于 CF 100s）、`proxy_buffering off`、`client_max_body_size 1m`。
- CF：上线前 curl 实测 `/mcp`，若被质询（HTML/403）需关 Bot Fight Mode 或加跳过规则。

客户端配置示例（字段名因客户端而异）：

```json
{
  "mcpServers": {
    "tradeck": {
      "type": "http",
      "url": "https://tradeck.virtualformat.cn/mcp",
      "headers": { "Authorization": "Bearer tdk_pat_xxx" }
    }
  }
}
```

## 环境变量

| 服务 | 变量 | 说明 |
|---|---|---|
| quant | `INBOUND_SERVICE_TOKENS`（`.env` 名 `QUANT_INBOUND_SERVICE_TOKENS`） | 入站服务令牌 JSON；空 = 不鉴权（dev） |
| quant | `QUANT_MIGRATE_DEFAULT_TO` | `u<管理员 id>`；空 = 不迁移 |
| quant | `QUANT_MAX_CONCURRENT_PER_USER` | 每用户活跃任务上限，默认 2（沿用原预留配置名） |
| quant | `QUANT_SANDBOX_UID` | 子进程降权 uid，默认 65534；0 = 不降权 |
| web | （复用 `TRADB_SERVICE_TOKEN`） | web 调 quant 沿用 `serviceAuthHeaders()`，quant 入站配置中该值映射 `web-bff`（与 AUTH.md 复用同一把的取舍一致） |
| api | `SERVICE_TOKENS` 追加 mcp | `{"<web token>": "web-bff", "<mcp token>": "mcp"}` |
| api | `PAT_ALLOWED_USER_IDS` | 可签发 PAT 的用户 id 名单；空 = 全部登录用户 |
| mcp | `MCP_SERVICE_TOKEN` / `AUTH_API_URL` / `QUANT_API_URL` / `MCP_PUBLIC_URL` | |

## 上线顺序

CD 只拉镜像重建，**不下发 compose / .env / nginx / deploy-cn.sh**（见 `.github/workflows/deploy.yml`），
标注「VPS 手工」的步骤需人工同步。prod 日常使用账号为 `auth.users.id = 2`（role=user，quant 用户 id `u2`）；
管理员 `id = 1` 默认不使用，迁移后其命名空间为空属预期。

本次改动作为一个整体推送（沙箱/PAT/MCP 代码同批进镜像），部署分三步：

| 步骤 | 时机 | VPS 手工 |
|---|---|---|
| ① 预置 `.env` | **推代码之前** | `QUANT_MIGRATE_DEFAULT_TO=u2`（web 一旦透传 `X-User-Id`，未迁移的策略就对日常账号不可见；迁移已支持「代码先于配置」时的逐文件合并兜底，但仍应先配） |
| ② 推 develop → CI → CD | 自动 | 部署后：quant 日志应有「default 命名空间已迁移」；以 best@thu 登录 web 量化页能看到原有策略；`docker exec tradeck-quant ls /data/cache/users` 只剩 `u2`（admin 登录过才会多出空的 `u1`） |
| ③ 收口 + 上线 MCP | 确认 ② 正常后 | 同步 `docker-compose.yml`（quant 端口回环 + 新增 mcp 服务）、`deploy/deploy-cn.sh`、`deploy/nginx/conf.d/tradeck.conf`；`.env` 加 `MCP_SERVICE_TOKEN`、`QUANT_INBOUND_SERVICE_TOKENS`、`PAT_ALLOWED_USER_IDS`，`AUTH_SERVICE_TOKENS` 追加 mcp；`docker compose pull && docker compose up -d --force-recreate`；`docker exec tradeck-nginx nginx -s reload`；CF 实测 `/mcp` 后再发令牌 |

步骤 ③ 的 `.env` 片段（令牌为高熵随机串，`openssl rand -hex 32` 生成，与已有 `TRADB_SERVICE_TOKEN` 区分）：

```dotenv
MCP_SERVICE_TOKEN=<新生成>
QUANT_INBOUND_SERVICE_TOKENS={"<TRADB_SERVICE_TOKEN 同值>": "web-bff", "<MCP_SERVICE_TOKEN 同值>": "mcp"}
AUTH_SERVICE_TOKENS={"<TRADB_SERVICE_TOKEN 同值>": "web-bff", "<MCP_SERVICE_TOKEN 同值>": "mcp"}
PAT_ALLOWED_USER_IDS=2   # 其余受邀用户注册后追加其 id，如 2,3,4
```

③ 之后的验收：

- 外网 `curl -m5 http://81.68.69.250:8083/health` 不通；`docker exec tradeck-web wget -qO- http://quant:8083/api/strategies` 返回 401
- quant 启动日志：「quant 入站鉴权已启用，consumer：['mcp', 'web-bff']」
- web 量化页回测 / 选股 / AI 生成正常（经 web-bff 令牌）
- 用户菜单「API 令牌」签发 PAT，MCP 客户端连 `https://tradeck.virtualformat.cn/mcp` 跑通 `get_strategy_guide`

回滚：`.env` 清空 `QUANT_INBOUND_SERVICE_TOKENS` 后 recreate quant 即恢复不鉴权；compose 去掉 mcp 服务并删 nginx `/mcp` 段即下线 MCP。
迁移本身不可自动回滚（`users/default` → `users/u2` 是目录改名），需要时手工 `mv` 回去。

## 残余风险（小范围接受）

- 子进程可访问网络、可读全部缓存（见沙箱已知边界）。
- 任务注册表是进程内存：每次部署重建 quant 丢在途任务与结果，mcp 明确返回「任务不存在，请重跑」。
- 仅支持可自定义请求头的 MCP 客户端；只支持 OAuth 的 web 连接器暂不可用（随 AUTH P2 解决）。
