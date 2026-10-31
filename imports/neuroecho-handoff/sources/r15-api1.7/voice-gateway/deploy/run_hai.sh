#!/usr/bin/env bash
set -euo pipefail

# HAI images may run without systemd. This script keeps the same loopback-only
# layout as the service templates and manages both processes with pidfiles.
ROOT="${NIANXIANG_ROOT:-/opt/nianxiang}"
GPT_DIR="${NIANXIANG_GPT_DIR:-$ROOT/GPT-SoVITS}"
GATEWAY_DIR="${NIANXIANG_GATEWAY_DIR:-$ROOT/voice-gateway}"
CUDA_PY="${NIANXIANG_CUDA_PY:-/root/miniforge3/bin/python}"
GATEWAY_PY="${NIANXIANG_GATEWAY_PY:-$ROOT/venv/bin/python}"
ENV_FILE="${VOICE_GATEWAY_ENV_FILE:-/etc/nianxiang/voice-gateway.env}"
RUN_DIR="${NIANXIANG_RUN_DIR:-$ROOT/run}"
GPT_LOG="${NIANXIANG_GPT_LOG:-/tmp/gpt-sovits.log}"
GATEWAY_LOG="${NIANXIANG_GATEWAY_LOG:-/tmp/voice-gateway.log}"
GPT_PID="$RUN_DIR/gpt-sovits.pid"
GATEWAY_PID="$RUN_DIR/voice-gateway.pid"

mkdir -p "$RUN_DIR"

alive() {
  [[ -s "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
}

write_pid() {
  local pid="$1" file="$2"
  printf '%s\n' "$pid" > "$file"
}

start_gpt() {
  if alive "$GPT_PID" || curl -fsS --max-time 2 http://127.0.0.1:9880/docs >/dev/null 2>&1; then
    echo "GPT-SoVITS already running"
    return
  fi
  [[ -x "$CUDA_PY" ]] || { echo "missing CUDA Python: $CUDA_PY" >&2; return 1; }
  [[ -f "$GPT_DIR/api_v2.py" ]] || { echo "missing GPT-SoVITS: $GPT_DIR/api_v2.py" >&2; return 1; }
  (
    cd "$GPT_DIR"
    nohup "$CUDA_PY" -u api_v2.py -a 127.0.0.1 -p 9880 >>"$GPT_LOG" 2>&1 </dev/null &
    write_pid "$!" "$GPT_PID"
  )
  echo "started GPT-SoVITS; model loading may take 60-145 seconds"
}

start_gateway() {
  if alive "$GATEWAY_PID" || curl -fsS --max-time 2 http://127.0.0.1:9881/healthz >/dev/null 2>&1; then
    echo "Voice Gateway already running"
    return
  fi
  [[ -x "$GATEWAY_PY" ]] || { echo "missing gateway Python: $GATEWAY_PY" >&2; return 1; }
  [[ -f "$GATEWAY_DIR/app/main.py" ]] || { echo "missing gateway: $GATEWAY_DIR/app/main.py" >&2; return 1; }
  [[ -r "$ENV_FILE" ]] || { echo "missing gateway env: $ENV_FILE" >&2; return 1; }
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  (
    cd "$GATEWAY_DIR"
    nohup "$GATEWAY_PY" -m uvicorn app.main:app --host "${VOICE_GATEWAY_HOST:-127.0.0.1}" --port "${VOICE_GATEWAY_PORT:-9881}" >>"$GATEWAY_LOG" 2>&1 </dev/null &
    write_pid "$!" "$GATEWAY_PID"
  )
  echo "started Voice Gateway"
}

stop_one() {
  local file="$1" name="$2"
  if alive "$file"; then
    kill "$(cat "$file")" 2>/dev/null || true
    for _ in {1..20}; do alive "$file" || break; sleep .25; done
  fi
  rm -f "$file"
  echo "stopped $name"
}

status() {
  curl -fsS --max-time 3 http://127.0.0.1:9880/docs >/dev/null 2>&1 && echo "GPT-SoVITS: ready" || echo "GPT-SoVITS: unavailable"
  curl -fsS --max-time 3 http://127.0.0.1:9881/healthz >/dev/null 2>&1 && echo "Voice Gateway: ready" || echo "Voice Gateway: unavailable"
}

case "${1:-status}" in
  start)
    start_gpt
    start_gateway
    status
    ;;
  stop)
    stop_one "$GATEWAY_PID" "Voice Gateway"
    stop_one "$GPT_PID" "GPT-SoVITS"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    status
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
