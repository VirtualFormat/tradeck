#!/usr/bin/env bash
set -Eeuo pipefail

# 中国大陆生产部署入口：GHCR 镜像经南京大学镜像站拉取。
# 官方公共镜像（postgres）保持原仓库，不经过 GHCR 镜像站。
# 行情数据层镜像（collector/openbb/data-api）由 tradb 仓库部署，与本脚本无关。

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
for service in api quant web; do
  pull_service "${service}"
done

log "拉取 PostgreSQL 公共镜像"
if ! docker image inspect postgres:16-alpine >/dev/null 2>&1; then
  pull_service postgres
else
  log "本机已有 postgres:16-alpine，跳过公共镜像拉取"
fi

log "启动生产服务"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans

log "当前服务状态"
docker compose -f "${COMPOSE_FILE}" ps

# ── 健康检查（失败 exit 1，供 CI/CD 判定部署成败）────────────────
# web/quant 查宿主机映射端口的 /health；api 无宿主机端口（仅容器网络可达），
# 且 compose 已配 curl healthcheck，直接看 compose 状态。

wait_http() {
  local name="$1" url="$2" attempt
  for attempt in $(seq 1 12); do
    if curl -fsS --max-time 5 "${url}" >/dev/null 2>&1; then
      log "${name} 健康检查通过：${url}"
      return 0
    fi
    sleep 5
  done
  die "${name} 健康检查超时（60s）：${url}"
}

wait_healthy_container() {
  local name="$1" service="$2" attempt
  for attempt in $(seq 1 12); do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose -f "${COMPOSE_FILE}" ps -q "${service}")" 2>/dev/null)" == "healthy" ]]; then
      log "${name} 容器健康（compose healthcheck）"
      return 0
    fi
    sleep 5
  done
  die "${name} 容器 60s 内未转为 healthy"
}

log "健康检查"
wait_http "web" "http://127.0.0.1:3000"
wait_http "quant" "http://127.0.0.1:8083/health"
wait_healthy_container "api" "api"

log "部署完成，全部服务健康"
