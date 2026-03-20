#!/usr/bin/env bash
set -Eeuo pipefail

port="${LLAMA_SERVER_PORT:-8001}"
curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >/dev/null
