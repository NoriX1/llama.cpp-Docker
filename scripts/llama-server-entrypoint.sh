#!/usr/bin/env bash
set -Eeuo pipefail

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  local level="$1"
  shift
  printf "%s [llama-server] [%s] %s\n" "$(timestamp)" "$level" "$*" >&2
}

die() {
  log "ERROR" "$*"
  exit 70
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "Required file not found: $path"
}

gpu_available() {
  if [[ -e /dev/nvidiactl || -e /dev/nvidia0 || -e /dev/dxg ]]; then
    return 0
  fi

  if command -v ldconfig >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q 'libcuda\.so\.1'; then
    return 0
  fi

  return 1
}

load_args_file() {
  local file="$1"
  local -n target_ref="$2"
  local line

  require_file "$file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    [[ "${line:0:1}" == "#" ]] && continue
    target_ref+=("$line")
  done < "$file"
}

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_FILE="${MODEL_FILE:-model.gguf}"
MODEL_PATH="${MODEL_PATH:-$MODEL_DIR/$MODEL_FILE}"
LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:-8001}"
LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:-0.0.0.0}"
LLAMA_SERVER_ARGS_FILE="${LLAMA_SERVER_ARGS_FILE:-/config/llama-server.args}"
LLAMA_SERVER_CPU_FALLBACK_ARGS_FILE="${LLAMA_SERVER_CPU_FALLBACK_ARGS_FILE:-/config/llama-server.cpu-fallback.args}"
LLAMA_GPU_MODE="${LLAMA_GPU_MODE:-required}"
LOG_DIR="${LOG_DIR:-/logs}"
LOG_FILE="${LLAMA_SERVER_LOG_FILE:-$LOG_DIR/llama-server.log}"

require_file "$MODEL_PATH"
require_file "$LLAMA_SERVER_ARGS_FILE"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

declare -a runtime_args
load_args_file "$LLAMA_SERVER_ARGS_FILE" runtime_args

case "$LLAMA_GPU_MODE" in
  required)
    if ! gpu_available; then
      die "NVIDIA runtime is not available inside the container. Check Docker Desktop GPU support and NVIDIA Container Toolkit integration."
    fi
    log "INFO" "GPU runtime detected; starting in required-GPU mode"
    ;;
  fallback)
    if gpu_available; then
      log "INFO" "GPU runtime detected; using primary llama.cpp arguments"
    else
      log "WARNING" "GPU runtime not detected; switching to explicit CPU fallback args from $LLAMA_SERVER_CPU_FALLBACK_ARGS_FILE"
      runtime_args=()
      load_args_file "$LLAMA_SERVER_CPU_FALLBACK_ARGS_FILE" runtime_args
    fi
    ;;
  *)
    die "Unsupported LLAMA_GPU_MODE=$LLAMA_GPU_MODE. Use required or fallback."
    ;;
esac

log "INFO" "Model path: $MODEL_PATH"
log "INFO" "Listen address: $LLAMA_SERVER_HOST:$LLAMA_SERVER_PORT"
log "INFO" "Args file: $LLAMA_SERVER_ARGS_FILE"

exec /opt/llama/bin/llama-server \
  --model "$MODEL_PATH" \
  --host "$LLAMA_SERVER_HOST" \
  --port "$LLAMA_SERVER_PORT" \
  "${runtime_args[@]}"
