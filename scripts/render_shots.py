#!/usr/bin/env python3
"""Gate E: first-frame + locked character refs -> shot mp4.

Default: Hailuo 2.3 Fast (silent). Shots with tier=h3 go to MiniMax-H3
and MUST attach character face/master as reference images.

  python3 scripts/render_shots.py --prod productions/001-wip
  python3 scripts/render_shots.py --prod productions/001-wip --only SH010
  python3 scripts/render_shots.py --prod productions/001-wip --backend hailuo
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from video_backends import BACKENDS  # noqa: E402

H3_PER_EPISODE_CAP = 3


def load_shots(prod: Path, storyboard: str = "03-storyboard/shots.json") -> list[dict]:
    data = json.loads((prod / storyboard).read_text())
    return data["shots"]


def last_frame_path(prod: Path, shot: dict) -> Path:
    rel = str(shot.get("last_frame") or f"04-frames/{shot['id']}-last.jpg")
    return prod / rel


def character_refs(prod: Path, slugs: list[str], asset_root: str = "02-assets") -> list[Path]:
    paths: list[Path] = []
    missing: list[str] = []
    root = (asset_root or "02-assets").strip() or "02-assets"
    for slug in slugs:
        folder = prod / root / "characters" / slug
        face = folder / "face.jpg"
        master = folder / "master.jpg"
        if face.exists():
            paths.append(face)
        elif master.exists():
            paths.append(master)
        else:
            missing.append(slug)
        if master.exists() and face.exists() and master not in paths:
            paths.append(master)
    if missing:
        raise SystemExit(
            "Gate E blocked: these characters have no face.jpg or master.jpg: "
            + ", ".join(missing)
            + "\nLock Gate B assets first. See QUALITY.md."
        )
    # first_frame already counts as one image; keep extras in the 5-free window
    return paths[:4]


def assemble(prod: Path) -> None:
    script = ROOT / "scripts" / "assemble.sh"
    subprocess.check_call(["bash", str(script), str(prod)])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True, help="productions/<slug>")
    p.add_argument(
        "--backend",
        choices=["auto"] + sorted(BACKENDS),
        default="auto",
        help="auto = shot.tier (fast->hailuo, h3->h3). default auto",
    )
    p.add_argument(
        "--storyboard",
        default="03-storyboard/shots.json",
        help="relative shots table, e.g. 03-storyboard/shots.b.json",
    )
    p.add_argument(
        "--video-dir",
        default="05-shots",
        help="relative output folder for shot mp4s",
    )
    p.add_argument("--only", nargs="*", help="shot ids, e.g. SH001 SH010")
    p.add_argument("--assemble-only", action="store_true")
    p.add_argument("--skip-assemble", action="store_true")
    p.add_argument(
        "--review-track",
        action="store_true",
        help="after shots, mix Chinese scratch VO + captions (Gate E+)",
    )
    args = p.parse_args()

    prod = Path(args.prod).resolve()
    if args.assemble_only:
        assemble(prod)
        return

    shots = load_shots(prod, args.storyboard)
    subprocess.check_call(
        [sys.executable, str(ROOT / "scripts" / "check_prod.py"), "--prod", str(prod)]
    )
    want = set(args.only or [])
    selected = [s for s in shots if not want or s["id"] in want]
    h3_count = sum(1 for s in shots if s.get("tier") == "h3")
    if args.backend == "auto" and h3_count > H3_PER_EPISODE_CAP:
        raise SystemExit(
            f"Gate E blocked: {h3_count} shots marked tier=h3, cap is {H3_PER_EPISODE_CAP}. "
            "See QUALITY.md."
        )

    backends: dict[str, object] = {}

    def get_backend(name: str):
        if name not in backends:
            backends[name] = BACKENDS[name]()
        return backends[name]

    for shot in selected:
        slugs = list(shot.get("characters") or [])
        if slugs == [] and shot.get("tier") == "h3":
            print(f"warn {shot['id']}: h3 shot with no characters (empty scene ok)")
        refs = character_refs(prod, slugs, str(shot.get("asset_root") or "02-assets")) if slugs else []
        if slugs and not refs:
            raise SystemExit(f"{shot['id']} listed characters but no ref files")

        dest = prod / args.video_dir / f"{shot['id']}.mp4"
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  {shot['id']} already has {dest.relative_to(prod)}, skip create")
            continue
        from director.gates import designed_end_frame, i2v_source
        from director.prompts import compile_video_prompt, still_refs, video_mode

        source = i2v_source(prod, shot, shots)
        image = prod / source["path"]
        print(f"  {shot['id']} source={source['kind']} {source['path']} ({source['reason']})")
        if not image.exists():
            raise SystemExit(f"missing first frame {image}")

        if args.backend == "auto":
            name = "h3" if shot.get("tier") == "h3" else "hailuo"
        else:
            name = "h3" if args.backend == "minimax" else args.backend
        if name == "h3" and os.environ.get("COMPSHARE_API_KEY", "").strip():
            name = "compshare"
        if name == "auto" and os.environ.get("ARK_API_KEY", "").strip() and not os.environ.get("MINIMAX_API_KEY", "").strip():
            name = "seedance"
        backend = get_backend(name)

        extra_refs = []
        for rel in still_refs(prod, shot):
            path = prod / rel
            if path.exists() and path not in refs and path not in extra_refs:
                extra_refs.append(path)
        refs = (refs + extra_refs)[:4]
        if name in {"seedance", "ark"}:
            from director.pipeline import read_artifact
            from director.prompts import compile_seedance_prompt

            spec = next(
                (
                    item
                    for item in (read_artifact(prod, "shot_specs.json").get("shot_specs") or [])
                    if item.get("shot_id") == shot["id"]
                ),
                {},
            )
            prompt = compile_seedance_prompt(shot, spec)
        else:
            prompt = compile_video_prompt(shot, silent=True, refs=[str(r) for r in refs])
        mode = video_mode(shot, source["kind"], [str(r) for r in refs])
        end_info = designed_end_frame(prod, shot)
        if not end_info["ok"]:
            raise SystemExit(end_info["reason"])
        end = prod / end_info["path"] if end_info["path"] else None
        print(f"  {shot['id']} mode={mode} end={end_info['path'] or 'none'}")
        from director.pipeline import duration_for_shot

        seconds = int(round(duration_for_shot(prod, shot["id"], float(shot.get("seconds") or 4))))
        try:
            backend.render(image, prompt, seconds, dest, refs=refs, mode=mode, last_frame=end)
        except TypeError:
            backend.render(image, prompt, seconds, dest, refs=refs)
        last = last_frame_path(prod, shot)
        last.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            ["ffmpeg", "-y", "-sseof", "-0.05", "-i", str(dest), "-frames:v", "1", str(last)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  last frame {last}")
        nxt = next((x for x in shots if x.get("from") == shot["id"] and x.get("cut") == "continue"), None)
        if nxt:
            print(f"  next {nxt['id']} will I2V this last frame")

    if args.review_track:
        selected_ids = [s["id"] for s in selected]
        out = prod / "06-export" / ("preview-vo.mp4" if not want else "preview-partial-vo.mp4")
        subprocess.check_call(
            [
                sys.executable,
                str(ROOT / "scripts" / "mix_review_track.py"),
                "--prod",
                str(prod),
                "--only",
                *selected_ids,
                "--out",
                str(out),
            ]
        )

    if not args.skip_assemble:
        assemble(prod)


if __name__ == "__main__":
    main()
