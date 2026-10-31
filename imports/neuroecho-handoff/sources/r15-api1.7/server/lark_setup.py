"""Bridge the CLI's first-run browser flow into the local web UI."""
import re
import subprocess
import threading
from urllib.parse import urlparse, parse_qs

from . import lark


def verification_url(output):
    # Never forward CLI output (which can contain application credentials).
    for match in re.finditer(r'https://[^\s<>"\x1b]+', output):
        url = match.group().rstrip("'),.;]}")
        parsed = urlparse(url)
        if (parsed.hostname in ("open.feishu.cn", "open.larksuite.com")
                and parsed.path == "/page/cli"
                and parse_qs(parsed.query).get("user_code")):
            return url
    return ""


def initialize(on_url):
    """Wait at most ten minutes; expose only an allowlisted verification URL."""
    with subprocess.Popen(
        [lark.LARK_BIN, "config", "init", "--new"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", env=lark.cli_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        timer = threading.Timer(600, process.kill)
        timer.daemon = True
        timer.start()
        try:
            buffer, shown = "", ""
            for line in process.stdout:
                buffer = (buffer + line)[-16384:]
                url = verification_url(buffer)
                if url and url != shown:
                    on_url(url)
                    shown = url
            return process.wait() == 0
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
