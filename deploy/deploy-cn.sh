#!/usr/bin/env bash
set -Eeuo pipefail

# 中国大陆生产部署入口：GHCR 镜像经南京大学镜像站拉取。
# 官方公共镜像（postgres/nginx）保持原仓库，不经过 GHCR 镜像站。

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"

export GHCR_REGISTRY="${GHCR_REGISTRY:-ghcr.nju.edu.cn}"

log() {
  printf '[deploy-cn] %s\n' "$*"
}

die() {
  printf '[deploy-cn] ERROR: %s\n' "$*" >&2
  exit 1
}

pull_service() {
  local service="$1"
  local attempt
  for attempt in 1 2 3; do
    log "拉取 ${service}（第 ${attempt}/3 次）"
    if docker compose -f "${COMPOSE_FILE}" pull "${service}"; then
      return 0
    fi
    sleep $((attempt * 5))
  done
  die "镜像拉取失败：${service}"
}

command -v docker >/dev/null 2>&1 || die "未安装 docker"
docker compose version >/dev/null 2>&1 || die "未安装 docker compose 插件"
[[ -f "${COMPOSE_FILE}" ]] || die "找不到 ${COMPOSE_FILE}"
[[ -f "${PROJECT_ROOT}/.env" ]] || die "缺少 ${PROJECT_ROOT}/.env，请先从 .env.example 创建并填写生产配置"

cd "${PROJECT_ROOT}"

log "GHCR 镜像源：${GHCR_REGISTRY}"
log "校验 compose 配置"
docker compose -f "${COMPOSE_FILE}" config --quiet

log "串行拉取 tradeck 应用镜像，避免镜像站并发大层超时"
for service in openbb collector data-api quant web; do
  pull_service "${service}"
done

log "拉取 PostgreSQL 公共镜像"
pull_service postgres

log "启动生产服务"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans

log "当前服务状态"
docker compose -f "${COMPOSE_FILE}" ps
