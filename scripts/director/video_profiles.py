"""Video-model capability profiles.

The shot-table station designs against a profile, never against a model name
hard-coded in a prompt. Swap the target model and the same shot table is
re-checked and re-compiled; the design itself does not have to be redone.

Numbers marked `verified` come from the vendor API docs at the time of
writing. Profiles with `verified=False` are placeholders that must be
confirmed before they gate a real production.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

ALL_MOVES = ("static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane", "orbit", "drone", "crash_zoom", "whip_pan")

PROFILES: dict[str, dict[str, Any]] = {
    "seedance_2_0": {
        "id": "seedance_2_0",
        "label": "Seedance 2.0（火山方舟 doubao-seedance-2-0 / -fast / -mini）",
        "vendor_models": ["doubao-seedance-2-0-260128", "doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-mini-260615", "doubao-seedance-2-0-mini"],
        "prompt_language": "zh",
        "min_shot_sec": 4,
        "max_shot_sec": 15,
        "aspects": ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"],
        "first_last_frame": True,
        "max_ref_images": 9,
        "return_last_frame": True,
        "multi_setup_in_clip": False,
        "max_internal_cuts": 0,
        "native_dialogue_audio": True,
        "lip_sync": True,
        "allowed_moves": ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan"],
        "notes": [
            "单镜渲染 4–15 秒整数。纸面可短于 4 秒（反应 1.2–2.0）；渲染按 min，剪辑裁回纸面秒。",
            "默认一镜一机位。模型能听提示词切镜，本仓库不编片内切（max_internal_cuts=0）。要开的剧把本档调回去。",
            "原生音视频联合生成，可生成对白与口型；对白想让模型说时标 dialogue_delivery=on_camera。出片带模型声音（generate_audio=true）；对白仍可后期重录，但成片保留环境声/音效。",
            "首帧 / 首尾帧 / 最多 9 张参考图，三种模式互斥，不能 first_frame 和 reference_image 同发。文生视频不是成片路径。",
            "出片默认 Mini 720p（1280×720）。仅当首帧人脸拦截（PrivacyInformation）才走官方 MiniMax-H3 768p，本地 ffmpeg lanczos 缩到 1280×720。配额/超时/风控词不 fallback。",
        ],
        "verified": True,
    },
    "seedance_2_5": {
        "id": "seedance_2_5",
        "label": "Seedance 2.5（火山方舟 doubao-seedance-2-5-260628）",
        "vendor_models": ["doubao-seedance-2-5-260628", "doubao-seedance-2-5"],
        "prompt_language": "zh",
        "min_shot_sec": 4,
        "max_shot_sec": 30,
        "aspects": ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"],
        "first_last_frame": True,
        "max_ref_images": 30,
        "return_last_frame": True,
        "multi_setup_in_clip": False,
        "max_internal_cuts": 0,
        "native_dialogue_audio": True,
        "lip_sync": True,
        "allowed_moves": ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan"],
        "notes": [
            "单镜 4–30 秒整数；本剧仍按 4–15 编，2.0 / 2.5 同一张表。不要编 duration=-1。",
            "默认一镜一机位。不编片内切（max_internal_cuts=0）。16–30 秒长镜也不靠片内换机位，要换就开新镜。",
            "硬首帧 / 首尾帧提交必须 ratio=adaptive；包里的 16:9 靠首帧像素，不要把 16:9 写进 2.5 首帧请求。",
            "first_frame、last_frame、reference_image 互斥。硬首帧不带护照图。参考模式最多 30 张，用提示词指定「首帧为图片N」。",
            "generate_audio 默认 true。本剧出片带模型声音，提交 generate_audio=true。无 camera_fixed。",
            "能力细节见 knowledge/model-notes/seedance_2_5.md。",
        ],
        "verified": True,
    },
    "wan_3": {
        "id": "wan_3",
        "label": "万相 3.0（阿里云百炼 wan3.0-video / prime）",
        "vendor_models": ["wan3.0-video", "wan3.0-video-prime", "wan_3", "wan3"],
        "prompt_language": "zh",
        "min_shot_sec": 2,
        "max_shot_sec": 30,
        "aspects": ["16:9", "9:16", "4:3", "3:4", "1:1"],
        "first_last_frame": True,
        "max_ref_images": 10,
        "return_last_frame": False,
        "multi_setup_in_clip": False,
        "max_internal_cuts": 0,
        "native_dialogue_audio": True,
        "lip_sync": True,
        "allowed_moves": ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan"],
        "notes": [
            "单镜 2–30 秒整数；本剧仍按 4–15 编。不要编 duration=-1。",
            "硬首帧 / 首尾帧提交 ratio=adaptive。first_frame、last_frame 与 reference_image 互斥。",
            "硬首帧不带护照图，身份靠 6.1 父图链。参考模式最多 10 张图。",
            "提示词用中文。默认关闭 prompt 智能改写，避免改掉已锁 motion。",
            "可出有声，开关声音同价。本剧对白仍后期叠，提交 audio=false。",
            "能力细节见 knowledge/model-notes/wan_3.md。",
        ],
        "verified": True,
    },
    "minimax_h3": {
        "id": "minimax_h3",
        "label": "MiniMax H3 官方 API / 本机 FL2VA",
        "vendor_models": ["MiniMax-H3", "minimax_h3", "MiniMax-H3-Max"],
        "prompt_language": "en",
        "min_shot_sec": 4,
        "max_shot_sec": 15,
        "aspects": ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"],
        "first_last_frame": True,
        "max_ref_images": 9,
        "return_last_frame": True,
        "multi_setup_in_clip": False,
        "max_internal_cuts": 0,
        "native_dialogue_audio": False,
        "lip_sync": False,
        "allowed_moves": ["static", "push", "pull", "pan"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan", "handheld", "crane", "track", "follow"],
        "notes": [
            "官方 API 4–15 秒整数；H3 768P/2K，H3-Max 480P/768P 且最短 5 秒。",
            "图生视频：首帧 / 首尾帧 / 全能参考互斥。硬首帧不带护照图，身份靠 6.1 父图链。",
            "锁首帧一次 body beat；对白后期叠，不对口型。",
            "一镜一个动作，不切机位。",
            "正式出片不是主路径。仅当 Seedance Mini 720p 首帧人脸拦截时，官方 H3 768p 出片再本地缩到 1280×720。不走 CompShare。",
        ],
        "verified": True,
    },
}

ALIASES = {
    "seedance": "seedance_2_0",
    "seedance_2_0_mini": "seedance_2_0",
    "doubao-seedance-2-0-mini": "seedance_2_0",
    "doubao-seedance-2-0-mini-260615": "seedance_2_0",
    "doubao-seedance-2-0-260128": "seedance_2_0",
    "doubao-seedance-2-0-fast-260128": "seedance_2_0",
    "dreamina-seedance-2-0-260128": "seedance_2_0",
    "doubao-seedance-2-5": "seedance_2_5",
    "doubao-seedance-2-5-260628": "seedance_2_5",
    "wan": "wan_3",
    "wan3": "wan_3",
    "wan3.0": "wan_3",
    "wan3.0-video": "wan_3",
    "wan3.0-video-prime": "wan_3",
    "wan_3.0": "wan_3",
    "h3": "minimax_h3",
    "minimax": "minimax_h3",
    "minimax-h3": "minimax_h3",
    "minimax_h3_max": "minimax_h3",
}

DEFAULT_PROFILE = "seedance_2_0"


def allows_internal_cuts(profile: Optional[dict[str, Any]] = None) -> bool:
    """House rule: Seedance 2.0 / 2.5 default off. A future show opts in on the profile."""
    profile = profile or {}
    return int(profile.get("max_internal_cuts") or 0) > 0 and bool(
        profile.get("multi_setup_in_clip") or profile.get("one_shot_may_cut_inside")
    )


def profile_ids() -> list[str]:
    return sorted(PROFILES)


def get_profile(model: Optional[str]) -> dict[str, Any]:
    key = str(model or "").strip().lower()
    key = ALIASES.get(key, key)
    if key in PROFILES:
        return dict(PROFILES[key])
    return dict(PROFILES[DEFAULT_PROFILE])


def _profile_from_text(text: str) -> str:
    blob = str(text or "").lower()
    if re.search(r"seedance[\s_-]*2[\s._-]*5", blob):
        return "seedance_2_5"
    if "seedance" in blob or "豆包" in blob or "方舟" in blob:
        return "seedance_2_0"
    if re.search(r"wan[\s._-]*3|万相", blob):
        return "wan_3"
    if re.search(r"\bh3\b|minimax|fl2va", blob):
        return "minimax_h3"
    return ""


def resolve_target_model(prod: Optional[Path] = None, explicit: Optional[str] = None) -> str:
    """Order: explicit arg → env DIRECTOR_TARGET_MODEL → .pipeline/gen_packages.json → confirm.md → env ARK_SEEDANCE_MODEL / backend → default."""
    if explicit and str(explicit).strip():
        return get_profile(explicit)["id"]
    env = os.environ.get("DIRECTOR_TARGET_MODEL", "").strip()
    if env:
        return get_profile(env)["id"]
    if prod is not None:
        packages = prod / ".pipeline" / "gen_packages.json"
        if packages.exists():
            try:
                import json

                model = str(json.loads(packages.read_text(encoding="utf-8")).get("episode_target_model") or "")
                if model:
                    return get_profile(model)["id"]
            except (OSError, ValueError):
                pass
        confirm = prod / "01-bible" / "confirm.md"
        if confirm.exists():
            found = _profile_from_text(confirm.read_text(encoding="utf-8"))
            if found:
                return found
    ark_model = os.environ.get("ARK_SEEDANCE_MODEL", "").strip()
    if ark_model:
        return get_profile(ark_model)["id"]
    backend = os.environ.get("DIRECTOR_VIDEO_BACKEND", "").strip().lower()
    if backend in {"seedance", "ark"}:
        return "seedance_2_0"
    if backend in {"local", "h3", "minimax"} or os.environ.get("LOCAL_H3_BASE", "").strip() or os.environ.get("MINIMAX_API_KEY", "").strip():
        return "minimax_h3"
    if os.environ.get("ARK_API_KEY", "").strip():
        return "seedance_2_0"
    return DEFAULT_PROFILE


def profile_brief(profile: dict[str, Any]) -> dict[str, Any]:
    """The slice the shot-table agent is allowed to see. Enough to design against, nothing about SDK payloads.

    `experience` is what QC has learned about this model (knowledge/model-notes/<id>.md); empty when nothing yet.
    """
    from .model_notes import experience_for

    return {
        "target_model": profile["id"],
        "label": profile["label"],
        "prompt_language": profile["prompt_language"],
        "shot_seconds": {"min": profile["min_shot_sec"], "max": profile["max_shot_sec"]},
        "one_shot_may_cut_inside": bool(profile["multi_setup_in_clip"]),
        "max_internal_cuts": int(profile["max_internal_cuts"]),
        "dialogue_delivery_options": ["post", "on_camera"] if profile["native_dialogue_audio"] else ["post"],
        "allowed_moves": list(profile["allowed_moves"]),
        "forbidden_moves": list(profile["forbidden_moves"]),
        "first_last_frame": bool(profile["first_last_frame"]),
        "notes": list(profile.get("notes") or []),
        "verified": bool(profile.get("verified")),
        "experience": experience_for(profile["id"]),
    }
