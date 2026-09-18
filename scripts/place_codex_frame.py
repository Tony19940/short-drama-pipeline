#!/usr/bin/env python3
"""Copy a Codex-generated still into productions/<slug>/04-frames.

Use this for 6.1 keyframes. Do not land shot frames in 02-assets.

Every landing records where it came from: a sidecar `SH001.json` next to the
jpg names the parent image it was edited from, the source file hash, and the
previous version that was kept. A first frame defaults to the previous
same-scene last frame (or that shot's first if there is no last). Parent locks
face and space, not a finished action: first-frame *content* follows this shot's
`in_from` (t=0), not the parent's already-completed result. A scene
`master.jpg` is refused when a locked previous same-scene frame exists, unless
`--allow-master`. A last frame defaults to its own first frame.
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

from director.paths import productions_root, safe_under
from place_codex_asset import next_version

SHOT_ID = re.compile(r"^SH\d{3}$")
SCENE_MASTER = re.compile(r"^02-assets/scenes/[^/]+/master\.jpg$")
SLOTS = {
    "first": "{shot}.jpg",
    "last": "{shot}-last.jpg",
}
PARENT_ROOTS = ("02-assets/", "04-frames/")
FRAME_SIZE = (1672, 941)


def episode_frame_dir(episode=1) -> str:
    from director.pipeline import episode_frame_dir as _episode_frame_dir

    return _episode_frame_dir(episode)


def _t(value) -> str:
    return str(value or "").strip()


def is_scene_master(rel: str) -> bool:
    path = _t(rel).replace("\\", "/").lstrip("./")
    return bool(SCENE_MASTER.match(path))


def load_shot_table_rows(prod: Path, episode=1) -> list[dict]:
    from director.pipeline import episode_artifact_name, episode_label, read_artifact
    from director.production import load_json

    name = episode_artifact_name("shot_list.json", episode)
    data = read_artifact(prod, name)
    shots = list(data.get("shots") or [])
    if not shots:
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
    first = dest_rel(pid, "first", episode)
    if not safe_under(prod, first).exists():
        return None
    if identity_gate_of(prod, first) == "pass":
        return first
    return None


def previous_same_scene_frame(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """First-frame continuity parent: previous last if present, else passing first."""
    return previous_same_scene_parent(prod, shot_id, episode)


def previous_same_scene_parent(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """Parent for this shot's first frame: same-scene previous `-last`, else passing first."""
    prev = previous_same_scene_shot(prod, shot_id, episode)
    if not prev:
        return None
    pid = _t(prev.get("shot_id") or prev.get("id"))
    if not SHOT_ID.match(pid):
        return None
    last = dest_rel(pid, "last", episode)
    last_path = safe_under(prod, last)
    if last_path.exists():
        gate = identity_gate_of(prod, last)
        if gate not in {"fail", "awaiting_user"}:
            return last
    return previous_passing_first_frame(prod, shot_id, episode)


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
        meta = read_sidecar(prod, dest_rel(sid, "first", episode))
        if not meta:
            continue
        parent = _t(meta.get("parent"))
        prev = previous_same_scene_shot(prod, sid, episode)
        if not prev:
            continue
        pid = _t(prev.get("shot_id") or prev.get("id"))
        if not SHOT_ID.match(pid):
            continue
        prev_first = dest_rel(pid, "first", episode)
        if not safe_under(prod, prev_first).exists():
            continue
        gate = identity_gate_of(prod, prev_first)
        parent_gate = identity_gate_of(prod, parent) if parent.startswith("04-frames/") else ""
        if parent_gate in {"fail", "awaiting_user"}:
            errors.append(f"{sid} parent {parent} identity_gate={parent_gate}")
            continue
        if gate == "pass":
            if is_scene_master(parent) and not meta.get("allow_master"):
                errors.append(
                    f"{sid} parent is scene master ({parent}); previous same-scene frame is {prev_first}"
                )
        elif gate in {"fail", "awaiting_user"} and parent == prev_first:
            errors.append(f"{sid} parent is {prev_first} with identity_gate={gate}; should be scene master")
    return errors


def dest_rel(shot_id: str, slot: str, episode=1) -> str:
    if not SHOT_ID.match(shot_id):
        raise ValueError("shot 必须是 SH001 这种编号")
    if slot not in SLOTS:
        raise ValueError("slot 只能是 first 或 last")
    return episode_frame_dir(episode) + "/" + SLOTS[slot].format(shot=shot_id)


def write_frame_jpeg(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(src)
    if image.mode in {"RGBA", "LA", "P"}:
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")
    if image.size != FRAME_SIZE:
        image = image.resize(FRAME_SIZE, Image.Resampling.LANCZOS)
    image.save(dest, format="JPEG", quality=92, optimize=True)


def sidecar_path(dest: Path) -> Path:
    return dest.with_suffix(".json")


def read_sidecar(prod: Path, rel: str) -> dict:
    path = sidecar_path(safe_under(prod, rel))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_parent(
    prod: Path,
    shot_id: str,
    slot: str,
    parent: Optional[str],
    episode=1,
    allow_master: bool = False,
) -> str:
    rel = str(parent or "").strip().replace(chr(92), "/")
    if not rel:
        if slot == "last":
            rel = dest_rel(shot_id, "first", episode=episode)
        else:
            rel = previous_same_scene_parent(prod, shot_id, episode) or ""
            if not rel:
                raise ValueError("首帧必须写 --parent：本场空镜 master.jpg 或上一镜已过闸尾帧/首帧。禁止对着空气文生")
    rel = rel.lstrip("./")
    if not rel.startswith(PARENT_ROOTS):
        raise ValueError("父图只能来自 02-assets/（空镜、护照）或 04-frames/（已锁帧）")
    if rel.startswith("04-frames/"):
        gate = identity_gate_of(prod, rel)
        if gate in {"fail", "awaiting_user"}:
            raise ValueError(f"父图 {rel} identity_gate={gate}，不能续。改用本场空镜 --allow-master")
    if slot == "first" and is_scene_master(rel) and not allow_master:
        prev = previous_same_scene_parent(prod, shot_id, episode)
        if prev:
            raise ValueError(f"已有同场上一镜 {prev}，首帧不要用空镜 master。需要空镜时加 --allow-master")
    path = safe_under(prod, rel)
    if not path.exists():
        raise FileNotFoundError(f"父图不存在：{rel}")
    if path.resolve() == safe_under(prod, dest_rel(shot_id, slot, episode=episode)).resolve():
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
) -> dict:
    rel = dest_rel(shot_id, slot, episode=episode)
    prod = prod.resolve()
    parent_rel = resolve_parent(prod, shot_id, slot, parent, episode=episode, allow_master=allow_master)
    dest = safe_under(prod, rel)
    previous = None
    if dest.exists() and not replace:
        previous = next_version(dest)
        shutil.copyfile(dest, previous)
        old_meta = sidecar_path(dest)
        if old_meta.exists():
            shutil.move(str(old_meta), str(sidecar_path(previous)))
    write_frame_jpeg(src, dest)
    previous_rel = str(previous.resolve().relative_to(prod)) if previous else None
    gate = _t(identity_gate)
    if not gate and slot == "first":
        gate = "pass"
    if gate and gate not in {"pass", "fail", "awaiting_user"}:
        raise ValueError("identity_gate 只能是 pass / fail / awaiting_user")
    meta = {
        "shot": shot_id,
        "slot": slot,
        "dest": rel,
        "parent": parent_rel,
        "src": src.name,
        "src_sha256": _sha256(src),
        "placed_at": int(time.time()),
        "previous": previous_rel,
        "tool": tool,
        "allow_master": bool(allow_master),
    }
    if gate:
        meta["identity_gate"] = gate
    if checks:
        meta["checks"] = checks
    sidecar_path(dest).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "dest": rel,
        "parent": parent_rel,
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
    parser.add_argument("--parent", default="", help="首帧默认同场上一镜 -last（没有则过闸首帧）；空镜 master 只许场第一镜或 --allow-master。尾帧默认本镜首帧")
    parser.add_argument(
        "--episode",
        default="1",
        help="集数或标签。1=04-frames/；2=04-frames/ep02/；ep01-v2=04-frames/ep01-v2/",
    )
    parser.add_argument("--allow-master", action="store_true", help="允许用场景空镜 master 当父图，即使同场上一镜已锁")
    parser.add_argument("--identity-gate", default="", choices=["", "pass", "fail", "awaiting_user"])
    parser.add_argument("--checks", default="", help="JSON object of identity checks")
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
        )
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))
    print(f"wrote {prod / result['dest']}  (parent {result['parent']})")
    if result["previous"]:
        print(f"kept {prod / result['previous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
