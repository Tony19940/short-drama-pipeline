#!/usr/bin/env python3
"""Fill missing episode first/last frames from the shot's location master.

Used so every confirmed package has a 16:9 still on disk. Unique hero frames
can overwrite these later via place_codex_frame.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import episode_artifact_name  # noqa: E402
from director.pipeline import read_artifact  # noqa: E402
from place_codex_frame import episode_frame_dir  # noqa: E402

LOC = {
    "granary": "02-assets/scenes/granary/master.jpg",
    "granary-yard": "02-assets/scenes/granary-yard/master.jpg",
    "old-sluice": "02-assets/scenes/old-sluice/master.jpg",
    "ancient-shoal": "02-assets/scenes/ancient-shoal/master.jpg",
    "ancient-shoal-night": "02-assets/scenes/ancient-shoal-night/master.jpg",
    "modern-channel": "02-assets/scenes/modern-channel/master.jpg",
    "dry-bed": "02-assets/scenes/dry-bed/master.jpg",
    "elephant-camp": "02-assets/scenes/elephant-camp/master.jpg",
    "water-gate": "02-assets/scenes/water-gate/master.jpg",
    "river-bend": "02-assets/scenes/river-bend/master.jpg",
}


def location_of(pkg: dict) -> str:
    cont = pkg.get("continuity") or {}
    state = pkg.get("state") or {}
    return str(cont.get("location_id") or state.get("location") or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", type=int, required=True)
    args = parser.parse_args()
    prod = Path(args.prod)
    if not prod.is_absolute():
        prod = (ROOT / prod).resolve()
    if prod.name == "010-gongpai":
        raise SystemExit("010-gongpai 禁止用空镜冒充首帧。走 scripts/render_codex_frames.py")
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", args.episode)).get("packages") or []
    if not packages:
        raise SystemExit("no packages")
    folder = prod / episode_frame_dir(args.episode)
    placed = []
    for pkg in packages:
        sid = pkg["shot_id"]
        loc = location_of(pkg)
        parent = LOC.get(loc)
        if not parent or not (prod / parent).exists():
            parent = "02-assets/scenes/ancient-shoal/master.jpg"
        src = prod / parent
        first = folder / f"{sid}.jpg"
        if not first.exists():
            subprocess.check_call(
                [
                    sys.executable,
                    str(SCRIPTS / "place_codex_frame.py"),
                    "--prod",
                    str(prod),
                    "--episode",
                    str(args.episode),
                    "--shot",
                    sid,
                    "--slot",
                    "first",
                    "--parent",
                    parent,
                    "--src",
                    str(src),
                ]
            )
            placed.append(f"{sid}.jpg")
        if pkg.get("keyframe_plan") == "first_last":
            last = folder / f"{sid}-last.jpg"
            if not last.exists():
                subprocess.check_call(
                    [
                        sys.executable,
                        str(SCRIPTS / "place_codex_frame.py"),
                        "--prod",
                        str(prod),
                        "--episode",
                        str(args.episode),
                        "--shot",
                        sid,
                        "--slot",
                        "last",
                        "--src",
                        str(first),
                    ]
                )
                placed.append(f"{sid}-last.jpg")
    print(json.dumps({"episode": args.episode, "placed": placed, "count": len(packages)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
