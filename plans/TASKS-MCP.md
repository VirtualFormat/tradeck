# MCP 接入 — 任务拆解与验收

> 流程沿用既有模式：主 agent 派活 → 执行（写范围受限）→ review 门禁 → 修复 → 验收，回填「验收记录」。
> 技术背景见 `docs/MCP.md`。
> Review 门禁：① 符合 AGENTS.md 约定（优雅降级 / 中文注释 / UI 强制规则）；
> ② 安全检查（令牌只存哈希、身份只来自令牌、子进程无密钥）；③ 验收标准全绿。

## 背景速览

2-3 名受邀用户经 MCP 客户端以 PAT 连接 quant 上传策略、跑回测。独立 `apps/mcp` 服务；
`users/default` 迁移给管理员 `u<id>`。开放前必须先修 quant 的四个既有缺口：
用户代码在主进程执行、quant 不鉴权来访者且无条件采信 `X-User-Id`、web 不传用户身份、任务无归属。

## 任务拆解

| # | 任务 | 写范围 | 依赖 |
|---|---|---|---|
| 1 | 文档：docs/MCP.md、本文件、docs/README.md / AUTH.md / AGENTS.md 索引增补 | `docs/`、`plans/`、`AGENTS.md` | — |
| 2 | quant 入站服务令牌中间件 + `current_user_id` 收口；web `quantFetch()` 透传 `X-User-Id`；`QUANT_MIGRATE_DEFAULT_TO` 启动迁移 | `apps/quant/app/{api,config,runner}.py`、`apps/web/src/lib/quant.ts`、`apps/web/src/app/api/_guard.ts`、`apps/web/src/app/api/quant/**` | — |
| 3 | 任务 owner + poll/cancel 归属校验 + 每用户活跃上限 | `apps/quant/app/{tasks,api}.py` | 2 |
| 4 | 轻量沙箱：custom/ai 只 AST 解析 META；选股/优化/试加载走 worker；子进程干净环境 + 降权 | `apps/quant/app/{strategy/loader,worker,runner,api}.py`、`apps/quant/app/sandbox.py`（新） | 2 |
| 5 | validator 修正（用户因子 scoring / 下标放行 / dunder 赋值）+ `POST /api/strategies/validate` + `GET /api/strategies/errors` | `apps/quant/app/ai/validator.py`、`apps/quant/app/api.py` | 4 |
| 6 | 部署配置：quant 端口回环、`.env.example`、prod/dev compose | `docker-compose.yml`、`.devcontainer/docker-compose.yml`、`.env.example` | 2 |
| 7 | PAT：`auth.api_tokens` + 签发/列表/撤销/verify + `PAT_ALLOWED_USER_IDS` + web 设置页 | `apps/backend/app/{auth_main,config}.py`、`apps/backend/app/api/auth_tokens.py`（新）、`apps/backend/init.sql`、`apps/web/src/app/settings/tokens/`、`apps/web/src/app/api/account/tokens/`、`apps/web/src/components/settings/` | — |
| 8 | `apps/mcp`：SDK v2 无状态 HTTP、PAT verifier、8 个工具、配额、/health；Dockerfile、compose、CI 矩阵、deploy-cn.sh、nginx | `apps/mcp/**`、`.github/workflows/app-images.yml`、`deploy/**`、`docker-compose.yml` | 2-7 |
| 9 | 全量测试 + 独立 review | — | 1-8 |

**接口契约（mcp ↔ api / quant 对齐用，细节以最终代码为准）**：

```
api  POST /api/auth/tokens/verify   X-Service-Token(mcp)  { token }
       → 200 { user_id: "u<id>", scopes: [...], expires_at } | 401（无效/撤销/过期/禁用）
quant 任意 /api/*                   X-Service-Token + X-User-Id: u<id>
       → 401（缺/错服务令牌，配置了 INBOUND_SERVICE_TOKENS 时）| 400（缺 X-User-Id）
quant POST /api/strategies/validate { code } → 200 { valid, error?, meta? }
quant GET  /api/strategies/errors          → 200 [{ file, source, error }]（仅本人 custom/ai）
quant GET  /api/backtest/task/{id}         → 404（非本人任务，与不存在同响应）
```

## 验收标准

**P0 quant 加固**：

- [x] 配置 `INBOUND_SERVICE_TOKENS` 后：无/错 `X-Service-Token` 调 `/api/*` 返回 401；`/health` 不鉴权。
- [x] 配置后缺 `X-User-Id` 返回 400（不再回落 default）；未配置时行为与改造前一致。
- [x] web 全部 `/api/quant/*` 代理经 `quantFetch()`，带 `X-User-Id: u<id>`（grep 无裸 `fetch(\`${QUANT_API_URL}`）。
- [x] `QUANT_MIGRATE_DEFAULT_TO` 迁移幂等：二次启动不报错；目标目录已存在时跳过并告警。
- [x] 用户 B poll/cancel 用户 A 的回测/AI 任务返回 404。
- [x] 同一用户第 3 个活跃任务返回 429；其他用户不受影响。
- [x] 沙箱：主进程注册表加载 custom/ai 策略不执行模块代码（策略顶层 `print`/写文件不发生）。
- [x] 沙箱：子进程 uid 为 65534、环境无 `AI_API_KEY`/`SERVICE_TOKEN`、读 `/proc/1/environ` 失败（quant 镜像内 root 实测）。
- [x] 选股、优化（含小网格）、保存试加载、每日信号均经沙箱子进程（用户策略）。
- [ ] builtin 策略回测结果与改造前逐值一致（golden 测试不回归）。
- [x] validator：scoring 引用本人 active 用户因子可保存；`params["__user_factor_values__"]` 放行；`__name__` / `__builtins__` 拒绝。
- [ ] quant 单测全绿（`PYTHONPATH=apps/quant python -m unittest discover -s apps/quant/tests`）。

**P1 PAT**：

- [ ] 签发返回明文仅一次；`auth.api_tokens` 只存 sha256（查库确认无明文）。
- [ ] 撤销/过期/用户 disabled 的令牌 verify 返回 401；非 mcp 服务令牌调 verify 返回 403。
- [ ] `PAT_ALLOWED_USER_IDS` 非空时名单外用户签发 403；每人有效令牌 ≤5。
- [ ] web 设置页：UI 强制规则检查清单全绿，`pnpm lint` 通过。
- [ ] backend 单测全绿。

**P2 MCP**：

- [ ] 无/错 Bearer 返回 401 且 `WWW-Authenticate` 指向 resource metadata。
- [ ] scope 不足的工具调用被拒（只读令牌调 `save_strategy` 失败）。
- [ ] 端到端：读指南 → validate → save → run_backtest → get_backtest_result，web 上可见同一策略。
- [ ] `get_backtest_result` 默认摘要 ≤10KB；分页取 trades 正常。
- [ ] 配额：每令牌第 61 次/分钟调用被拒；`universe=all` 被拒。
- [ ] mcp 单测全绿（httpx MockTransport mock api/quant）。

**部署**：

- [ ] 外网 curl `81.68.69.250:8083` 不通；容器网络内无令牌调 quant 401。
- [ ] CF 实测 `https://tradeck.virtualformat.cn/mcp` 返回 JSON-RPC 响应（非质询页）。
- [ ] `deploy-cn.sh` 健康检查覆盖 mcp。

## 验收记录

2026-10-18（P0，主 agent）：

- quant 单测 423 例：除 5 例**改造前既有失败**外全部通过（`test_api_eventloop_fixes` 4 例 import 已改名的
  `_check_matrix_coverage_or_503` / `_matrix_coverage`；`test_optimize_api` 1 例 tracked 期望值与代码不符）——
  未修，待定。新增 `test_inbound_auth`（15）、`test_sandbox`（10）、`test_validator_rules`（8）、注册表归属（6+1）。
- 沙箱在 quant 镜像内以 root 跑 `test_sandbox` + `test_backtest_tasks` 全绿；probe：子进程 uid 65534、
  环境仅 `LANG/PATH/PYTHONIOENCODING/QUANT_CACHE_DIR/QUANT_DEFAULT_USER`、读 `/proc/1/environ` 失败、写缓存失败。
- 「builtin 回测逐值一致」：builtin 走原进程内路径未改；用户策略沙箱回测与进程内结果交易数/总收益一致（test_sandbox）。
- web：`tsc --noEmit`、eslint 0 错误。prod compose `config` 与 nginx `-t` 通过。

2026-10-18（P1/P2 + 端到端 + 独立 review，主 agent）：

- PAT / MCP 由 workflow 两条并行流实现，各自经独立 reviewer 修复（PAT 5 项、MCP 6 项）；backend 73 例、mcp 67 例全绿。
- 本地四服务联调（auth-db + api + quant + mcp 现场构建）用官方 MCP 客户端跑通：签发 PAT → 8 工具 → validate
  拦 argparse / 读 environ → save → run_backtest → 长轮询 done（摘要 4KB）→ 交易分页；只读令牌 scope 拒绝；
  无 Bearer / 伪造 PAT / 非法 Host 分别 401/401/421；撤销 32s 后 401；库中只有 sha256，日志无密钥。
- MCP reviewer 发现 quant symbol 路径穿越（web 链路同样可触发）→ quant 请求模型加 `^[A-Z0-9.-]{1,20}$`，web 输入归一。
- P0 对抗式 review（4 视角 × 2 怀疑者）确认 18 条，已全部修复：worker 线程桥 NameError（future 永不完成，
  critical）、池信号量按 loop 重建被打穿、AI 任务取消提前释放额度、预检不预占、同步回测绕过额度、
  web 429 被吞成 502 后回退旧接口、入站令牌非法配置 fail-open、试加载合成矩阵误拒 / 无并发上限 / 超时过长、
  静态 META 与执行结果分叉、BFF 任务 id 路径穿越、Popen 失败 fd 泄漏、回传消息上限过宽、子进程 stderr 丢失、
  dtype 开关未透传、迁移把空目录当冲突。quant 432 例（仅 5 例既有失败）。
- 复审（回归视角）确认 8 条，已全部修复：注册表线程池/事件循环真并发导致额度永久泄漏（加 RLock，cancel 不重新占位已
  release 的任务）、并发清扫 500、`/api/ai/save` 覆盖失败删掉旧版本（改走带 .bak 的统一落盘）、`from numpy import
  __builtins__ as b` 绕过双下划线规则（导入名/别名拦下划线前缀与通配）、custom 与 builtin 同 id 被静默屏蔽（409）、
  validate/save 对 composite 结论不一致、AI 生成未透传 user_id、优化系路由绕过每用户额度（预占）。
  quant 443 例（仅 5 例既有失败）；沙箱相关 99 例在 quant 镜像内以 root 全绿；backend 73、mcp 67、web tsc/eslint 全绿。
- 沙箱逃逸视角：两轮 workflow 与专项 agent 均未交付报告，由主 agent 直接核查（quant 镜像内 root 父进程实测）：
  - 主进程注册表构造点逐个核对：api/jobs 均 sandbox=True；runner/screener 的 `registry or StrategyRegistry(...)`
    默认分支只被 CLI 与沙箱子进程使用；mining/factors 不执行策略代码；分钟频策略主进程调 compute 被
    SandboxViolation 拦截；与 builtin 同 id 的用户文件不加载（且保存 409）；composite 引用分钟频子策略被移除。
  - 子进程（uid 65534）对 root 所有缓存目录建文件/符号链接均 PermissionError，`kill(1, 0)` PermissionError。
  - 伪造回传：子进程经 ctypes 向 fd 3–29 写伪造 JSON / pickle 样字节 → 父进程只得到「回传消息格式非法」
    SandboxError，父进程存活，无反序列化执行面。
  - 结论：未发现可跨到主进程的路径。顺带堵上 validator 的间接引用绕过（@exec 装饰器、默认参数、别名、海象、
    `"{0.__class__}".format`、match 类模式内部属性）——这些只影响沙箱内，属纵深防御。
  - 最终：quant 445 例（仅 5 例既有失败）、镜像内 root 沙箱相关 101 例、backend 73、mcp 67、web tsc/eslint 全绿。

2026-10-19：prod 有两个账号——admin `id=1`（默认不使用）与 user `id=2`（best@thu，日常使用）。
迁移目标定为日常账号：`QUANT_MIGRATE_DEFAULT_TO=u2`；MCP 名单 `PAT_ALLOWED_USER_IDS=2`。
迁移改为逐文件合并（目标已有数据时不冲突的文件并入、同名保留目标版本），兜底「代码先于配置上线」的部署顺序。
上线手册定稿见 docs/MCP.md「上线顺序」。

2026-10-21（prod 部署完成，主 agent）：

- 部署：推 develop（c4e975c）→ CI 构建 4 镜像（含新增 tradeck-mcp，可公开拉取）→ CD 自动部署成功
  （web/quant/mcp/api 健康检查全过）；VPS 配置先备份至 /data/apps/tradeck/backup-20261021-153833，
  .env 修改另备份为 .env.bak-mcp-*（权限 600）。
- 迁移：`users/default` → `users/u2`（factors/signals/strategies 共 7 个文件），quant 日志可见；
  迁移后 u2 策略列表 3 个 AI 策略 + 6 个 builtin，load errors 为空。
- 沙箱（prod 实测）：子进程 uid=65534、环境仅白名单 5 项、读 /proc/1/environ 失败、写缓存失败；
  u2 的用户策略沙箱回测 done；u1 查 u2 任务 404。
- 收口：外网 curl 81.68.69.250:8083 不通；web 容器内四种情况分别为 401/401/400/200
  （无令牌/错令牌/缺用户/正常）；web BFF 完整链路（策略列表/回测登记/轮询终态）正常。
- MCP：mcp 容器带服务令牌与公网 URL；CF→nginx→mcp 链路无 Bearer 401（带 WWW-Authenticate）、
  resource metadata 200；api verify 端点非 mcp 调用 403、mcp 带伪 PAT 401、无服务令牌 401；
  nginx 配置已切到新版并 reload（备份在 backup 目录）。
- 端到端带真 PAT 的全链路验证未做：PAT 签发走 web「API 令牌」页（用户菜单入口），
  需要用户自行登录签发后实测（分类器禁止直写 prod auth-db 造验证 session，属正确拦截）。

## 遗留事项

- 沙箱强化：seccomp 禁 socket/execve；独立 `network_mode: none` 沙箱容器 + 缓存只读挂载；按用户目录权限。
- OAuth 2.1（随 AUTH P2），支持只认 OAuth 的 web 端 MCP 连接器。
- 任务注册表持久化（部署重建不丢在途任务）。
- 扩展工具：screen / walkforward / optimize / delete_strategy；用量统计面板。
