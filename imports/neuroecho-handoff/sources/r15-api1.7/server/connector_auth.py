"""Explicit, local browser login for installed CLI connectors; no raw output."""
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel

from . import cli_runtime, gmail_cli_source

LOCK = threading.Lock()
JOBS = {}
TOOLS = {"github": ("gh", "XINJI_GH_CLI"), "notion": ("ntn", "XINJI_NOTION_CLI"),
         "gmail": ("gws", "XINJI_GWS_CLI")}
HOSTS = {"github": {"github.com"}, "notion": {"www.notion.so", "notion.so", "www.notion.com", "notion.com"},
         "gmail": {"accounts.google.com"}}


class LoginStatus(BaseModel):
    status: str
    url: str = ""
    code: str = ""
    message: str = ""


def extract_link(provider, text):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    for raw in re.findall(r'https://[^\s<>"\x1b]+', text):
        candidate = raw.rstrip("'),.;]}")
        parsed = urlparse(candidate)
        if (parsed.hostname in HOSTS[provider] and not parsed.username and not parsed.password
                and parsed.port in (None, 443)):
            if provider == "github" and parsed.path.rstrip("/") not in ("/login/device", "/login/oauth/authorize"):
                continue
            # Do not relay tokens even if an unexpected CLI prints a callback.
            if re.search(r"(?:[?&#])(?:access_token|refresh_token|token)=", candidate, re.I):
                continue
            return candidate
    return ""


def _update(provider, job, **values):
    with LOCK:
        if JOBS.get(provider) is job:
            job.update(values)


def _run(provider, cli, job):
    args = {"github": ["auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--skip-ssh-key"],
            "notion": ["login"],
            "gmail": ["auth", "login", "--scopes", gmail_cli_source.SCOPE]}[provider]
    process = None
    timer = None
    try:
        process = subprocess.Popen([cli, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   env=cli_runtime.environment(),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        timer = threading.Timer(600, process.kill)
        timer.daemon = True
        timer.start()
        buffer = ""
        for line in process.stdout:
            buffer = (buffer + line)[-16384:]
            link = extract_link(provider, buffer)
            code = re.search(r"(?:one-time code|code:)\s*([A-Z0-9]{4}-[A-Z0-9]{4})", buffer, re.I) if provider == "github" else None
            values = {"status": "pending", "message": "请在运行念响的这台电脑浏览器中完成登录和授权。"}
            if link:
                values["url"] = link
            if code:
                values["code"] = code[1]
            _update(provider, job, **values)
        if process.wait() != 0:
            raise RuntimeError()
        # Exit zero proves login completion, not access to an arbitrary document.
        _update(provider, job, status="success", url="", code="",
                message="登录流程已完成，请读取并核对所选资料。若读取被拒绝，仍需核对资源访问权。")
    except Exception:
        message = "连接未完成或已超时，请重新连接；若持续失败，请检查网络及账号权限。"
        if provider == "gmail":
            message += " Google OAuth 应用需由项目管理员预先配置，不能仅靠普通用户点击授权创建。"
        _update(provider, job, status="error", url="", code="", message=message)
    finally:
        if timer:
            timer.cancel()
        if process is not None and process.poll() is None:
            process.kill()


def start(provider):
    if provider not in TOOLS:
        raise HTTPException(404, "unsupported connector")
    with LOCK:
        job = JOBS.get(provider)
        if job and job["status"] in ("starting", "pending"):
            return {k: job.get(k, "") for k in LoginStatus.model_fields}
        tool, override = TOOLS[provider]
        cli = cli_runtime.resolve(tool, override)
        if not cli:
            return {"status": "needs_install", "message": "连接组件尚未安装，请先安装对应 CLI，再从网页连接。"}
        job = {"status": "starting", "url": "", "code": "", "message": "正在准备登录…", "created": time.monotonic()}
        JOBS[provider] = job
        threading.Thread(target=_run, args=(provider, cli, job), daemon=True).start()
        return {k: job.get(k, "") for k in LoginStatus.model_fields}


def login_start(provider: str):
    return start(provider)


def login_status(provider: str):
    if provider not in TOOLS:
        raise HTTPException(404, "unsupported connector")
    with LOCK:
        job = JOBS.get(provider, {"status": "idle"})
        return {k: job.get(k, "") for k in LoginStatus.model_fields}
