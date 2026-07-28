# tradeck 开发规范

## UI 规范：shadcn 优先（强制）

UI 整体基于 shadcn preset `b2fms620zo`（初始化：`pnpm dlx shadcn@latest init --preset b2fms620zo --template next`；已有项目对齐：`pnpm dlx shadcn@latest apply b2fms620zo`）。

前端一切 UI 元素优先使用 `apps/web/src/components/ui/` 的 shadcn 组件，官方目录有但未装的先 `pnpm dlx shadcn add X` 安装再使用，禁止手写 div 模拟；图表必须经 `ui/chart`；空态统一走 `empty-state.tsx`；图标只用 phosphor。**完整规则与提交前检查清单见 `AGENTS.md`「UI 强制规则」一节，任何前端任务开工前必读。**

## 开发环境：devcontainer（强制）

**所有开发在 devcontainer 内完成，不污染宿主机**。宿主机只需要 Docker + VS Code（Remote-Containers 扩展）。

### 启动开发环境

```bash
# 方式 1: VS Code 打开项目 → F1 → "Dev Containers: Reopen in Container"
# 方式 2: 命令行
devcontainer up --workspace-folder .
```

devcontainer 配置在 `.devcontainer/`，自动装：
- Node 24 + pnpm 9
- Python 3.12 + backend requirements（akshare / yfinance / tickflow 等；OpenBB Platform 独立容器运行）
- apps/web 依赖（pnpm install）
- OpenBB Platform 服务（端口 6900）

### 在 devcontainer 内开发

- 改前端代码 → `cd apps/web && pnpm dev`（HMR 工作）
- 改 backend 代码 → uvicorn --reload 自动生效
- 跑 Python 脚本 → `python3 script.py`
- 装新依赖 → 在 devcontainer 内装，不污染宿主机

### 不要在宿主机装东西

- ❌ 不要在 WSL 宿主机装 pnpm/python 包
- ❌ 不要在宿主机跑 `pnpm install`
- ❌ 不要在宿主机跑 `pip install`
- ✅ 所有依赖在 devcontainer 内

## Prod 部署：docker compose（独立）

项目根的 `docker-compose.yml` 只用于：
- Prod 部署
- 部署前的自我验证（本地跑 prod 配置确认能起）

```bash
# 本地验证 prod 配置
docker compose up -d --build

# 部署到 VPS
docker compose -f docker-compose.yml up -d --build
```

## 项目结构

```
tradeck/
├── .devcontainer/          ← 开发环境配置
│   ├── devcontainer.json
│   └── docker-compose.yml  ← dev 用 compose（dev + postgres + backend + openbb）
├── apps/web/                ← Next.js 前端
├── apps/backend/            ← FastAPI 后端（数据管道 + API；app/datasource 数据层门面）
├── docker/openbb/           ← OpenBB Platform Dockerfile（dev + prod 共用）
├── docker-compose.yml        ← prod 用 compose（postgres + openbb + backend + web）
├── docs/                    ← 技术文档
└── .env                     ← API key 配置
```

## 技术栈（确认，不变）

- **前端**：Next.js 16 + shadcn/ui + Tailwind v4 + lightweight-charts（K线）+ recharts
- **数据层**：日K 走 TickFlow；A 股报价/深度数据 backend 直调 akshare；宏观/海外走 OpenBB Platform（FastAPI，Python）
