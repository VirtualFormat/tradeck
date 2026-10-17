# tradeck 前端 — Next.js 16
# 多阶段：dev（默认阶段，dev server + bind mount HMR）/ prod（target=prod，
# next build  standalone 产物）。dev compose 不指定 target 走 dev；
# prod compose 指定 target: prod。

FROM node:24-bookworm-slim AS base

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pnpm 9（pnpm 10+ 的 approve-builds 太严格）
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate


# ── dev 阶段（默认）：容器内跑 dev server，bind mount 源码 ──
FROM base AS dev
WORKDIR /app

# 先拷 package.json，利用缓存装依赖
COPY package.json ./
RUN pnpm install --no-frozen-lockfile

# 源码通过 bind mount 挂载（docker-compose volumes）
EXPOSE 3000

# HMR 需要 polling（WSL/Docker 文件监听问题）
ENV WATCHPACK_POLLING=true
ENV CHOKIDAR_USEPOLLING=true

CMD ["pnpm", "dev", "-H", "0.0.0.0"]


# ── prod 构建阶段：安装依赖 + next build ──
FROM base AS builder
WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
# outputFileTracingRoot 指向 devcontainer 路径（/workspace/apps/web），
# 构建期覆盖为容器内实际路径，避免 standalone 产物路径错乱。
ENV NEXT_PRIVATE_OUTPUT_TRACING_ROOT=/app
RUN pnpm build


# ── prod 运行阶段：standalone 产物（node server.js，无 pnpm/node_modules）──
FROM node:24-bookworm-slim AS prod
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
