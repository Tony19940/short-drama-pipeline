#!/usr/bin/env python3
"""Copy a Codex-generated still into productions/<slug>/04-frames.

Use this for 6.1 keyframes. Do not land shot frames in 02-assets.

Every landing records where it came from: a sidecar `SH001.json` next to the
jpg names the parent image it was edited from, the source file hash, and the
previous version that was kept. A first frame defaults to the previous
same-setup verified video end, then a planned end/legacy still reference. Parent locks
face and space, not a finished action: first-frame *content* follows this shot's
`in_from` (t=0), not the parent's already-completed result. A scene
`master.jpg` is refused when a locked previous same-scene frame exists, unless
`--allow-master`. Both `end` and the legacy `last` slot are planned ends,
defaulting to their own first frame. Neither slot is an extracted video end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PIL import Image

from director.defaults import production_aspect
from director.paths import productions_root, safe_under
from director.review_state import REVIEW_STATES, can_use_as_parent, default_place_state, normalize_review_state
from place_codex_asset import next_version

SHOT_ID = re.compile(r"^SH\d{3}$")
SCENE_MASTER = re.compile(r"^02-assets/scenes/[^/]+/master\.jpg$")
SLOTS = {
    "first": "{shot}.jpg",
    "end": "{shot}-end.jpg",
    "last": "{shot}-last.jpg",
}
FRAME_ROLES = {"first": "planned_start", "end": "planned_end", "last": "planned_end"}
PARENT_ROOTS = ("02-assets/", "04-frames/", "05-shots/")
ASPECT_PIXELS = {
    "16:9": (1672, 941),
    "9:16": (941, 1672),
}
FRAME_SIZE = ASPECT_PIXELS["16:9"]
ASPECT_TOLERANCE = 0.04


class AspectMismatchError(ValueError):
    """Source pixels are not the declared aspect and --crop was not given."""


def episode_frame_dir(episode=1, prod: Optional[Path] = None) -> str:
    if prod is not None:
        from director.context import context_for

        return context_for(prod, episode).frame_dir()
    from director.pipeline import episode_frame_dir as _episode_frame_dir

    return _episode_frame_dir(episode)


def _t(value) -> str:
    return str(value or "").strip()


def is_scene_master(rel: str) -> bool:
    path = _t(rel).replace("\\", "/").lstrip("./")
    return bool(SCENE_MASTER.match(path))


def load_shot_table_rows(prod: Path, episode=1) -> list[dict]:
    from director.context import context_for
    from director.pipeline import episode_label
    from director.production import load_json

    ctx = context_for(prod, episode)
    data = ctx.read_artifact("shot_list.json", required=ctx.mode == "registered")
    shots = list(data.get("shots") or [])
    if not shots and ctx.mode != "registered":
        label = episode_label(episode)
        rel = "03-storyboard/shot_list.json" if not label else f"03-storyboard/shot_list.{label}.json"
        shots = list(load_json(prod, rel, {}).get("shots") or [])
    return shots


def previous_same_scene_shot(prod: Path, shot_id: str, episode=1) -> Optional[dict]:
    rows = load_shot_table_rows(prod, episode)
    scene = ""
    for row in rows:
        if _t(row.get("shot_id") or row.get("id")) == shot_id:
            scene = _t(row.get("scene_id"))
            break
    if not scene:
        return None
    prev = None
    for row in rows:
        sid = _t(row.get("shot_id") or row.get("id"))
        if sid == shot_id:
            return prev
        if _t(row.get("scene_id")) == scene:
            prev = row
    return prev


def identity_gate_of(prod: Path, rel: str) -> str:
    return _t(read_sidecar(prod, rel).get("identity_gate"))


def previous_passing_first_frame(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """Previous same-scene first frame, only when sidecar identity_gate=pass."""
    prev = previous_same_scene_shot(prod, shot_id, episode)
    if not prev:
        return None
    pid = _t(prev.get("shot_id") or prev.get("id"))
    if not SHOT_ID.match(pid):
        return None
    first = dest_rel(pid, "first", episode, prod=prod)
    if not safe_under(prod, first).exists():
        return None
    if identity_gate_of(prod, first) == "pass":
        return first
    return None


def previous_same_scene_frame(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """First-frame visual parent; a planned end is not actual video evidence."""
    return previous_same_scene_parent(prod, shot_id, episode)


def previous_same_scene_parent(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """Same-setup parent, preferring a verified generated end over planned stills.

    A new camera setup does not inherit the previous shot's composition.
    """
    from director.setup_anchors import resolve_continuity_parent

    return resolve_continuity_parent(prod, shot_id, episode)


def parent_chain_errors(prod: Path, shots: Optional[list] = None, episode=1) -> list[str]:
    """Gate D helper: do not chain a fail/awaiting parent; do not skip a passing first.

    Shots without a sidecar are legacy and skipped.
    """
    rows = list(shots) if shots is not None else load_shot_table_rows(prod, episode)
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = _t(row.get("shot_id") or row.get("id"))
        if not SHOT_ID.match(sid):
            continue
        meta = read_sidecar(prod, dest_rel(sid, "first", episode, prod=prod))
        if not meta:
            continue
        parent = _t(meta.get("parent"))
        prev = previous_same_scene_shot(prod, sid, episode)
        if not prev:
            continue
        pid = _t(prev.get("shot_id") or prev.get("id"))
        if not SHOT_ID.match(pid):
            continue
        prev_first = dest_rel(pid, "first", episode, prod=prod)
        if not safe_under(prod, prev_first).exists():
            continue
        gate = identity_gate_of(prod, prev_first)
        parent_gate = identity_gate_of(prod, parent) if parent and not parent.startswith("02-assets/") else ""
        if parent and not parent.startswith("02-assets/"):
            parent_role = frame_role_info(prod, parent)
            if parent_role["frame_role"] == "generated_end" and parent_role["provenance_status"] != "verified":
                errors.append(f"{sid} parent {parent} generated_end provenance is stale")
                continue
        if parent_gate in {"fail", "awaiting_user"}:
            errors.append(f"{sid} parent {parent} identity_gate={parent_gate}")
            continue
        if gate == "pass":
            if is_scene_master(parent) and not meta.get("allow_master"):
                from director.setup_anchors import same_setup, shot_row

                current = shot_row(prod, sid, episode)
                if current is None or same_setup(prev, current):
                    errors.append(
                        f"{sid} parent is scene master ({parent}); previous same-setup frame is {prev_first}"
                    )
        elif gate in {"fail", "awaiting_user"} and parent == prev_first:
            errors.append(f"{sid} parent is {prev_first} with identity_gate={gate}; should be scene master")
    return errors


def dest_rel(shot_id: str, slot: str, episode=1, prod: Optional[Path] = None) -> str:
    if not SHOT_ID.match(shot_id):
        raise ValueError("shot 必须是 SH001 这种编号")
    if slot not in SLOTS:
        raise ValueError("slot 只能是 first、end 或 legacy last")
    return episode_frame_dir(episode, prod=prod) + "/" + SLOTS[slot].format(shot=shot_id)


def frame_pixel_size(aspect: str = "16:9") -> tuple[int, int]:
    return ASPECT_PIXELS.get(str(aspect or "16:9"), ASPECT_PIXELS["16:9"])


def _center_crop_to_aspect(image: Image.Image, target_ratio: float) -> Image.Image:
    w, h = image.size
    if w <= 0 or h <= 0:
        return image
    src_ratio = w / h
    if src_ratio > target_ratio:
        new_w = max(1, int(round(h * target_ratio)))
        left = max(0, (w - new_w) // 2)
        return image.crop((left, 0, left + new_w, h))
    new_h = max(1, int(round(w / target_ratio)))
    top = max(0, (h - new_h) // 2)
    return image.crop((0, top, w, top + new_h))


def write_frame_jpeg(src: Path, dest: Path, *, aspect: str = "16:9", crop: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as raw:
        image = raw.convert("RGB") if raw.mode != "RGB" else raw.copy()
    target = frame_pixel_size(aspect)
    target_ratio = target[0] / target[1]
    src_ratio = image.size[0] / image.size[1] if image.size[1] else target_ratio
    if abs(src_ratio - target_ratio) > ASPECT_TOLERANCE:
        if not crop:
            raise AspectMismatchError(
                f"源图 {image.size[0]}×{image.size[1]} 不是 {aspect}，加 --crop 裁切，禁止拉伸"
            )
        image = _center_crop_to_aspect(image, target_ratio)
    if image.size != target:
        image = image.resize(target, Image.Resampling.LANCZOS)
    image.save(dest, format="JPEG", quality=92, optimize=True)


def sidecar_path(dest: Path) -> Path:
    return dest.with_suffix(".json")


def read_sidecar(prod: Path, rel: str) -> dict:
    path = sidecar_path(safe_under(prod, rel))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_role_info(prod: Path, rel: str) -> dict:
    """Describe a frame without inferring its role from a `-last` filename.

    A generated end is usable only while both the extracted image and its
    source video match the recorded hashes. This is extraction provenance,
    separate from the image's identity/content review.
    """
    meta = read_sidecar(prod, rel)
    role = _t(meta.get("frame_role")) or "unknown"
    info = {"frame_role": role, "provenance_status": "unknown", "legacy": not bool(meta.get("frame_role")), "warnings": []}
    if role == "unknown":
        info["warnings"].append(f"{rel}: frame_role=unknown (legacy); 文件名不能证明是视频实际尾帧")
        return info
    if role in {"planned_start", "planned_end"}:
        info["provenance_status"] = "planned"
        if role == "planned_end":
            info["warnings"].append(f"{rel}: planned_end 是设计目标，只能作视觉参考，不能证明视频已到达 out_to")
        if meta.get("legacy_slot"):
            info["legacy"] = True
            info["warnings"].append(f"{rel}: legacy --slot last；新设计尾帧请用 --slot end")
        return info
    if role != "generated_end":
        info["provenance_status"] = "invalid"
        info["warnings"].append(f"{rel}: 未知 frame_role={role}")
        return info
    extraction = meta.get("extraction") or {}
    video_rel = _t(meta.get("source_video"))
    try:
        image = safe_under(prod, rel)
        video = safe_under(prod, video_rel) if video_rel else None
        valid = (
            isinstance(extraction, dict)
            and bool(_t(extraction.get("method")))
            and extraction.get("position") == "video_end"
            and bool(video_rel)
            and video is not None and video.is_file()
            and image.is_file()
            and _t(meta.get("dest_sha256")) == _sha256(image)
            and _t(meta.get("source_video_sha256")) == _sha256(video)
        )
    except (OSError, ValueError):
        valid = False
    info["source_video"] = video_rel
    info["provenance_status"] = "verified" if valid else "stale"
    if not valid:
        info["warnings"].append(f"{rel}: generated_end 来源缺失或文件 hash 已变，不能用于实际尾帧连戏")
    return info


def record_generated_end(
    prod: Path,
    shot_id: str,
    *,
    frame_rel: str,
    video_rel: str,
    extraction_method: str,
    offset_sec: Optional[float] = None,
    identity_gate: Optional[str] = None,
    episode=1,
) -> dict:
    """Record an end immediately after a renderer has extracted it from video.

    This helper does not extract, move, or review media. Renderers must call it
    after a successful extraction; Codex still placement cannot call this role.
    New extracted ends live in the context's shot directory so planned stills stay intact.
    """
    if not SHOT_ID.match(shot_id):
        raise ValueError("shot 必须是 SH001 这种编号")
    frame_rel = _t(frame_rel).replace("\\", "/").lstrip("./")
    video_rel = _t(video_rel).replace("\\", "/").lstrip("./")
    from director.context import context_for

    ctx = context_for(prod, episode)
    if (frame_rel != f"{ctx.shot_dir()}/{shot_id}-last.jpg"
            or video_rel != f"{ctx.shot_dir()}/{shot_id}.mp4"):
        raise ValueError(f"实际尾帧和源视频必须放在当前版本 {ctx.shot_dir()}/；不能覆盖设计帧或其他版本")
    frame = safe_under(prod, frame_rel)
    video = safe_under(prod, video_rel)
    if frame.name != f"{shot_id}-last.jpg" or video.name != f"{shot_id}.mp4" or frame.parent != video.parent:
        raise ValueError("实际尾帧须为源视频同目录的 SHxxx-last.jpg，对应 SHxxx.mp4")
    if not frame.is_file() or not video.is_file():
        raise FileNotFoundError("实际尾帧或源视频不存在")
    if not _t(extraction_method):
        raise ValueError("必须记录实际抽帧方法 extraction_method")
    meta = {
        "shot": shot_id, "slot": "generated_end", "frame_role": "generated_end",
        "dest": frame_rel, "dest_sha256": _sha256(frame),
        "source_video": video_rel, "source_video_sha256": _sha256(video),
        "extracted_at": int(time.time()), "tool": "video-extractor",
        "context": ctx.to_dict(),
        "extraction": {"method": _t(extraction_method), "position": "video_end"},
        "identity_gate": normalize_review_state(identity_gate, default=default_place_state()),
    }
    if offset_sec is not None:
        meta["extraction"]["offset_sec"] = float(offset_sec)
    sidecar_path(frame).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return frame_role_info(prod, frame_rel)


def resolve_generated_end(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """Approved, hash-bound video end only; legacy unknown is never called actual."""
    from director.context import context_for

    ctx = context_for(prod, episode)
    expected_video = f"{ctx.shot_dir()}/{shot_id}.mp4"
    for rel in (f"{ctx.shot_dir()}/{shot_id}-last.jpg", dest_rel(shot_id, "last", episode, prod=prod)):
        info = frame_role_info(prod, rel)
        if (info["frame_role"] == "generated_end" and info["provenance_status"] == "verified"
                and info.get("source_video") == expected_video and can_use_as_parent(identity_gate_of(prod, rel))):
            return rel
    return None


def resolve_parent(
    prod: Path,
    shot_id: str,
    slot: str,
    parent: Optional[str],
    episode=1,
    allow_master: bool = False,
) -> str:
    from director.context import context_for

    ctx = context_for(prod, episode)
    rel = str(parent or "").strip().replace(chr(92), "/")
    if not rel:
        if slot in {"end", "last"}:
            rel = dest_rel(shot_id, "first", episode=episode, prod=prod)
        else:
            rel = previous_same_scene_parent(prod, shot_id, episode) or ""
            if not rel:
                raise ValueError("首帧必须写 --parent：本场空镜 master.jpg 或上一镜已过闸尾帧/首帧。禁止对着空气文生")
    rel = rel.lstrip("./")
    frame_prefix = ctx.frame_dir().rstrip("/") + "/"
    shot_prefix = ctx.shot_dir().rstrip("/") + "/"
    if not rel.startswith(("02-assets/", frame_prefix, shot_prefix)):
        raise ValueError("父图只能来自 02-assets/、本版本设计帧目录或来源已核实的本版本视频尾帧")
    if not rel.startswith("02-assets/"):
        role = frame_role_info(prod, rel)
        if rel.startswith(shot_prefix) or role["frame_role"] == "generated_end":
            if role["frame_role"] != "generated_end" or role["provenance_status"] != "verified":
                raise ValueError(f"父图 {rel} 不是来源已核实的 generated_end")
        gate = identity_gate_of(prod, rel) or "unknown"
        own_first = dest_rel(shot_id, "first", episode=episode, prod=prod)
        if slot in {"end", "last"} and rel == own_first:
            if gate in {"fail", "awaiting_user"}:
                raise ValueError(f"父图 {rel} identity_gate={gate}，不能续。改用本场空镜 --allow-master")
        elif not can_use_as_parent(gate):
            raise ValueError(f"父图 {rel} identity_gate={gate}，未通过不能续。改用本场空镜 --allow-master")
    if slot == "first" and is_scene_master(rel) and not allow_master:
        prev = previous_same_scene_parent(prod, shot_id, episode)
        if prev:
            raise ValueError(f"已有同机位上一镜 {prev}，首帧不要用空镜 master。换机位或需要空镜时加 --allow-master")
    path = safe_under(prod, rel)
    if not path.exists():
        raise FileNotFoundError(f"父图不存在：{rel}")
    if path.resolve() == safe_under(prod, dest_rel(shot_id, slot, episode=episode, prod=prod)).resolve():
        raise ValueError("父图不能是自己")
    return rel


def place(
    prod: Path,
    shot_id: str,
    slot: str,
    src: Path,
    replace: bool = False,
    parent: Optional[str] = None,
    tool: str = "codex-imagegen",
    episode=1,
    allow_master: bool = False,
    identity_gate: Optional[str] = None,
    checks: Optional[dict] = None,
    aspect: Optional[str] = None,
    crop: bool = False,
) -> dict:
    rel = dest_rel(shot_id, slot, episode=episode, prod=prod)
    prod = prod.resolve()
    parent_rel = resolve_parent(prod, shot_id, slot, parent, episode=episode, allow_master=allow_master)
    parent_info = frame_role_info(prod, parent_rel) if not parent_rel.startswith("02-assets/") else {}
    dest = safe_under(prod, rel)
    previous = None
    if dest.exists() and not replace:
        previous = next_version(dest)
        shutil.copyfile(dest, previous)
        old_meta = sidecar_path(dest)
        if old_meta.exists():
            shutil.move(str(old_meta), str(sidecar_path(previous)))
    write_frame_jpeg(src, dest, aspect=aspect or production_aspect(prod), crop=crop)
    previous_rel = str(previous.resolve().relative_to(prod)) if previous else None
    gate = normalize_review_state(identity_gate, default=default_place_state())
    dest_hash = _sha256(dest)
    src_hash = _sha256(src)
    evidence = dict(checks) if isinstance(checks, dict) else {}
    evidence.setdefault("image_sha256", dest_hash)
    meta = {
        "shot": shot_id,
        "slot": slot,
        "frame_role": FRAME_ROLES[slot],
        "legacy_slot": slot == "last",
        "dest": rel,
        "parent": parent_rel,
        "parent_sha256": _sha256(safe_under(prod, parent_rel)),
        "parent_frame_role": parent_info.get("frame_role", "asset"),
        "parent_provenance_status": parent_info.get("provenance_status", "asset"),
        "src": src.name,
        "src_sha256": src_hash,
        "dest_sha256": dest_hash,
        "placed_at": int(time.time()),
        "previous": previous_rel,
        "tool": tool,
        "allow_master": bool(allow_master),
        "identity_gate": gate,
        "review_rule_version": _t(evidence.get("rule_version")) or "place-v1",
    }
    if evidence:
        meta["checks"] = evidence
    warnings = list(parent_info.get("warnings") or [])
    if slot == "last":
        warnings.append("--slot last 仍是 planned_end；推荐 --slot end，不能当作 generated_end")
    if warnings:
        meta["warnings"] = warnings
    sidecar_path(dest).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "dest": rel,
        "parent": parent_rel,
        "frame_role": FRAME_ROLES[slot],
        "warnings": warnings,
        "previous": previous_rel,
        "sidecar": str(sidecar_path(dest).relative_to(prod)),
        "bytes": dest.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--shot", required=True, help="SH001")
    parser.add_argument("--slot", required=True, choices=sorted(SLOTS))
    parser.add_argument("--src", required=True)
    parser.add_argument("--parent", default="", help="首帧优先同机位已核实实际尾，其次设计尾/过闸首帧作参考。end/legacy last 是设计尾，默认本镜首帧")
    parser.add_argument(
        "--episode",
        default="1",
        help="集数或标签。1=04-frames/；2=04-frames/ep02/；ep01-v2=04-frames/ep01-v2/",
    )
    parser.add_argument("--allow-master", action="store_true", help="允许用场景空镜 master 当父图，即使同场上一镜已锁")
    parser.add_argument("--identity-gate", default="", choices=["", *REVIEW_STATES])
    parser.add_argument("--checks", default="", help="JSON object of identity checks")
    parser.add_argument("--aspect", default="", help="16:9 or 9:16; default from confirm / show policy")
    parser.add_argument("--crop", action="store_true", help="center-crop a wrong-ratio source; never stretch")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    src = Path(args.src).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"没有这张图：{src}")

    prod_arg = Path(args.prod).expanduser()
    prod = prod_arg if prod_arg.exists() else productions_root() / args.prod
    prod = prod.resolve()
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")

    try:
        checks = json.loads(args.checks) if args.checks else None
        result = place(
            prod,
            args.shot.upper(),
            args.slot,
            src,
            replace=args.replace,
            parent=args.parent,
            episode=args.episode,
            allow_master=args.allow_master,
            identity_gate=args.identity_gate or None,
            checks=checks,
            aspect=args.aspect or None,
            crop=args.crop,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))
    print(f"wrote {prod / result['dest']}  (parent {result['parent']})")
    if result["previous"]:
        print(f"kept {prod / result['previous']}")
    for warning in result["warnings"]:
        print(f"warn: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
