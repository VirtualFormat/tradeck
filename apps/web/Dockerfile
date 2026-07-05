# tradeck 前端 — Next.js 15 开发环境
# 容器内跑 dev server，bind mount 源码，HMR 通过端口映射到宿主机

FROM node:24-bookworm-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pnpm 9（pnpm 10+ 的 approve-builds 太严格）
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

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
