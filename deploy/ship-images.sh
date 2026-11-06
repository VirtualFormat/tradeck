#!/usr/bin/env bash
set -Eeuo pipefail

# 从本机（开发机）把 GHCR 镜像直接推送到 prod 并重建服务，绕开大陆镜像站。
#
# 背景：prod 经 ghcr.nju.edu.cn 拉 GHCR，新构建的镜像 NJU 未缓存时要回源 ghcr.io，
# 实测常卡死（0 KB/s、10 分钟以上无进展）。本机拉 ghcr.io 只需几十秒，
# 再经 SSH 管道 `docker save | gzip | docker load` 传到 prod，两个镜像约 1 分钟。
#
# 流程：
#   1. 读 prod compose，解析每个服务的镜像名（如 ghcr.nju.edu.cn/virtualformat/x:latest）
#   2. 本机从 ghcr.io 拉同路径镜像（linux/amd64），打上 prod 镜像名
#   3. 对比 prod 本地镜像 ID，一致则跳过传输与重建
#   4. save | gzip | ssh load，校验 ID
#   5. prod 上 `compose up -d --no-deps --pull never --force-recreate` 仅重建变化的服务
#   6. 等待容器 healthy（有 healthcheck）或稳定运行且无重启
#
# 用法：
#   deploy/ship-images.sh                 # 全部默认服务
#   deploy/ship-images.sh web api         # 只发指定服务
#   FORCE=1 deploy/ship-images.sh web     # 镜像未变也强制重建
#   DRY_RUN=1 deploy/ship-images.sh       # 只对比，不传输不重建
#
# 环境变量：DEPLOY_HOST（ssh 别名，默认 host-thu）、DEPLOY_PATH（prod 部署目录）、
#           SOURCE_REGISTRY（默认 ghcr.io）。
# 前置：本机能访问 ghcr.io（公开镜像无需登录）、能 ssh 到 prod、prod 有 jq。
# 不改 prod 的 compose/.env，只替换镜像并重建；不使用 --remove-orphans。

# ── 仓库配置 ──────────────────────────────────────────────
DEFAULT_SERVICES=(api quant mcp web)
DEPLOY_PATH="${DEPLOY_PATH:-/data/apps/tradeck}"
# 重建前需等待其空闲的服务及其检查命令（在 prod 上执行，输出非空表示忙）；tradeck 无
BUSY_CHECK_SERVICE=""
BUSY_CHECK_CMD=""
# ────────────────────────────────────────────────────────

DEPLOY_HOST="${DEPLOY_HOST:-host-thu}"
SOURCE_REGISTRY="${SOURCE_REGISTRY:-ghcr.io}"
FORCE="${FORCE:-0}"
DRY_RUN="${DRY_RUN:-0}"

log() { printf '[ship] %s\n' "$*"; }
die() { printf '[ship] ERROR: %s\n' "$*" >&2; exit 1; }
remote() { ssh -o ConnectTimeout=15 "${DEPLOY_HOST}" "$@"; }

services=("$@")
[[ ${#services[@]} -gt 0 ]] || services=("${DEFAULT_SERVICES[@]}")

command -v docker >/dev/null || die "本机未安装 docker"
remote "test -d '${DEPLOY_PATH}'" || die "prod 上不存在 ${DEPLOY_PATH}"

log "目标 ${DEPLOY_HOST}:${DEPLOY_PATH}，服务：${services[*]}"
# 在 prod 上解析 compose，输出「服务 镜像」（未声明 image 的服务输出空）
image_map="$(remote "cd '${DEPLOY_PATH}' && docker compose config --format json 2>/dev/null | jq -r '.services | to_entries[] | \"\\(.key) \\(.value.image // \"\")\"'")" \
  || die "读取 prod compose 失败"

to_ship=()      # 需要传输的 prod 镜像名
to_recreate=()  # 需要重建的服务
for svc in "${services[@]}"; do
  dst="$(awk -v s="${svc}" '$1==s {print $2}' <<<"${image_map}")"
  [[ -n "${dst}" ]] || die "prod compose 中没有服务 ${svc}（或未声明 image）"
  src="${SOURCE_REGISTRY}/${dst#*/}"

  log "${svc}: 拉取 ${src}"
  docker pull -q --platform linux/amd64 "${src}" >/dev/null || die "本机拉取失败：${src}"
  docker tag "${src}" "${dst}"
  local_id="$(docker image inspect -f '{{.Id}}' "${dst}")"
  remote_id="$(remote "docker image inspect -f '{{.Id}}' '${dst}' 2>/dev/null" || true)"
  running_id="$(remote "cd '${DEPLOY_PATH}' && c=\$(docker compose ps -q '${svc}') && [ -n \"\$c\" ] && docker inspect -f '{{.Image}}' \$c" 2>/dev/null || true)"

  if [[ "${local_id}" != "${remote_id}" ]]; then
    log "${svc}: 镜像有更新（${remote_id:-prod 无此镜像} → ${local_id}），需传输"
    to_ship+=("${dst}")
    to_recreate+=("${svc}")
  elif [[ "${running_id}" != "${local_id}" || "${FORCE}" == "1" ]]; then
    log "${svc}: prod 已有该镜像，但容器未在运行它（或 FORCE=1），需重建"
    to_recreate+=("${svc}")
  else
    log "${svc}: 已是最新（${local_id}），跳过"
  fi
done

if [[ "${DRY_RUN}" == "1" ]]; then
  log "DRY_RUN：待传输 ${#to_ship[@]} 个，待重建 ${to_recreate[*]:-无}"
  exit 0
fi

if [[ ${#to_ship[@]} -gt 0 ]]; then
  log "传输 ${#to_ship[@]} 个镜像：docker save | gzip | ssh docker load"
  start=$(date +%s)
  docker save "${to_ship[@]}" | gzip -1 | remote "gunzip | docker load" >/dev/null \
    || die "镜像传输失败"
  log "传输完成，用时 $(( $(date +%s) - start ))s"
  for dst in "${to_ship[@]}"; do
    [[ "$(docker image inspect -f '{{.Id}}' "${dst}")" == \
       "$(remote "docker image inspect -f '{{.Id}}' '${dst}'")" ]] || die "镜像 ID 校验失败：${dst}"
  done
  log "镜像 ID 校验通过"
fi

[[ ${#to_recreate[@]} -gt 0 ]] || { log "无服务需要重建，结束"; exit 0; }

# 有长任务的服务（如 tradb collector）等其空闲再重建，最多 10 分钟
if [[ -n "${BUSY_CHECK_SERVICE}" && " ${to_recreate[*]} " == *" ${BUSY_CHECK_SERVICE} "* ]]; then
  for attempt in $(seq 1 40); do
    busy="$(remote "${BUSY_CHECK_CMD}" 2>/dev/null || true)"
    [[ -z "${busy}" ]] && break
    [[ ${attempt} -eq 40 ]] && die "${BUSY_CHECK_SERVICE} 10 分钟内未空闲（运行中：${busy}），放弃重建"
    log "${BUSY_CHECK_SERVICE} 有运行中任务：${busy}，15s 后重试"
    sleep 15
  done
fi

log "重建：${to_recreate[*]}"
remote "cd '${DEPLOY_PATH}' && docker compose up -d --no-deps --pull never --force-recreate ${to_recreate[*]}" \
  2>&1 | grep -vE 'variable is not set|orphan containers' || true

# 健康检查：有 healthcheck 等 healthy；无则要求连续 20s 运行且重启计数不变
for svc in "${to_recreate[@]}"; do
  ok=0
  for attempt in $(seq 1 24); do
    state="$(remote "cd '${DEPLOY_PATH}' && c=\$(docker compose ps -q '${svc}') && set -- \$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}} {{.State.StartedAt}}' \$c) && echo \$1 \$2 \$3 \$(( \$(date +%s) - \$(date -d \$4 +%s) ))" 2>/dev/null || true)"
    read -r status health restarts age <<<"${state:-unknown unknown 0 0}"
    if [[ "${health}" == "healthy" ]]; then ok=1; break; fi
    if [[ "${health}" == "none" && "${status}" == "running" && "${restarts}" == "0" ]] && (( age >= 20 )); then
      ok=1; break
    fi
    sleep 5
  done
  [[ ${ok} -eq 1 ]] || die "${svc} 未通过健康检查（${state}），请查看：ssh ${DEPLOY_HOST} docker logs <容器>"
  log "${svc}: 健康（${status}/${health}）"
done

log "完成"
