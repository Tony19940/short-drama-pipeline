"""Launch local InkOS Studio for Gate 0. Never automates writing or login."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4567/"
WEB_FALLBACK = "https://huohuaapi.com/apps"


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def _open_url(url: str) -> None:
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _which_inkos() -> str:
    found = shutil.which("inkos")
    if found:
        return found
    extras = [
        Path.home() / ".local" / "bin" / "inkos",
        Path.home() / ".npm-global" / "bin" / "inkos",
        Path("/usr/local/bin/inkos"),
        Path("/opt/homebrew/bin/inkos"),
    ]
    for extra in extras:
        if extra.exists():
            return str(extra)
    return ""


def launch_inkos(brief=None) -> dict:
    brief = brief or {}
    title = str(brief.get("title") or "").strip()
    logline = str(brief.get("logline") or "").strip()
    url = os.environ.get("INKOS_STUDIO_URL", DEFAULT_URL).rstrip("/") + "/"
    host, port = "127.0.0.1", 4567
    if "://" in url:
        rest = url.split("://", 1)[1]
        hostport = rest.split("/", 1)[0]
        if ":" in hostport:
            host, raw_port = hostport.split(":", 1)
            try:
                port = int(raw_port)
            except ValueError:
                port = 4567
        else:
            host = hostport
    started = False
    already = _port_open(host, port)
    if already:
        _open_url(url)
        return {
            "ok": True,
            "opened": url,
            "already_running": True,
            "started": False,
            "title": title,
            "logline": logline,
            "note": "InkOS 已在跑，已打开写作台。写完导出 md/txt/docx/pdf，再回到本页上传。",
        }
    binary = _which_inkos()
    if binary:
        log_dir = Path.home() / ".inkos"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / "studio-from-director.log").open("a", encoding="utf-8")
        subprocess.Popen([binary, "studio"], stdout=log, stderr=log, start_new_session=True)
        started = True
        for _ in range(20):
            if _port_open(host, port):
                break
            time.sleep(0.3)
        if _port_open(host, port):
            _open_url(url)
            return {
                "ok": True,
                "opened": url,
                "already_running": False,
                "started": True,
                "title": title,
                "logline": logline,
                "note": "已启动本机 InkOS。在里面写短篇，导出后再上传到故事页。导演台不会代写。",
            }
    _open_url(WEB_FALLBACK)
    return {
        "ok": True,
        "opened": WEB_FALLBACK,
        "already_running": False,
        "started": started,
        "missing_cli": not bool(binary),
        "title": title,
        "logline": logline,
        "note": "本机没有 inkos 命令，已打开网页版。写完导出后回到故事页上传。",
    }

