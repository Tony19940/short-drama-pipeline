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
        "multi_setup_in_clip": True,
        "max_internal_cuts": 2,
        "native_dialogue_audio": True,
        "lip_sync": True,
        "allowed_moves": ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan"],
        "notes": [
            "单镜 4–15 秒整数；短于 4 秒的反应镜也按 4 秒设计，剪辑时裁。",
            "一段片内允许自然切镜（Shot 1 / Shot 2）。一镜可含最多 2 次片内切，但仍只推进一个节拍。",
            "原生音视频联合生成，可生成对白与口型；对白想让模型说时标 dialogue_delivery=on_camera。",
            "首帧 / 首尾帧 / 最多 9 张参考图；文生视频不是成片路径。",
        ],
        "verified": True,
    },
    "seedance_2_5": {
        "id": "seedance_2_5",
        "label": "Seedance 2.5（占位，接入前按方舟文档核对）",
        "vendor_models": ["doubao-seedance-2-5"],
        "prompt_language": "zh",
        "min_shot_sec": 4,
        "max_shot_sec": 30,
        "aspects": ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"],
        "first_last_frame": True,
        "max_ref_images": 30,
        "return_last_frame": True,
        "multi_setup_in_clip": True,
        "max_internal_cuts": 3,
        "native_dialogue_audio": True,
        "lip_sync": True,
        "allowed_moves": ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan"],
        "notes": [
            "第三方资料称单段最长 30 秒、30 张参考图；未经方舟官方文档核对，接入时先改这里。",
        ],
        "verified": False,
    },
    "minimax_h3": {
        "id": "minimax_h3",
        "label": "MiniMax H3 / 本机 FL2VA",
        "vendor_models": ["minimax_h3"],
        "prompt_language": "en",
        "min_shot_sec": 3,
        "max_shot_sec": 8,
        "aspects": ["16:9", "9:16"],
        "first_last_frame": True,
        "max_ref_images": 3,
        "return_last_frame": True,
        "multi_setup_in_clip": False,
        "max_internal_cuts": 0,
        "native_dialogue_audio": False,
        "lip_sync": False,
        "allowed_moves": ["static", "push", "pull", "pan"],
        "forbidden_moves": ["orbit", "drone", "crash_zoom", "whip_pan", "handheld", "crane", "track", "follow"],
        "notes": [
            "锁首帧一次 body beat；对白后期叠，不对口型。",
            "一镜一个动作，不切机位。",
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
    "h3": "minimax_h3",
    "minimax": "minimax_h3",
}

DEFAULT_PROFILE = "seedance_2_0"


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
    if backend in {"local", "h3", "minimax"} or os.environ.get("LOCAL_H3_BASE", "").strip():
        return "minimax_h3"
    if os.environ.get("ARK_API_KEY", "").strip():
        return "seedance_2_0"
    return DEFAULT_PROFILE


def profile_brief(profile: dict[str, Any]) -> dict[str, Any]:
    """The slice the shot-table agent is allowed to see. Enough to design against, nothing about SDK payloads."""
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
    }
