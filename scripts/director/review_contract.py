"""Frozen Gate E+ contract. Models may comment; scripts decide pass/fail."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

from .gates import ken_burns_blocked
from .paths import director_dir
from .production import load_json
from .store import _write


def contract_path(prod: Path) -> Path:
    return director_dir(prod, create=True) / "review-contract.json"


def load_contract(prod: Path) -> dict:
    path = director_dir(prod) / "review-contract.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _shots(prod: Path) -> list[dict]:
    return list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])


def preview_path(prod: Path, shot_ids: Optional[list[str]] = None) -> Path:
    shots = _shots(prod)
    if shot_ids and len(shot_ids) != len(shots):
        return prod / "06-export" / "preview-partial-vo.mp4"
    return prod / "06-export" / "preview-vo.mp4"


def has_audio_stream(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "audio" in out.lower()


def freeze_review_contract(prod: Path, shot_ids: Optional[list[str]] = None) -> dict:
    shots = _shots(prod)
    want = set(shot_ids or [])
    selected = [shot for shot in shots if not want or shot["id"] in want]
    if not selected:
        raise ValueError("没有可审镜头")
    items = []
    for shot in selected:
        video = prod / "05-shots" / f"{shot['id']}.mp4"
        items.append(
            {
                "id": shot["id"],
                "line": str(shot.get("line") or "").strip(),
                "caption": str(shot.get("caption") or "").strip(),
                "video": f"05-shots/{shot['id']}.mp4",
                "video_exists": video.exists(),
                "ken_burns": ken_burns_blocked(video) if video.exists() else False,
            }
        )
    contract = {
        "shot_ids": [item["id"] for item in items],
        "preview": str(preview_path(prod, [item["id"] for item in items]).relative_to(prod)),
        "shots": items,
        "visual": "inconclusive",
        "frozen_at": int(time.time()),
        "verdict": None,
        "required": None,
        "notes": "视觉层无模型时标 inconclusive，不算 pass。S0/S1 错了整镜失败。",
    }
    _write(contract_path(prod), contract)
    return contract


def evaluate_review_contract(prod: Path, preview: Optional[Path] = None) -> dict:
    contract = load_contract(prod) or freeze_review_contract(prod)
    dest = preview or (prod / contract.get("preview", "06-export/preview-vo.mp4"))
    failures: list[str] = []
    shot_verdicts: list[dict] = []
    for item in contract.get("shots") or []:
        reasons = []
        video = prod / item["video"]
        if not video.exists():
            reasons.append("缺单镜 mp4")
        elif ken_burns_blocked(video):
            reasons.append("Ken Burns 不能进审片")
        if not item.get("line") or not item.get("caption"):
            reasons.append("line/caption 空")
        grade = "fail" if reasons else "required_ok"
        if reasons:
            failures.extend(f"{item['id']} {reason}" for reason in reasons)
        shot_verdicts.append({"id": item["id"], "s0": reasons, "s1": [], "s2": [], "grade": grade})
    if not dest.exists():
        failures.append(f"缺 {dest.name}")
    elif ken_burns_blocked(dest):
        failures.append("审片轨是 Ken Burns")
    elif not has_audio_stream(dest):
        failures.append("审片轨没有音轨")
    required = "fail" if failures else "pass"
    visual = "inconclusive"
    if required == "fail":
        verdict = "fail"
    else:
        verdict = "inconclusive"
    contract.update(
        {
            "required": required,
            "visual": visual,
            "verdict": verdict,
            "failures": failures,
            "shot_verdicts": shot_verdicts,
            "preview_exists": dest.exists(),
            "has_audio": has_audio_stream(dest) if dest.exists() else False,
            "evaluated_at": int(time.time()),
        }
    )
    _write(contract_path(prod), contract)
    return contract
