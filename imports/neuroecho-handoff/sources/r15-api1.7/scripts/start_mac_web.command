#!/bin/bash
# First-party local source launcher; no account login or permission reset.
set -eu
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
  echo '此入口仅用于 Mac 网页服务。'; exit 1
fi
export PATH="$HOME/.nianxiang/tools/node_modules/.bin:$HOME/.nianxiang/tools/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null || ! command -v npm >/dev/null; then
  echo '首次准备需要 Python 3 和 Node.js/npm，请由项目管理员安装后重新打开。'
  read -r -p '按回车关闭…' _; exit 1
fi
mkdir -p "$HOME/.nianxiang/tools"
if ! command -v ntn >/dev/null || ! command -v gws >/dev/null; then
  npm install --prefix "$HOME/.nianxiang/tools" ntn @googleworkspace/cli
fi
if ! command -v gh >/dev/null; then
  if command -v brew >/dev/null; then
    brew install gh
  else
    echo 'GitHub 连接需要 GitHub CLI；请由管理员从 cli.github.com 安装。其它来源仍可使用。'
  fi
fi
if [ ! -x "$HOME/.nianxiang/venv/bin/python" ]; then
  python3 -m venv "$HOME/.nianxiang/venv"
fi
"$HOME/.nianxiang/venv/bin/python" -m pip install -r requirements.txt
echo '网页入口：http://127.0.0.1:18827/；关闭此终端会停止服务。'
echo '首次 Google 连接需管理员准备 OAuth 应用，见 docs/Mac网页来源接入.md。'
exec "$HOME/.nianxiang/venv/bin/python" scripts/run_paired_service.py --data-dir "$HOME/.nianxiang/web-data" --local-port 18827
