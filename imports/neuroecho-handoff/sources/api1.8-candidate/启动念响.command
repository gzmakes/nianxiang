#!/bin/bash
# macOS 双击启动：运行于本机回环地址，关闭终端或按 Ctrl+C 停止。
set -u
cd "$(dirname "$0")" || exit 1
PORT=18787
URL="http://127.0.0.1:${PORT}/"
PID=""
cleanup() {
  if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
fail() {
  printf '\n启动未完成：%s\n' "$1"
  printf '按回车关闭窗口。'
  read -r _ || true
  exit 1
}
printf '念响 · 本机启动\n\n'
command -v lsof >/dev/null 2>&1 || fail '缺少系统工具 lsof，无法确认端口归属。'
EXISTING_PID=$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1)
if [ -n "$EXISTING_PID" ]; then
  EXISTING_CWD=$(lsof -a -p "$EXISTING_PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  EXISTING_HEALTH=$(curl -fsS --max-time 2 "${URL}api/health" 2>/dev/null || true)
  case "$EXISTING_HEALTH" in
    *'"product":"xinji-echo"'*)
      if [ "$EXISTING_CWD" = "$PWD" ]; then
        printf '这份原型已在运行，打开现有对话：%s\n' "$URL"
        if command -v open >/dev/null 2>&1; then open "$URL" || true; fi
        exit 0
      fi
      ;;
  esac
  fail '本机 18787 端口已被其他服务占用。请先确认并停止那个服务。'
fi
if [ ! -x .venv/bin/python ]; then
  command -v python3 >/dev/null 2>&1 || fail '找不到 Python 3。请安装 Python 3.10 或更新版本后重试。'
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail 'Python 版本过低，请安装 Python 3.10 或更新版本。'
  printf '首次启动：正在创建项目虚拟环境 .venv …\n'
  python3 -m venv .venv || fail '无法创建虚拟环境，请检查 Python 安装。'
fi
PY=.venv/bin/python
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail '项目虚拟环境需要 Python 3.10 或更新版本。'
if ! "$PY" -c 'import fastapi, uvicorn, pydantic, qrcode, PIL' >/dev/null 2>&1; then
  printf '正在安装 requirements.txt 中的 Python 依赖（需要联网）…\n'
  "$PY" -m pip install -r requirements.txt || fail '依赖安装失败，请检查网络和 Python 环境后重试。'
fi
"$PY" -c 'import socket,sys; s=socket.socket(); r=s.connect_ex(("127.0.0.1",18787)); s.close(); sys.exit(0 if r else 1)' || fail '本机 18787 端口已被占用。请先关闭占用该端口的程序。'
printf '正在启动本机服务：%s\n' "$URL"
"$PY" -m uvicorn server.main:app --host 127.0.0.1 --port "$PORT" &
PID=$!
READY=0
for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  if lsof -nP -a -p "$PID" -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && curl -fsS --max-time 1 "${URL}api/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
[ "$READY" -eq 1 ] || fail '服务未能启动，请查看上方终端错误。'
printf '\n已启动，浏览器地址：%s\n' "$URL"
printf '模型配置：页面「更多」→「数据与模型设置」；未配置时使用规则引擎。\n'
printf '保持此窗口打开；按 Ctrl+C 可停止服务。\n\n'
if command -v open >/dev/null 2>&1; then open "$URL" || printf '无法自动打开浏览器，请手动打开上方地址。\n'; fi
wait "$PID" || true
PID=""
