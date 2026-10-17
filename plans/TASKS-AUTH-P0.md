# 用户登录 P0 — 任务拆解与验收

> 流程沿用既有模式：主 agent 派活 → 子 agent 按任务卡执行（写范围严格受限）→
> review 门禁 → 修复 → 验收，回填「验收记录」。技术背景见 `docs/AUTH.md`。
> Review 门禁：① 代码符合 AGENTS.md 约定（优雅降级 / 中文注释 / UI 强制规则）；
> ② 安全检查（无明文 token 落库、无邮箱枚举、cookie 属性齐全）；③ 验收标准全绿。

## 背景速览

邮箱 + 密码认证，web（Next.js BFF）手写 session（cookie `tdk_session`），backend 落 `auth` schema（`auth.users` / `auth.sessions`）。端点 `/api/auth/{register,login,session,logout}` 走既有 service-token（web-bff）。配置 `AUTH_INVITE_CODE`（非空 = 邀请制，首个用户自动 admin）、`AUTH_SESSION_DAYS`（默认 7）。

## 任务拆解（三个并行工作流）

三条流写范围不重叠，可并行派三个子 agent；B 依赖 A 的端点契约（先约定接口形状，B 可按契约 mock 开发，不阻塞）。

| 任务 | 内容 | 写范围 | 依赖 |
|---|---|---|---|
| A. backend auth | `auth` schema DDL（users/sessions）、`/api/auth/{register,login,session,logout}` 路由、密码哈希（argon2id/pbkdf2 双格式）、token 生成与 sha256 哈希存储、进程内登录限流（10 分钟 10 次）、`AUTH_INVITE_CODE` / `AUTH_SESSION_DAYS` 配置、首个用户自动 admin、单测 | `apps/backend/app/api/auth.py`（或同等位置）、`apps/backend/app/config.py`、DDL 落点（以最终代码为准）、`apps/backend/tests/` | — |
| B. web 登录 | 登录/注册页（shadcn 组件，遵守 UI 强制规则）、BFF 代理路由（转发 `/api/auth/*`，带 web-bff token）、`tdk_session` cookie 的 Set/读/清（HttpOnly/Secure/SameSite=Lax）、中间件：无 cookie 访问受保护页重定向 `/login?next=` | `apps/web/src/app/login/`、`apps/web/src/app/api/auth/`、`apps/web/src/middleware.ts`（以最终代码为准） | A 的接口契约 |
| C. 文档 | docs/AUTH.md、docs/README.md 索引、AGENTS.md 最小增补 | `docs/AUTH.md`、`docs/README.md`、`AGENTS.md` | — |

**接口契约（A/B 对齐用，细节以最终代码为准）**：

```
POST /api/auth/register  { email, password, invite_code? }  → 201 | 403（邀请码错）| 409（已注册）
POST /api/auth/login     { email, password }                → 200 + session token | 401（不区分邮箱/密码）
GET  /api/auth/session   （带 cookie/token）                 → 200 { user } | 401
POST /api/auth/logout                                        → 200（删 session 行）
```

## 验收标准

**backend**：

- [ ] 注册成功写 `auth.users`（email 唯一，重复注册 409）。
- [ ] 首个注册用户 role = admin，其后注册的为 user。
- [ ] `AUTH_INVITE_CODE` 非空时：无邀请码/错误邀请码注册 403；为空时开放注册。
- [ ] 登录成功返回 session token；DB `auth.sessions` 只存 token 哈希（grep/查库确认无明文）。
- [ ] 错误密码 401，响应体不区分「邮箱不存在」与「密码错误」（无邮箱枚举）。
- [ ] session 过期（`AUTH_SESSION_DAYS`，默认 7 天）后校验 401；登出后原 token 立即失效。
- [ ] 登录限流生效：同来源 10 分钟内第 11 次尝试被拒。
- [ ] backend 单测通过。
- [ ] `auth` schema 与行情表权限隔离（auth 角色对行情表不可见，以最终代码为准）。

**web**：

- [ ] 无 cookie 访问受保护页 → 重定向 `/login?next=<原路径>`；登录成功后跳回 next。
- [ ] 登录后 cookie `tdk_session` 带 `HttpOnly; Secure; SameSite=Lax; Path=/`。
- [ ] 注册成功自动登录：注册接口成功后同 handler 内转发 login 并种 `tdk_session` cookie；自动登录失败时降级返回「注册成功，请登录」。
- [ ] 登出后 cookie 清除，再访问受保护页重新跳登录。
- [ ] 登录/注册页走 shadcn 组件（UI 强制规则检查清单全绿），错误提示不泄露后端细节。
- [ ] `pnpm lint` 通过。

**部署与安全收尾**：

- [ ] `CORS_ORIGINS` 生产配置记录（空 = 不放行跨域；如需浏览器直连仅放行 web 域名）写入部署文档/部署记录。
- [ ] `AUTH_INVITE_CODE` / `AUTH_SESSION_DAYS` 登记 `.env.example`。
- [ ] HTTPS 前置确认（反代终结 TLS，cookie Secure 生效）。

## 验收记录

2026-09-15 回填：

- 实现：backend（schema + 4 端点 + 双格式密码哈希）、web（登录页 + 中间件 + 33 个代理路由守卫 + 注册自动登录）、文档（docs/AUTH.md）三条并行工作流均完成。
- Review 门禁：独立 review agent 审出 C1×1 / H×3 / M×4 / L×5；Critical 与全部 High、M2/M3/M4、L2/L3 已修复并复验，M1 与剩余 Low 项转入遗留。
- 验证结果：backend 单测 11 例（9 通过 + 2 例 argon2 因沙箱缺依赖按设计 skip，装 argon2-cffi 后自动启用）；web `tsc --noEmit` 通过、eslint 0 错误 0 警告；UI 红线 grep（裸 button/input、lucide、animate-spin 未登记豁免）零命中。
- 端到端未验：宿主机无 devcontainer 运行时，注册→登录→访问→登出全链路需在 dev 环境起 stack 后人工过一遍（重点：邀请码 403、错密码 401 不区分、无 cookie 重定向 /login?next=）。

## 遗留事项

- P1：改密 / 忘记密码（邮件发送基建，含邮箱验证）。
- P2：OAuth 第三方登录（届时重估 Auth.js v6）。
- P3：用户业务数据 `userdata` schema（自选股/看板布局等），角色门禁规则届时随真实需求定。
- 生产部署配置项：`CORS_ORIGINS`（web 域名）、`AUTH_DB_PASSWORD`（auth-db 强密码，prod 必改）、`AUTH_INVITE_CODE`（内测期邀请码，prod 必填）、`AUTH_SESSION_DAYS`（默认 7）、HTTPS 反代；web 侧 `AUTH_API_URL` 已由 prod compose 固定为 `http://auth-api:8080`（容器网络直达）；多实例部署时进程内限流不共享，需重估（以最终部署形态为准）。
