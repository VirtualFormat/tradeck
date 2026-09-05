#!/bin/bash
# devcontainer 创建后的初始化脚本
# 安装所有开发依赖（Node + Python/backend requirements + 前端依赖；OpenBB Platform 由独立容器运行）
set -e

echo "=== 1. 安装 Node 24 + pnpm 9 ==="
curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
apt-get install -y nodejs
corepack enable && corepack prepare pnpm@9.15.0 --activate
node --version && pnpm --version

echo ""
echo "=== 2. 安装 Python 依赖（collector + backend + quant，不含 OpenBB）==="
pip install --no-cache-dir \
  -r /workspace/apps/data-collector/requirements.txt \
  -r /workspace/apps/backend/requirements.txt \
  -r /workspace/apps/quant/requirements.txt

echo ""
echo "=== 3. 安装前端依赖 ==="
cd /workspace/apps/web && pnpm install --no-frozen-lockfile

echo ""
echo "=== 4. 验证 ==="
echo "OpenBB API: http://openbb:6900"
echo "Swagger UI: http://openbb:6900/docs"
echo "前端开发: cd /workspace/apps/web && pnpm dev"
