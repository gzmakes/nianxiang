#!/usr/bin/env bash
set -euo pipefail
pkill -f 'uvicorn app.main:app' || true
