"""One-shot production confirmations. Changing media bytes or the vendor request voids them."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from .gates import designed_end_frame, i2v_source, parent_still, require_fresh_gate, run_check
from .pipeline import episode_artifact_name, read_artifact, uses_pipeline
from .prompts import compile_h3_fields, compile_video_prompt, identity_refs, still_refs, video_mode
from .shot_repo import select_shots
from .store import exclusive_state_lock, load_approvals, save_approvals
from .vendor_request import COMPILER_VERSION, media_hash, vendor_request_from_package


def _shots(prod: Path, episode: Any = 1) -> list[dict]:
    from .shot_repo import list_shots

    return list_shots(prod, episode)


def _selected(prod: Path, shot_ids: Optional[list[str]], episode: Any = 1) -> list[dict]:
    return select_shots(prod, shot_ids, episode)


def _file_hash(prod: Path, rel: str) -> str:
    return media_hash(prod, rel)


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
    media = {
        "parent": _file_hash(prod, parent.get("path") or ""),
        "source": _file_hash(prod, source.get("path") or ""),
        "frame": _file_hash(prod, shot.get("frame") or f"04-frames/{shot['id']}.jpg"),
        "end_frame": _file_hash(prod, end.get("path") or ""),
        "refs": {rel: _file_hash(prod, rel) for rel in refs},
    }
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
        "media_hashes": media,
        "compiler_version": COMPILER_VERSION,
    }


def _pipeline_specs(prod: Path, shot_ids: Optional[list[str]], episode: Any = 1) -> list[dict]:
    selected = _selected(prod, shot_ids, episode)
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    frames = {
        item.get("shot_id"): item
        for item in (read_artifact(prod, episode_artifact_name("keyframes.json", episode)).get("keyframes") or [])
        if item.get("shot_id")
    }
    by_id = {item.get("shot_id"): item for item in (packages.get("packages") or packages.get("gen_packages") or [])}
    specs = []
    for shot in selected:
        sid = shot["id"]
        pkg = by_id.get(sid)
        if not pkg:
            raise ValueError(f"{sid} 没有生成包")
        request = vendor_request_from_package(prod, pkg, frames.get(sid) or {}, episode=episode, refs=[])
        specs.append({
            "id": sid,
            "vendor_request": request.to_dict(),
            "fingerprint": request.fingerprint(),
            "dest": f"{request.episode_id and '' or ''}{shot.get('frame')}",
        })
    return specs


def fingerprint_for(prod: Path, shot_ids: Optional[list[str]] = None, episode: Any = 1) -> tuple[str, list[dict]]:
    if uses_pipeline(prod):
        specs = _pipeline_specs(prod, shot_ids, episode)
        payload = {
            "compiler_version": COMPILER_VERSION,
            "episode": str(episode),
            "shot_ids": [item["id"] for item in specs],
            "requests": [item["vendor_request"] for item in specs],
        }
    else:
        shots = _shots(prod, episode)
        selected = _selected(prod, shot_ids, episode)
        specs = [shot_spec(prod, shot, shots) for shot in selected]
        payload = {
            "compiler_version": COMPILER_VERSION,
            "shot_ids": [item["id"] for item in specs],
            "shots": [
                {k: item[k] for k in ("id", "parent", "source", "refs", "mode", "dest", "compiled", "end_frame", "media_hashes")}
                for item in specs
            ],
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), specs


def prepare_render(
    prod: Path,
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode: Any = 1,
) -> dict:
    require_fresh_gate(prod, "C")
    from .pipeline import assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod)
        assert_keyframes_passed(prod)
    check = run_check(prod)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    selected = _selected(prod, shot_ids, episode)
    if not uses_pipeline(prod):
        shots = _shots(prod, episode)
        for shot in selected:
            dest = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
            if not dest.exists():
                raise PermissionError(f"{shot['id']} 还没有锁定首帧")
            source = i2v_source(prod, shot, shots)
            if not source["exists"]:
                raise PermissionError(f"{shot['id']} 缺 I2V 源：{source['reason']}")
    else:
        for shot in selected:
            dest = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
            if not dest.exists():
                raise PermissionError(f"{shot['id']} 还没有锁定首帧")
    fingerprint, specs = fingerprint_for(prod, [shot["id"] for shot in selected], episode)
    with exclusive_state_lock(prod, "approvals"):
        approvals = load_approvals(prod)
        approvals["render"] = {
            "fingerprint": fingerprint,
            "shot_ids": [shot["id"] for shot in selected],
            "review_track": bool(review_track),
            "consumed": False,
            "episode": episode,
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
        "note": "改分镜、换父图、换图字节或失败重试都会作废这份确认。不扣积分。",
    }


def consume_render_fingerprint(
    prod: Path,
    fingerprint: Optional[str],
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode: Any = 1,
) -> str:
    if not fingerprint:
        raise PermissionError("出片需要先 prepare 并确认指纹")
    with exclusive_state_lock(prod, "approvals"):
        live, _specs = fingerprint_for(prod, shot_ids, episode)
        if live != fingerprint:
            raise PermissionError("指纹已过期：分镜、父图、参考图或厂商请求已变，请重新 prepare")
        approvals = load_approvals(prod)
        rec = approvals.get("render") or {}
        if rec.get("fingerprint") != fingerprint:
            raise PermissionError("没有这份出片确认，请先 prepare")
        if rec.get("consumed"):
            raise PermissionError("这份确认已用过，失败重试必须重新 prepare")
        want = [shot["id"] for shot in _selected(prod, shot_ids, episode)]
        if rec.get("shot_ids") != want:
            raise PermissionError("确认的镜头和这次派出的不一致")
        rec["consumed"] = True
        rec["used_at"] = int(time.time())
        rec["review_track"] = bool(review_track)
        approvals["render"] = rec
        save_approvals(prod, approvals)
        return fingerprint
