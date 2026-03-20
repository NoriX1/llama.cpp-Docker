#!/usr/bin/env bash
set -Eeuo pipefail

LOG_DIR="${LOG_DIR:-/logs}"
LOG_FILE="${PROXY_LOG_FILE:-$LOG_DIR/llama-proxy.log}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

exec python3 /opt/proxy/llama-proxy.py
