"""One-shot production confirmations. Changing parent, refs, or prompt voids them."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from .gates import designed_end_frame, i2v_source, parent_still, require_fresh_gate, run_check
from .production import load_json
from .prompts import compile_h3_fields, compile_video_prompt, identity_refs, still_refs, video_mode
from .store import load_approvals, save_approvals


def _shots(prod: Path) -> list[dict]:
    return list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])


def _selected(prod: Path, shot_ids: Optional[list[str]]) -> list[dict]:
    shots = _shots(prod)
    want = set(shot_ids or [])
    selected = [shot for shot in shots if not want or shot["id"] in want]
    if not selected:
        raise ValueError("没有可出的镜头")
    return selected


def shot_spec(prod: Path, shot: dict, shots: list[dict]) -> dict:
    parent = parent_still(prod, shot, shots)
    source = i2v_source(prod, shot, shots)
    refs = still_refs(prod, shot)
    compiled = compile_video_prompt(shot, silent=True, refs=refs)
    fields = compile_h3_fields(shot, silent=True, refs=refs)
    mode = video_mode(shot, source.get("kind") or "designed_frame", refs)
    dest = f"05-shots/{shot['id']}.mp4"
    end = designed_end_frame(prod, shot)
    if not end["ok"]:
        raise PermissionError(end["reason"])
    return {
        "id": shot["id"],
        "parent": parent.get("path") or "",
        "source": source.get("path") or "",
        "source_kind": source.get("kind") or "",
        "refs": list(refs),
        "identity_refs": identity_refs(refs),
        "mode": mode,
        "dest": dest,
        "frame": shot.get("frame") or f"04-frames/{shot['id']}.jpg",
        "end_frame": end.get("path") or "",
        "compiled": compiled,
        "h3": fields,
    }


def fingerprint_for(prod: Path, shot_ids: Optional[list[str]] = None) -> tuple[str, list[dict]]:
    shots = _shots(prod)
    selected = _selected(prod, shot_ids)
    specs = [shot_spec(prod, shot, shots) for shot in selected]
    payload = {
        "shot_ids": [item["id"] for item in specs],
        "shots": [
            {k: item[k] for k in ("id", "parent", "source", "refs", "mode", "dest", "compiled", "end_frame")}
            for item in specs
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), specs


def prepare_render(prod: Path, shot_ids: Optional[list[str]] = None, review_track: bool = False) -> dict:
    require_fresh_gate(prod, "C")
    from .pipeline import assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod)
        assert_keyframes_passed(prod)
    check = run_check(prod)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    selected = _selected(prod, shot_ids)
    shots = _shots(prod)
    for shot in selected:
        dest = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
        if not dest.exists():
            raise PermissionError(f"{shot['id']} 还没有锁定首帧")
        source = i2v_source(prod, shot, shots)
        if not source["exists"]:
            raise PermissionError(f"{shot['id']} 缺 I2V 源：{source['reason']}")
    fingerprint, specs = fingerprint_for(prod, [shot["id"] for shot in selected])
    approvals = load_approvals(prod)
    approvals["render"] = {
        "fingerprint": fingerprint,
        "shot_ids": [shot["id"] for shot in selected],
        "review_track": bool(review_track),
        "consumed": False,
        "at": int(time.time()),
    }
    save_approvals(prod, approvals)
    return {
        "ok": True,
        "fingerprint": fingerprint,
        "shot_ids": [shot["id"] for shot in selected],
        "count": len(specs),
        "review_track": bool(review_track),
        "shots": specs,
        "note": "改分镜、换父图或失败重试都会作废这份确认。不扣积分。",
    }


def consume_render_fingerprint(
    prod: Path,
    fingerprint: Optional[str],
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
) -> str:
    if not fingerprint:
        raise PermissionError("出片需要先 prepare 并确认指纹")
    live, _specs = fingerprint_for(prod, shot_ids)
    if live != fingerprint:
        raise PermissionError("指纹已过期：分镜、父图或参考图已变，请重新 prepare")
    approvals = load_approvals(prod)
    rec = approvals.get("render") or {}
    if rec.get("fingerprint") != fingerprint:
        raise PermissionError("没有这份出片确认，请先 prepare")
    if rec.get("consumed"):
        raise PermissionError("这份确认已用过，失败重试必须重新 prepare")
    want = [shot["id"] for shot in _selected(prod, shot_ids)]
    if rec.get("shot_ids") != want:
        raise PermissionError("确认的镜头和这次派出的不一致")
    rec["consumed"] = True
    rec["used_at"] = int(time.time())
    rec["review_track"] = bool(review_track)
    approvals["render"] = rec
    save_approvals(prod, approvals)
    return fingerprint
