#!/usr/bin/env python3
"""Codex still-frame runner for 010-gongpai: candidate -> checklist -> place.

Does not write shots.json, does not render video, does not lock Gate D.
EP06-EP15 are blocked until the still gate and EP02 sample pass.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.codex_stills import (  # noqa: E402
    CHECK_KEYS,
    StillPackError,
    episode_still_blocked,
    first_frame_parent,
    identity_gate_from_checks,
    pack_codex_still_refs,
    parse_checks,
    review_role_for,
    scene_blocked_for_later,
)
from director.paths import productions_root, safe_under  # noqa: E402
from director.pipeline import episode_artifact_name, read_artifact  # noqa: E402
from director.prompts import rewrite_still_prompt  # noqa: E402
from place_codex_frame import (  # noqa: E402
    dest_rel,
    identity_gate_of,
    place,
    read_sidecar,
)


def _prod(arg: str) -> Path:
    path = Path(arg).expanduser()
    prod = path if path.exists() else productions_root() / arg
    prod = prod.resolve()
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")
    return prod


def _shots(prod: Path, episode: int) -> list[dict]:
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
    return list(table.get("shots") or [])


def _packages(prod: Path, episode: int) -> dict[str, dict]:
    data = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    return {item.get("shot_id"): item for item in (data.get("packages") or []) if item.get("shot_id")}


def _assets(prod: Path) -> dict:
    return read_artifact(prod, "assets.json")


def candidate_dir(prod: Path, episode) -> Path:
    from director.pipeline import episode_label, episode_number

    label = episode_label(episode) or f"ep{episode_number(episode):02d}"
    path = prod / ".director" / "candidates" / label
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_job(prod: Path, episode: int, shot: dict, packages: dict, assets: dict) -> dict:
    from director.continuity_hard import load_continuity_hard

    sid = str(shot.get("shot_id") or "")
    pkg = packages.get(sid) or {}
    location_id = str(shot.get("location_id") or (pkg.get("continuity") or {}).get("location_id") or "")
    parent, allow_master = first_frame_parent(
        prod, sid, episode, location_id, still_parent=str(shot.get("still_parent") or "")
    )
    role = review_role_for(episode, sid)
    hard = load_continuity_hard(prod)
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
    still_files = pack_codex_still_refs(
        prod,
        parent=parent,
        state=pkg.get("state") or shot.get("state"),
        assets=assets,
        table=table,
        hard=hard,
        episode=episode,
        strict_existing=True,
    )
    prompt = pkg.get("still_image_prompt") or pkg.get("image_prompt") or ""
    prompt = rewrite_still_prompt(prompt, still_files, assets)
    dest = dest_rel(sid, "first", episode)
    sidecar = read_sidecar(prod, dest)
    return {
        "shot_id": sid,
        "scene_id": shot.get("scene_id"),
        "episode": episode,
        "review_role": role,
        "parent": parent,
        "allow_master": bool(allow_master),
        "still_ref_files": still_files,
        "still_image_prompt": prompt,
        "dest": dest,
        "keyframe_plan": pkg.get("keyframe_plan") or "first",
        "identity_gate": sidecar.get("identity_gate") or "",
        "candidate": str((candidate_dir(prod, episode) / f"{sid}.png").relative_to(prod)),
    }


def plan_episode(prod: Path, episode: int) -> dict:
    blocked = episode_still_blocked(prod, episode)
    if blocked:
        raise SystemExit(blocked)
    shots = _shots(prod, episode)
    packages = _packages(prod, episode)
    assets = _assets(prod)
    jobs = []
    for shot in shots:
        sid = str(shot.get("shot_id") or "")
        scene = str(shot.get("scene_id") or "")
        reason = scene_blocked_for_later(prod, episode, scene, shots, current_shot_id=sid)
        if reason:
            jobs.append({"shot_id": sid, "scene_id": scene, "status": "blocked", "reason": reason})
            continue
        try:
            job = build_job(prod, episode, shot, packages, assets)
        except (StillPackError, ValueError, FileNotFoundError) as exc:
            jobs.append({"shot_id": sid, "scene_id": scene, "status": "error", "reason": str(exc)})
            continue
        dest = prod / job["dest"]
        if dest.exists():
            job["status"] = "landed"
        else:
            job["status"] = "ready"
        jobs.append(job)
    payload = {"episode": episode, "jobs": jobs}
    out = candidate_dir(prod, episode) / "plan.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["plan"] = str(out.relative_to(prod))
    return payload


def print_job(prod: Path, episode: int, shot_id: str) -> dict:
    shots = {str(item.get("shot_id")): item for item in _shots(prod, episode)}
    shot = shots.get(shot_id)
    if not shot:
        raise SystemExit(f"没有 {shot_id}")
    scene = str(shot.get("scene_id") or "")
    start = next((item.get("shot_id") for item in _shots(prod, episode) if item.get("scene_id") == scene), None)
    reason = scene_blocked_for_later(prod, episode, scene, _shots(prod, episode), current_shot_id=shot_id)
    if reason and shot_id != start:
        raise SystemExit(reason)
    job = build_job(prod, episode, shot, _packages(prod, episode), _assets(prod))
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return job


def _source_is_16x9(path: Path) -> bool:
    with Image.open(path) as image:
        w, h = image.size
    if h <= 0:
        return False
    return abs((w / h) - (16 / 9)) <= 0.03


def promote(prod: Path, episode: int, shot_id: str, src: Path, checks_raw: str) -> dict:
    blocked = episode_still_blocked(prod, episode)
    if blocked:
        raise SystemExit(blocked)
    shots = _shots(prod, episode)
    shot = next((item for item in shots if item.get("shot_id") == shot_id), None)
    if not shot:
        raise SystemExit(f"没有 {shot_id}")
    scene = str(shot.get("scene_id") or "")
    start = next((item.get("shot_id") for item in shots if item.get("scene_id") == scene), None)
    reason = scene_blocked_for_later(prod, episode, scene, shots, current_shot_id=shot_id)
    if reason and shot_id != start:
        raise SystemExit(reason)
    if not src.exists():
        raise SystemExit(f"没有这张图：{src}")
    if not _source_is_16x9(src):
        raise SystemExit(f"{src.name} 不是 16:9，拒绝落盘")
    checks = parse_checks(checks_raw)
    role = review_role_for(episode, shot_id)
    gate = identity_gate_from_checks(checks, role)
    job = build_job(prod, episode, shot, _packages(prod, episode), _assets(prod))
    cand = candidate_dir(prod, episode) / f"{shot_id}{src.suffix.lower() or '.png'}"
    if src.resolve() != cand.resolve():
        shutil.copyfile(src, cand)
    else:
        cand = src
    result = place(
        prod,
        shot_id,
        "first",
        src,
        parent=job["parent"],
        episode=episode,
        allow_master=job["allow_master"],
        identity_gate=gate,
        checks=checks,
        tool="codex-imagegen",
    )
    print(json.dumps({
        "ok": True,
        "shot_id": shot_id,
        "identity_gate": gate,
        "review_role": role,
        "checks": checks,
        "dest": result["dest"],
        "parent": result["parent"],
        "previous": result.get("previous"),
        "candidate": str(cand.relative_to(prod)),
        "stop_scene": gate in {"fail", "awaiting_user"} and role == "scene_start" or gate == "fail",
    }, ensure_ascii=False, indent=2))
    return result


def status_episode(prod: Path, episode: int) -> dict:
    shots = _shots(prod, episode)
    rows = []
    for shot in shots:
        sid = str(shot.get("shot_id") or "")
        rel = dest_rel(sid, "first", episode)
        exists = safe_under(prod, rel).exists()
        rows.append({
            "shot_id": sid,
            "scene_id": shot.get("scene_id"),
            "review_role": review_role_for(episode, sid),
            "exists": exists,
            "identity_gate": identity_gate_of(prod, rel) if exists else "",
            "parent": read_sidecar(prod, rel).get("parent") if exists else "",
        })
    payload = {"episode": episode, "shots": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", required=True, help="集数或标签：1、2、ep01-v2")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--print-job", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--shot", default="")
    parser.add_argument("--src", default="")
    parser.add_argument("--checks", default="", help="in_frame=pass,absent=pass,left_right=pass,costume=pass,bopha=pass,text=pass")
    args = parser.parse_args()
    prod = _prod(args.prod)
    if args.plan:
        payload = plan_episode(prod, args.episode)
        printable = {
            "episode": payload["episode"],
            "plan": payload.get("plan"),
            "ready": [j["shot_id"] for j in payload["jobs"] if j.get("status") == "ready"],
            "blocked": [j["shot_id"] for j in payload["jobs"] if j.get("status") == "blocked"],
            "error": [j["shot_id"] for j in payload["jobs"] if j.get("status") == "error"],
            "landed": [j["shot_id"] for j in payload["jobs"] if j.get("status") == "landed"],
        }
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0
    if args.status:
        status_episode(prod, args.episode)
        return 0
    if args.print_job:
        if not args.shot:
            raise SystemExit("--print-job 需要 --shot")
        print_job(prod, args.episode, args.shot.upper())
        return 0
    if args.promote:
        if not args.shot or not args.src:
            raise SystemExit("--promote 需要 --shot 和 --src")
        promote(prod, args.episode, args.shot.upper(), Path(args.src).expanduser().resolve(), args.checks)
        return 0
    raise SystemExit("指定 --plan / --print-job / --promote / --status")


if __name__ == "__main__":
    raise SystemExit(main())
