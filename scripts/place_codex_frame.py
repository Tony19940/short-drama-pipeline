#!/usr/bin/env python3
"""Copy a Codex-generated still into productions/<slug>/04-frames.

Use this for 6.1 keyframes. Do not land shot frames in 02-assets.

Every landing records where it came from: a sidecar `SH001.json` next to the
jpg names the parent image it was edited from, the source file hash, and the
previous version that was kept. A first frame must name its parent (the scene
plate or the previous locked first frame); a last frame defaults to its own
first frame.
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

from director.paths import productions_root, safe_under
from place_codex_asset import next_version, write_jpeg

SHOT_ID = re.compile(r"^SH\d{3}$")
SLOTS = {
    "first": "{shot}.jpg",
    "last": "{shot}-last.jpg",
}
PARENT_ROOTS = ("02-assets/", "04-frames/")


def dest_rel(shot_id: str, slot: str) -> str:
    if not SHOT_ID.match(shot_id):
        raise ValueError("shot 必须是 SH001 这种编号")
    if slot not in SLOTS:
        raise ValueError("slot 只能是 first 或 last")
    return "04-frames/" + SLOTS[slot].format(shot=shot_id)


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


def resolve_parent(prod: Path, shot_id: str, slot: str, parent: Optional[str]) -> str:
    rel = str(parent or "").strip().replace("\\", "/")
    if not rel:
        if slot == "last":
            rel = dest_rel(shot_id, "first")
        else:
            raise ValueError("首帧必须写 --parent：本场空镜 master.jpg 或上一镜已锁首帧。禁止对着空气文生")
    rel = rel.lstrip("./")
    if not rel.startswith(PARENT_ROOTS):
        raise ValueError("父图只能来自 02-assets/（空镜、护照）或 04-frames/（已锁帧）")
    path = safe_under(prod, rel)
    if not path.exists():
        raise FileNotFoundError(f"父图不存在：{rel}")
    if path.resolve() == safe_under(prod, dest_rel(shot_id, slot)).resolve():
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
) -> dict:
    rel = dest_rel(shot_id, slot)
    prod = prod.resolve()
    parent_rel = resolve_parent(prod, shot_id, slot, parent)
    dest = safe_under(prod, rel)
    previous = None
    if dest.exists() and not replace:
        previous = next_version(dest)
        shutil.copyfile(dest, previous)
        old_meta = sidecar_path(dest)
        if old_meta.exists():
            shutil.move(str(old_meta), str(sidecar_path(previous)))
    write_jpeg(src, dest)
    previous_rel = str(previous.resolve().relative_to(prod)) if previous else None
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
    }
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
    parser.add_argument("--parent", default="", help="首帧必填：02-assets/scenes/<id>/master.jpg 或 04-frames/SHxxx.jpg；尾帧默认本镜首帧")
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
        result = place(prod, args.shot.upper(), args.slot, src, replace=args.replace, parent=args.parent)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))
    print(f"wrote {prod / result['dest']}  (parent {result['parent']})")
    if result["previous"]:
        print(f"kept {prod / result['previous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
