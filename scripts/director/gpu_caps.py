"""Ask the local H3 box what it can do. Never download weights. Never fake Ref2VA as FL2VA."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

_CACHE: tuple[float, dict] | None = None
TTL = 10


def gpu_configured() -> bool:
    return bool(os.environ.get("LOCAL_H3_BASE", "").strip())


def seedance_configured() -> bool:
    return bool(os.environ.get("ARK_API_KEY", "").strip())


def video_ready() -> bool:
    return gpu_configured() or seedance_configured()


def video_backend_name() -> str:
    chosen = os.environ.get("DIRECTOR_VIDEO_BACKEND", "").strip()
    if chosen:
        return chosen
    if seedance_configured():
        return "seedance"
    if gpu_configured():
        return "local"
    return ""


def gpu_capabilities(force: bool = False) -> dict[str, Any]:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE[0] < TTL:
        return _CACHE[1]
    base = os.environ.get("LOCAL_H3_BASE", "").strip().rstrip("/")
    empty = {
        "ok": False,
        "configured": bool(base),
        "gpu": False,
        "fl2va": False,
        "ref2va": False,
        "ref2va_installed": False,
        "designed_end_frame": True,
        "continue_last_frame": True,
        "turbo": False,
        "fl_unet": None,
        "ref_unet": None,
        "reason": "LOCAL_H3_BASE 未配置" if not base else "还没问到 GPU",
        "note": "缺 Ref2VA 只显示未安装，不自动下载，也不把 FL2VA 冒充成 Ref2VA。",
    }
    if seedance_configured() and video_backend_name() == "seedance":
        cloud = dict(empty)
        cloud.update(
            {
                "ok": True,
                "configured": True,
                "gpu": False,
                "cloud": True,
                "backend": "seedance",
                "model": os.environ.get("ARK_SEEDANCE_MODEL", "doubao-seedance-2-0-mini-260615"),
                "fl2va": True,
                "designed_end_frame": True,
                "continue_last_frame": True,
                "reason": "Seedance 2.0 Mini 已接火山方舟，不走本机 GPU",
                "note": "云端图生视频：首帧必带，首尾帧可选，参考图挂在首帧外面。文生视频不成片。",
            }
        )
        _CACHE = (now, cloud)
        return cloud
    if not base:
        _CACHE = (now, empty)
        return empty
    info = dict(empty)
    info["configured"] = True
    try:
        req = urllib.request.Request(base + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        info["reason"] = f"GPU 健康检查失败：{exc}"
        _CACHE = (now, info)
        return info
    ref_unet = payload.get("ref_unet") or None
    fl_unet = payload.get("fl_unet") or None
    info.update(
        {
            "ok": bool(payload.get("ok", True)),
            "gpu": bool(payload.get("gpu") or payload.get("comfy")),
            "turbo": bool(payload.get("turbo")),
            "fl_unet": fl_unet,
            "ref_unet": ref_unet,
            "fl2va": bool(fl_unet) or bool(payload.get("gpu") or payload.get("comfy")),
            "ref2va_installed": bool(ref_unet),
            "ref2va": bool(ref_unet),
            "contract": payload.get("contract") or [
                "designed-first-frame",
                "continue-last-frame",
                "designed-end-frame",
                "refs-outside-first-frame",
            ],
            "raw": {k: payload.get(k) for k in ("ok", "gpu", "comfy", "turbo", "fl_unet", "ref_unet")},
            "reason": "Ref2VA 未安装" if not ref_unet else "GPU 已接",
        }
    )
    if not info["ref2va_installed"]:
        info["note"] = "Ref2VA 未安装。锁脸参考不能走 Ref2VA 节点。不要用 FL2VA 冒充。"
    _CACHE = (now, info)
    return info
