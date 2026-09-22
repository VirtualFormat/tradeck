# 用户认证与登录（auth）

> P0 定案方案。邮箱 + 密码认证，web（Next.js BFF）手写 session，tradeck 自建 auth-api（FastAPI）落独立 `auth-db`。
> 配套文件：任务拆解与验收见 `plans/TASKS-AUTH-P0.md`。

## 定位

tradeck 此前只有「服务身份」（service token，见 `DATA-SERVICE.md`），没有「用户身份」。auth P0 补齐用户域最小闭环：注册 / 登录 / 会话校验 / 登出，为后续用户业务数据（P3 的 `userdata` schema：自选股、看板布局等）打底。

设计取向：**不引入第三方认证框架，不引入 JWT**。session 是后端可控的状态（可撤销、可审计），JWT 的无状态卖点在本项目没有收益（单 backend、会话量极小），反而带来「登出不生效」「密钥轮换即全员掉线」的负担。P2 接 OAuth 时再重估 Auth.js v6，当前不预设。

## 架构

```
浏览器
  │  ① 表单提交（fetch 同源 Next API）
  ▼
web (Next.js :3000, BFF)
  │  ② Route Handler 代理 auth-api，X-Service-Token: web-bff（AUTH_API_URL）
  ▼
auth-api (FastAPI :8080, tradeck 自建 auth 服务；复用 tradeck-api 镜像，
          command 覆盖为 uvicorn app.auth_main:app)
  │  ③ /api/auth/{register,login,session,logout}
  ▼
auth-db（tradeck 自有独立 PG 16 service，与 tradb 行情库物理分离）
  users（email 唯一 / password_hash / role / status）
  sessions（token 哈希 / 过期时间）
```

链路要点：

- 浏览器只跟 web BFF 说话，cookie（`tdk_session`）由 web 在登录响应上 Set-Cookie，域为 web 自身域名，浏览器不直连 auth-api。
- **双后端分离**：auth 走 tradeck 自建 auth-api（web 侧 `AUTH_API_URL`），行情走 tradb data-api（`BACKEND_API_URL`）。两条链路独立配置、独立故障域，web 侧 session 校验与行情取数互不影响。
- web BFF → auth-api 走既有 service-token 体系（`X-Service-Token`，消费方标识 `web-bff`）。**复用与 tradb 同一把 `TRADB_SERVICE_TOKEN`**（web 侧 `serviceAuthHeaders()` 零改动，减少密钥数量；如需独立可另配 `AUTH_SERVICE_TOKEN` 并同步 web 侧）。auth 端点鉴权模型与行情读接口一致，不为 auth 开第二条通道。
- **用户域数据物理隔离**：auth 数据存 tradeck 自有 `auth-db`（prod compose 独立 postgres:16-alpine service，只接 default 网络、不接 tradb_net、不映射宿主机端口），auth-api 经 `AUTH_DATABASE_URL` 访问。tradb 零改动、不持有任何 tradeck 业务数据——这比原「auth schema 与行情表同库不同 schema」的设计更彻底：隔离从 PG 权限层提升到实例层，tradb 拆分后用户域天然留在 tradeck 侧。

## 会话模型

**手写 session cookie，不用 JWT**：

- web 登录成功后 Set-Cookie `tdk_session=<随机 token>`，属性 `HttpOnly; Secure; SameSite=Lax; Path=/`。HttpOnly 挡 XSS 窃取，Secure 仅 HTTPS 下生效（依赖上线前 HTTPS 前置，见「安全清单」）。
- token 是高熵随机串，**DB 只存其哈希**（`sessions` 表存 `sha256(token)` 派生的 token_hash），明文 token 只存在于浏览器 cookie 与请求的短暂生命周期内。库泄露 ≠ 会话泄露。
- 每次请求：web 中间件 / BFF 读 cookie → 调 auth-api `/api/auth/session` → auth-api 按 token_hash 查 `sessions` 表，校验未过期且用户 status 有效。
- 过期策略：默认 7 天（`AUTH_SESSION_DAYS`），登出即删除对应 session 行（服务端可撤销，这是相对 JWT 的核心收益）。过期即失效，P0 不做滑动续期/refresh token（7 天窗口下复杂度不值，续期策略留待 P1 评估）。

密码存储：`password_hash` 支持 **argon2id / pbkdf2 双格式**（哈希串自带算法标识，校验时按标识分发）。双格式是为兼容存量/迁移场景，新注册统一 argon2id；纯标准库环境可退 pbkdf2。具体字段编码格式以最终代码为准。

## 注册与邀请制

配置 `AUTH_INVITE_CODE`（auth-api 环境变量）：

- **非空 = 邀请制**：注册请求必须带匹配邀请码，不匹配 403。内测期默认姿势。
- **空 = 开放注册**：任何邮箱可注册。
- **首个用户自动 admin**：`users` 表为空时的第一个注册者 role = admin，之后注册的均为 user。保证系统必有管理员，不需要手工 SQL 提权。

注册流程只收邮箱 + 密码（+ 邀请码），P0 不做邮箱验证（验证邮件属 P1 的邮件能力，与忘记密码共用一套发送基建）。

## 角色模型

| 角色 | 说明 |
|---|---|
| admin | 首个用户自动获得；P0 仅作标记 |
| user | 默认角色 |

**P0 角色不做门禁**：登录态只区分「已登录 / 未登录」，admin/user 字段落库但不驱动任何权限分支。门禁规则等 P3 用户业务数据出现真实需求再定（避免提前设计一套用不上的权限矩阵）。

## 安全清单（上线前必须项）

- [ ] **HTTPS 前置**：反代（Caddy/Nginx）终结 TLS，cookie `Secure` 才有意义；`SameSite=Lax` 依赖站上下文，跨站部署需重估。
- [ ] **`CORS_ORIGINS` 生产显式配置**：auth-api 已是 env 驱动（空 = 不放行任何跨域）。浏览器不直连 auth-api 时保持为空即可；若确有浏览器直连场景，只放行 web 域名，禁止 `*`。
- [ ] **登录限流**：已实现进程内限流（10 分钟 10 次），防在线爆破。多实例部署时需注意进程内计数不共享（以最终部署形态为准）。
- [ ] **密钥/配置管理**：`AUTH_DB_PASSWORD`（auth-db 数据库密码，prod 必改强密码）、`AUTH_INVITE_CODE`、`AUTH_SESSION_DAYS`、`SERVICE_TOKENS`、`CORS_ORIGINS` 全部走环境变量，登记 `.env.example`，不入库不硬编码。
- [ ] 错误信息不区分「邮箱不存在」与「密码错误」（统一 401，防邮箱枚举）。
- [ ] DB 角色最小权限：auth-db 仅 auth-api 经容器网络访问，不接 tradb_net、不映射宿主机端口（呼应上文物理隔离的设计意图）。

## 分期路线图

| 期 | 内容 | 状态 |
|---|---|---|
| P0 | 邮箱+密码注册/登录/session/登出，邀请制，角色标记（本文件范围） | 本次施工 |
| P1 | 改密 / 忘记密码（邮件发送基建，含邮箱验证） | 未开始 |
| P2 | OAuth 第三方登录（届时重估 Auth.js v6） | 未开始 |
| P3 | 用户业务数据 `userdata` schema（自选股、看板布局等，角色门禁需求届时再定） | 未开始 |

## 与 service-token 体系的关系

两套身份**正交**，互不替代：

- **service token**（`X-Service-Token`，见 `DATA-SERVICE.md`）：服务对服务的身份。回答「哪个消费方在调 data-api」（web-bff / 量化服务 / 回测），用于消费方区分与审计。它不识别「人」。
- **用户 session**（`tdk_session` cookie + auth-db `sessions` 表）：人对 web 的身份。回答「当前是哪个用户」，作用域止于 web BFF；auth-api 看到的调用方永远是 web-bff 这个 service token，用户信息经 auth 端点出入，不向行情读接口传播。

即：浏览器 →（用户 session）→ web BFF →（service token）→ auth-api。两层身份各管各的信任边界，任一层撤销不影响另一层。
