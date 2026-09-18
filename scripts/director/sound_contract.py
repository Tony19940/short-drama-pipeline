"""Sound contract for the edit/sound agent. Maps onto existing line_kind values."""

from __future__ import annotations

import json
from pathlib import Path

from .production import load_json

KIND_ALIASES = {
    "inner_voice": "inner",
    "character_intro": "intro",
}
KIND_LABELS = {
    "dialogue": "口述",
    "inner": "心里",
    "narration": "旁白",
    "intro": "出场简介",
    "sms": "短信/字卡",
    "reaction": "无台词反应",
}
INTENTION = {
    "dialogue": "对一个人把这件事说清楚，不要播音腔",
    "inner": "只给观众听的心里话，画面里嘴巴不要动",
    "narration": "交代必要信息，像低声告诉朋友，不要解说词",
    "intro": "用最短的一句话让观众认出这个人",
    "sms": "字卡自己承担信息，不要再念一遍",
    "reaction": "先不说话，只让观众看见听完以后的那一眼",
}


def normalize_kind(value: str) -> str:
    raw = str(value or "").strip()
    return KIND_ALIASES.get(raw, raw)


def build_sound_contract(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/shots.json", {"shots": []})
    items = []
    t = 0
    for shot in data.get("shots") or []:
        sec = int(shot.get("seconds") or 0)
        kind = normalize_kind(shot.get("line_kind") or "narration")
        items.append(
            {
                "id": shot.get("id"),
                "start": t,
                "seconds": sec,
                "kind": kind,
                "kind_label": KIND_LABELS.get(kind, kind),
                "speaker": shot.get("speaker") or "",
                "line": shot.get("line") or "",
                "caption": shot.get("caption") or "",
                "sfx": shot.get("sfx") or "",
                "intention": shot.get("sound_intent") or INTENTION.get(kind, ""),
                "emotion": shot.get("emotion") or "",
                "pickup": (
                    f"{shot.get('id')} {t}s：现在是{KIND_LABELS.get(kind, kind)}。"
                    f"按「{shot.get('emotion') or 'held'}」再念一遍，不要播音腔。"
                ),
            }
        )
        t += sec
    return {
        "episode": data.get("episode") or "ep01",
        "total_seconds": t,
        "cues": items,
        "kinds": sorted({item["kind"] for item in items}),
        "note": "对白/心声/旁白/出场简介不进 video_prompt。给配音员讲意图，不讲抑扬。叠轨仍走 mix_review_track.py。",
    }


def write_sound_draft(prod: Path) -> dict:
    dest = prod / "07-dubbing"
    dest.mkdir(parents=True, exist_ok=True)
    contract = build_sound_contract(prod)
    (dest / "sound-contract.draft.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return snapshot_sound(prod)


def promote_sound_draft(prod: Path) -> None:
    src = prod / "07-dubbing" / "sound-contract.draft.json"
    if src.exists() and src.stat().st_size > 0:
        dest = prod / "07-dubbing" / "sound-contract.json"
        dest.write_bytes(src.read_bytes())


def snapshot_sound(prod: Path) -> dict:
    from .sfx import snapshot_sfx

    live = build_sound_contract(prod)
    official = prod / "07-dubbing" / "sound-contract.json"
    draft = prod / "07-dubbing" / "sound-contract.draft.json"
    return {
        "live": live,
        "official": json.loads(official.read_text(encoding="utf-8")) if official.exists() else None,
        "draft": json.loads(draft.read_text(encoding="utf-8")) if draft.exists() else None,
        "preview": "06-export/preview-vo.mp4",
        "dubbing_dir": "07-dubbing",
        "sfx": snapshot_sfx(prod),
    }
