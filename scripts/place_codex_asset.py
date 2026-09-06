#!/usr/bin/env python3
"""Copy a Codex-generated still into productions/<slug>/02-assets.

Codex imagegen writes under $CODEX_HOME/generated_images. This script
converts to JPEG, writes the canonical slot, and keeps a versioned sibling
when the destination already exists.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import productions_root, safe_under

KINDS = {
    "character": ("02-assets/characters", ("master", "face", "front", "side", "back", "sheet")),
    "scene": ("02-assets/scenes", ("master", "door", "table", "sheet")),
    "prop": ("02-assets/props", ("master",)),
}


def dest_rel(kind: str, slug: str, slot: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind 只能是 {', '.join(KINDS)}")
    root, slots = KINDS[kind]
    if slot not in slots:
        raise ValueError(f"{kind} 的 slot 只能是 {', '.join(slots)}")
    if kind == "prop" and slot == "master":
        return f"{root}/{slug}/master.jpg"
    return f"{root}/{slug}/{slot}.jpg"


def next_version(path: Path) -> Path:
    stem = path.stem
    suffix = path.suffix
    n = 1
    while True:
        candidate = path.with_name(f"{stem}-v{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def write_jpeg(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(src)
    if image.mode in {"RGBA", "LA", "P"}:
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.save(dest, format="JPEG", quality=92, optimize=True)


def place(prod: Path, kind: str, slug: str, slot: str, src: Path, replace: bool = False) -> dict:
    rel = dest_rel(kind, slug, slot)
    prod = prod.resolve()
    dest = safe_under(prod, rel)
    previous = None
    if dest.exists() and not replace:
        previous = next_version(dest)
        shutil.copyfile(dest, previous)
    write_jpeg(src, dest)
    return {
        "ok": True,
        "dest": rel,
        "previous": str(previous.resolve().relative_to(prod)) if previous else None,
        "bytes": dest.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True, help="productions/<slug> or just the slug")
    parser.add_argument("--kind", required=True, choices=sorted(KINDS))
    parser.add_argument("--slug", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--src", required=True, help="Codex generated image path")
    parser.add_argument("--replace", action="store_true", help="overwrite without keeping -vN")
    args = parser.parse_args()

    src = Path(args.src).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"没有这张图：{src}")

    prod_arg = Path(args.prod).expanduser()
    prod = prod_arg if prod_arg.exists() else productions_root() / args.prod
    prod = prod.resolve()
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")

    result = place(prod, args.kind, args.slug, args.slot, src, replace=args.replace)
    print(f"wrote {prod / result['dest']}")
    if result["previous"]:
        print(f"kept {prod / result['previous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
