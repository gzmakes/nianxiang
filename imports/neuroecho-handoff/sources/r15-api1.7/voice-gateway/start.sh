#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python -m uvicorn app.main:app --host "${VOICE_GATEWAY_HOST:-127.0.0.1}" --port "${VOICE_GATEWAY_PORT:-9881}"
