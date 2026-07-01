#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${FUTU_LOGIN_ACCOUNT:-}" ]]; then
  echo "FUTU_LOGIN_ACCOUNT is required" >&2
  exit 64
fi

pwd_args=()
if [[ -n "${FUTU_LOGIN_PWD_MD5:-}" ]]; then
  pwd_args+=("-login_pwd_md5=${FUTU_LOGIN_PWD_MD5}")
elif [[ -n "${FUTU_LOGIN_PWD:-}" ]]; then
  pwd_args+=("-login_pwd=${FUTU_LOGIN_PWD}")
else
  echo "FUTU_LOGIN_PWD_MD5 or FUTU_LOGIN_PWD is required" >&2
  exit 64
fi

cert_dir="${FUTU_OPEND_CERT_DIR:-/var/lib/futu-opend}"
cert_file="${FUTU_OPEND_WEBSOCKET_CERT:-${cert_dir}/websocket.crt}"
key_file="${FUTU_OPEND_WEBSOCKET_PRIVATE_KEY:-${cert_dir}/websocket.key}"
mkdir -p "$cert_dir"
if [[ ! -s "$cert_file" || ! -s "$key_file" ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -days "${FUTU_OPEND_CERT_DAYS:-3650}" \
    -subj "/CN=futu-opend" \
    -addext "subjectAltName=DNS:futu-opend,IP:127.0.0.1" \
    -keyout "$key_file" \
    -out "$cert_file" >/dev/null 2>&1
fi

websocket_args=(
  "-websocket_ip=${FUTU_OPEND_WEBSOCKET_IP:-0.0.0.0}"
  "-websocket_port=${FUTU_OPEND_WEBSOCKET_PORT:-33333}"
  "-websocket_private_key=${key_file}"
  "-websocket_cert=${cert_file}"
)
if [[ -n "${FUTU_OPEND_KEY:-}" ]]; then
  websocket_key_md5="$(printf '%s' "$FUTU_OPEND_KEY" | md5sum | awk '{print $1}')"
  websocket_args+=("-websocket_key_md5=${websocket_key_md5}")
fi

exec /opt/futu-opend/FutuOpenD \
  "-login_account=${FUTU_LOGIN_ACCOUNT}" \
  "${pwd_args[@]}" \
  "-api_ip=${FUTU_OPEND_API_IP:-0.0.0.0}" \
  "-api_port=${FUTU_OPEND_API_PORT:-11111}" \
  "-telnet_ip=${FUTU_OPEND_TELNET_IP:-127.0.0.1}" \
  "-telnet_port=${FUTU_OPEND_TELNET_PORT:-22222}" \
  "${websocket_args[@]}" \
  "-lang=${FUTU_OPEND_LANG:-chs}" \
  "-log_level=${FUTU_OPEND_LOG_LEVEL:-info}" \
  "-log_path=/var/log/futu-opend" \
  "-no_monitor=1" \
  "-console=1"
