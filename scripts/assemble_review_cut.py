#!/usr/bin/env python3
"""Join a draft pass into one review cut of the episode (review-only: never an EDL, never a take).

    python3 scripts/assemble_review_cut.py --prod productions/012-khleang-moeung --episode 1
    python3 scripts/assemble_review_cut.py --prod ... --episode 1 --dir 05-shots/draft-480p --no-subs

Each clip is trimmed to its paper length (director.draft_review.trim_window), scene transitions follow the
shot table's `transition_out` (black / fade), the Khmer name and place/time cards are overlaid as placed in the
table, and Chinese review subtitles show every line with its delivery (电话 / 内心 / 画外). A place/time
caption with no `place_card` yet is shown on the scene's first shot and reported, so the gap is visible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director.context import context_for, using_context  # noqa: E402
from director.draft_review import (  # noqa: E402
    probe_seconds,
    speech_span,
    subtitle_chunks,
    subtitle_font,
    transcribe,
    trim_window,
)
from director.lines import read_lines  # noqa: E402
from director.name_cards import (  # noqa: E402
    card_position,
    card_texts,
    coretext_binary,
    normalize_card,
    normalize_place_card,
    place_texts,
    render_card,
)
from director.pipeline import episode_artifact_name, episode_label, read_artifact  # noqa: E402
from director.shot_table import cast_names  # noqa: E402

FPS = 24
TAG = {"phone": "电话", "inner": "内心", "off_camera": "画外", "narration": "旁白"}


def video_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def encode(src: Path, start: float, dur: float, out: Path, w: int, h: int, *, fade_in: float = 0, fade_out: float = 0) -> None:
    vf = [f"scale={w}:{h}", f"fps={FPS}", "setsar=1"]
    if fade_in:
        vf.append(f"fade=t=in:st=0:d={fade_in:.2f}")
    if fade_out:
        vf.append(f"fade=t=out:st={max(0, dur - fade_out):.2f}:d={fade_out:.2f}")
    af = f"aresample=48000,afade=t=in:d={max(0.03, fade_in):.2f},afade=t=out:st={max(0, dur - max(0.04, fade_out)):.3f}:d={max(0.04, fade_out):.2f}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                    "-vf", ",".join(vf), "-af", af, "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(out)], check=True)


def black(sec: float, out: Path, w: int, h: int) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}:d={sec:.2f}",
                    "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{sec:.2f}", "-c:v", "libx264", "-crf", "17",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)], check=True)


def sub_png(text: str, path: Path, size: int) -> tuple[int, int]:
    from PIL import Image, ImageDraw, ImageFont

    found = subtitle_font()
    font = ImageFont.truetype(found[0], size, index=found[1]) if found else ImageFont.load_default()
    box = ImageDraw.Draw(Image.new("RGBA", (10, 10))).textbbox((0, 0), text, font=font, stroke_width=3)
    img = Image.new("RGBA", (box[2] - box[0] + 16, box[3] - box[1] + 16), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((8 - box[0], 8 - box[1]), text, font=font, fill="white", stroke_width=3, stroke_fill="black")
    img.save(path)
    return img.size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prod", required=True, type=Path)
    parser.add_argument("--episode", default="1")
    parser.add_argument("--dir", default="", help="draft folder (default: <shot dir>/draft-480p)")
    parser.add_argument("--out", default="", help="output mp4 (default: <dir>/<EP>-review.mp4)")
    parser.add_argument("--no-subs", action="store_true")
    args = parser.parse_args()
    prod = (args.prod if args.prod.is_absolute() else ROOT / args.prod).resolve()
    ctx = context_for(prod, args.episode)
    folder = prod / (args.dir or f"{ctx.shot_dir()}/draft-480p")
    with using_context(ctx):
        table = read_artifact(prod, episode_artifact_name("shot_list.json", args.episode))
        lines = read_lines(prod, args.episode)
        writer = read_artifact(prod, episode_artifact_name("writer.json", args.episode))
    names = cast_names(writer)
    kinds = {r.get("line_id"): r.get("kind") for r in (lines or {}).get("lines") or []}
    report_path = folder / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")).get("shots", {}) if report_path.is_file() else {}
    label = episode_label(args.episode) or f"ep{int(args.episode):02d}"
    out = Path(args.out) if args.out else folder / f"{label.upper()}-review.mp4"
    shots = [s for s in table.get("shots") or [] if (folder / f"{s['shot_id']}.mp4").is_file()]
    if not shots:
        raise SystemExit(f"no draft clips in {folder}")
    w, h = video_size(folder / f"{shots[0]['shot_id']}.mp4")
    work = Path(tempfile.mkdtemp(prefix="review-cut-"))
    parts, timeline, clock = [], [], 0.0
    pending_fade_in = 0.0
    for index, shot in enumerate(shots):
        sid = shot["shot_id"]
        clip = folder / f"{sid}.mp4"
        clip_sec = probe_seconds(clip)
        segs = (report.get(sid) or {}).get("segments")
        if segs is None and shot.get("dialogue_delivery") == "on_camera" and shot.get("dialogue_ref"):
            heard = transcribe(clip, folder / "qc")
            segs = heard["segments"] if heard else None
        span = speech_span(segs or [])
        a, b = trim_window(shot, clip_sec, span)
        trans = shot.get("transition_out") if isinstance(shot.get("transition_out"), dict) else {}
        kind = trans.get("type") if index + 1 < len(shots) else ""
        sec = float(trans.get("sec") or 0.8)
        fade_out = min(sec, 1.0) if kind == "fade" else 0.0
        seg = work / f"{index:03d}-{sid}.mp4"
        encode(clip, a, b - a, seg, w, h, fade_in=pending_fade_in, fade_out=fade_out)
        pending_fade_in = min(sec, 1.0) if kind == "fade" else 0.0
        real = probe_seconds(seg)
        timeline.append({"shot_id": sid, "in_sec": round(a, 3), "out_sec": round(a + real, 3), "start": round(clock, 3),
                         "paper_sec": shot.get("duration_sec"), "speech": span})
        parts.append(seg)
        clock += real
        if kind == "black":
            gap = work / f"{index:03d}-black.mp4"
            black(sec, gap, w, h)
            parts.append(gap)
            timeline.append({"black": round(sec, 2), "start": round(clock, 3), "sound": trans.get("sound", "")})
            clock += probe_seconds(gap)
    (work / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    base = work / "base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(base)], check=True)

    starts = {row["shot_id"]: row for row in timeline if "shot_id" in row}
    overlays = []  # (png, x, y, t0, t1, fade)
    texts = card_texts(lines)
    places = place_texts(lines)
    coretext = coretext_binary(ROOT / "scripts" / "khmer_coretext.swift")
    placed_scenes = set()
    for shot in shots:
        row = starts[shot["shot_id"]]
        if isinstance(shot.get("name_card"), dict) and shot["name_card"].get("character") in texts:
            card = normalize_card(shot["name_card"], shot)
            text = texts[card["character"]]
            png = render_card(text["name_km"], text["role_km"], h, work / f"card-{card['character']}.png", coretext)
            x, y = card_position(card, w, h)
            overlays.append((png, x, y, row["start"] + card["start_sec"], row["start"] + card["start_sec"] + card["hold_sec"], True))
        if isinstance(shot.get("place_card"), dict):
            card = normalize_place_card(shot["place_card"], shot)
            placed_scenes.add(card["scene_id"])
            text = places.get(card["scene_id"])
            if text:
                png = render_card(text["line1_km"], text["line2_km"], h, work / f"place-{card['scene_id']}.png", coretext)
                x, y = card_position(card, w, h)
                overlays.append((png, x, y, row["start"] + card["start_sec"], row["start"] + card["start_sec"] + card["hold_sec"], True))
    for scene, text in places.items():
        if scene in placed_scenes:
            continue
        first = next((s for s in shots if s.get("scene_id") == scene), None)
        if first is None:
            continue
        print(f"warn place/time card {text['zh']} has no place_card; shown on {first['shot_id']} for review only")
        row = starts[first["shot_id"]]
        png = render_card(text["line1_km"], text["line2_km"], h, work / f"place-{scene}.png", coretext)
        overlays.append((png, int(w * 0.05) - 24, int(h * 0.08) - 24, row["start"] + 0.3, row["start"] + 2.9, True))
    if not args.no_subs:
        n = 0
        for shot in shots:
            row = starts[shot["shot_id"]]
            seg_len = row["out_sec"] - row["in_sec"]
            delivery = shot.get("dialogue_delivery") or "on_camera"
            for ref in shot.get("dialogue_ref") or []:
                how = ref.get("delivery") or delivery
                if how == "post":
                    how = "inner" if kinds.get(ref.get("line_id")) == "inner" else "off_camera"
                who = names.get(ref.get("character"), ref.get("character") or "")
                span = row["speech"]
                if span and how == "on_camera":
                    lo, hi = max(0.0, span[0] - row["in_sec"]), min(seg_len, span[1] - row["in_sec"] + 0.2)
                else:
                    lo, hi = 0.25, seg_len - 0.15
                tag = f"（{who}·{TAG[how]}）" if how in TAG else ""
                chunks = subtitle_chunks(ref.get("line") or "")
                total = sum(len(c) for c in chunks) or 1
                cur = lo
                for i, chunk in enumerate(chunks):
                    span_sec = (hi - lo) * len(chunk) / total
                    path = work / f"sub{n:03d}.png"
                    n += 1
                    sw, sh = sub_png((tag if i == 0 else "") + chunk, path, max(18, int(h * 0.056)))
                    overlays.append((path, (w - sw) // 2, h - sh - int(h * 0.03), row["start"] + cur, row["start"] + cur + span_sec, False))
                    cur += span_sec
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(base)]
    chains, last = [], "[0:v]"
    for i, (png, x, y, t0, t1, fade) in enumerate(overlays, start=1):
        hold = t1 - t0
        cmd += ["-loop", "1", "-t", f"{hold:.3f}", "-i", str(png)]
        f = f",fade=t=in:st=0:d=0.3:alpha=1,fade=t=out:st={max(0, hold - 0.3):.3f}:d=0.3:alpha=1" if fade else ""
        chains.append(f"[{i}:v]format=rgba{f},setpts=PTS-STARTPTS+{t0:.3f}/TB[o{i}]")
        chains.append(f"{last}[o{i}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{t0:.3f},{t1:.3f})'[v{i}]")
        last = f"[v{i}]"
    if chains:
        cmd += ["-filter_complex", ";".join(chains), "-map", last, "-map", "0:a"]
    cmd += ["-c:a", "copy", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    out.with_suffix(".cut.json").write_text(json.dumps({"note": "review-only draft cut; not an EDL", "timeline": timeline},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out.relative_to(prod) if out.is_relative_to(prod) else out} {probe_seconds(out):.1f}s, {len(overlays)} overlays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
