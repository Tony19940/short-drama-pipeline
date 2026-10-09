#!/usr/bin/env python3
"""Name cards and place/time cards: preview on first frames, then overlay on the cut with a real Khmer font.

    python3 scripts/render_name_cards.py --prod productions/012-khleang-moeung --episode 1 --preview
    python3 scripts/render_name_cards.py --prod ... --episode 1 --video 06-export/ep01.mp4 --out 06-export/ep01.cards.mp4
    python3 scripts/render_name_cards.py --prod ... --episode 1 --video ... --out ... --dry-run

Words come from the dialogue gate (intro captions `name · role`, place_time captions `time · place`); placement
from the shot table (`name_card`, `place_card`); times from the cut (`cut.json` timeline). Core Text does the
shaping; no model draws text.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director.context import context_for, using_context  # noqa: E402
from director.lines import read_lines  # noqa: E402
from director.name_cards import (  # noqa: E402
    card_texts,
    coretext_binary,
    ffmpeg_overlay_args,
    overlay_plan,
    place_texts,
    placed_cards,
    placed_place_cards,
    preview_on_frame,
    render_card,
    validate_name_cards,
    video_size,
)
from director.pipeline import episode_artifact_name, episode_label, read_artifact  # noqa: E402

SWIFT = ROOT / "scripts" / "khmer_coretext.swift"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prod", required=True, type=Path)
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--preview", action="store_true", help="stamp each card on its shot's first frame")
    parser.add_argument("--video", type=Path, help="edited episode to overlay")
    parser.add_argument("--out", type=Path, help="output video")
    parser.add_argument("--cut", type=Path, help="cut.json with the timeline (default: the episode's cut artifact)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    prod = (args.prod if args.prod.is_absolute() else ROOT / args.prod).resolve()
    ctx = context_for(prod, args.episode)
    with using_context(ctx):
        table = read_artifact(prod, episode_artifact_name("shot_list.json", args.episode))
        lines = read_lines(prod, args.episode)
    errors, warnings = validate_name_cards(table, lines)
    for line in warnings:
        print("warn ", line)
    if errors:
        for line in errors:
            print("ERROR", line, file=sys.stderr)
        return 1
    texts = card_texts(lines)
    places = place_texts(lines)
    cards = placed_cards(table) + placed_place_cards(table)
    if not cards:
        print("no shot carries a name_card or place_card")
        return 0

    def words(card: dict) -> tuple[str, str, str, str]:
        """(line 1, line 2, label, file stem) for a name card or a place/time card."""
        if card.get("kind") == "place":
            text = places[card["scene_id"]]
            return text["line1_km"], text["line2_km"], f"{text['km']} ({text['zh']})", f"place-{card['scene_id']}"
        text = texts[card["character"]]
        return text["name_km"], text["role_km"], f"{text['km']} ({text['zh']})", card["character"]
    label = episode_label(args.episode) or f"ep{args.episode:02d}"
    folder = prod / "03-storyboard" / "name-cards" / label
    coretext = None if args.dry_run else coretext_binary(SWIFT)

    if args.preview:
        frame_dir = prod / ctx.frame_dir()
        for shot, card in cards:
            sid = shot["shot_id"]
            line1, line2, label, stem = words(card)
            frame = frame_dir / f"{sid}.jpg"
            print(f"{sid} {stem}: {label} side={card['side']} x={card['x']} y={card['y']} "
                  f"{card['start_sec']}+{card['hold_sec']}s")
            if args.dry_run or not frame.exists():
                continue
            from PIL import Image

            height = Image.open(frame).height
            png = render_card(line1, line2, height, folder / f"{stem}-{height}p.png", coretext)
            out = preview_on_frame(frame, png, card, folder / f"preview-{sid}-{stem}.jpg")
            print("  preview", out.relative_to(prod))

    if args.video:
        if not args.out:
            parser.error("--video needs --out")
        video = args.video if args.video.is_absolute() else prod / args.video
        out = args.out if args.out.is_absolute() else prod / args.out
        with using_context(ctx):
            cut = read_artifact(prod, episode_artifact_name("cut.json", args.episode)) if not args.cut else {}
        if args.cut:
            import json

            cut = json.loads((args.cut if args.cut.is_absolute() else prod / args.cut).read_text(encoding="utf-8"))
        plan = overlay_plan(table, cut)
        if not plan:
            print("no carded shot survives the cut")
            return 0
        width, height = video_size(video)
        pngs = []
        for card in plan:
            line1, line2, label, stem = words(card)
            print(f"{card['shot_id']} {stem}: {card['t0']}s–{card['t1']}s {label}")
            if not args.dry_run:
                pngs.append(render_card(line1, line2, height, folder / f"{stem}-{height}p.png", coretext))
            else:
                pngs.append(folder / f"{stem}-{height}p.png")
        command = ffmpeg_overlay_args(video, plan, pngs, out, width, height)
        if args.dry_run:
            print(" ".join(command))
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
