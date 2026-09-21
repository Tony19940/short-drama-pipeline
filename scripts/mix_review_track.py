#!/usr/bin/env python3
"""Burn a Chinese review track (scratch VO + captions) onto shot videos.

Urban short-drama plot lives in lines, not in silent H3. Watch this cut,
not the mute concat, when checking story.

  python3 scripts/mix_review_track.py --prod productions/002-sophea-tent \\
      --only SH001 SH002 SH003 SH004 SH005 \\
      --out productions/002-sophea-tent/06-export/preview-30s-vo.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
DEFAULT_VOICE = {
    "narration": "Tingting",
    "intro": "Tingting",
    "inner": "Tingting",
    "sms": "Shelley (中文（中国大陆）)",
    "dialogue": "Grandma (中文（中国大陆）)",
    "reaction": "Tingting",
}


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def ass_stamp(t: float) -> str:
    if t < 0:
        t = 0
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def caption_png(text: str, dest: Path, size: tuple[int, int] = (768, 1344)) -> None:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 36)
    w, h = size
    lines = textwrap.wrap(text, width=16) or [text]
    line_h = 48
    pad_x, pad_y = 28, 18
    block_h = pad_y * 2 + line_h * len(lines)
    block_w = w - 72
    x0 = 36
    y0 = h - 80 - block_h
    draw.rounded_rectangle((x0, y0, x0 + block_w, y0 + block_h), radius=16, fill=(0, 0, 0, 150))
    y = y0 + pad_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    img.save(dest)


def say_to_wav(text: str, voice: str, dest: Path) -> None:
    aiff = dest.with_suffix(".aiff")
    subprocess.check_call(
        ["say", "-v", voice, "-r", "185", "-o", str(aiff), text],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ["ffmpeg", "-y", "-i", str(aiff), "-ac", "1", "-ar", "32000", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    aiff.unlink(missing_ok=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    p.add_argument("--only", nargs="*")
    p.add_argument("--out", required=True)
    p.add_argument("--episode", default="1")
    args = p.parse_args()

    prod = Path(args.prod).resolve()
    want = args.only or []
    selected = []
    shot_dir = "05-shots"
    try:
        import sys

        scripts = Path(__file__).resolve().parent
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from director.pipeline import episode_shot_dir
        from director.shot_repo import select_shots

        shot_dir = episode_shot_dir(args.episode)
        rows = select_shots(prod, want or None, args.episode)
        selected = [{"id": row.get("id") or row.get("shot_id")} for row in rows]
    except Exception:
        selected = []
    if not selected:
        shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
        selected = [s for s in shots if not want or s["id"] in want]
    if not selected:
        raise SystemExit("no shots")

    clips = []
    for s in selected:
        sid = s.get("id") or s.get("shot_id")
        mp4 = prod / shot_dir / f"{sid}.mp4"
        if not mp4.exists() and shot_dir != "05-shots":
            mp4 = prod / "05-shots" / f"{sid}.mp4"
        if not mp4.exists():
            raise SystemExit(f"missing {mp4}")
        clips.append((s, mp4, probe_duration(mp4)))

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="review-track-"))

    concat_list = work / "concat.txt"
    with concat_list.open("w") as f:
        for _, mp4, _ in clips:
            f.write(f"file '{mp4}'\n")
    picture = work / "picture.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(picture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    t = 0.0
    captions: list[tuple[Path, float, float]] = []
    wavs: list[tuple[Path, int]] = []
    for s, mp4, dur in clips:
        line = str(s.get("line") or "").strip()
        caption = str(s.get("caption") or line).strip()
        kind = str(s.get("line_kind") or "narration")
        kind = {"inner_voice": "inner", "character_intro": "intro"}.get(kind, kind)
        if kind == "reaction":
            caption = caption or ""
        if kind == "intro" and caption and "简介" not in caption:
            caption = "简介 · " + caption
        if kind == "inner" and caption and not caption.startswith("（"):
            caption = "（" + caption.rstrip("）") + "）"
        if caption:
            start = t + 0.15
            end = min(t + dur - 0.12, t + max(2.2, min(dur - 0.2, 5.5)))
            png = work / f"{s['id']}.png"
            caption_png(caption, png)
            captions.append((png, start, end))
        if line:
            voice = s.get("voice") or DEFAULT_VOICE.get(kind, "Tingting")
            wav = work / f"{s['id']}.wav"
            say_to_wav(line, voice, wav)
            wavs.append((wav, int(t * 1000) + 180))
        t += dur

    if not wavs:
        raise SystemExit("shots have no line fields; write line/caption in shots.json")

    vo = work / "vo.wav"
    inputs = ["-i", str(picture)]
    filters = []
    mix_labels = []
    for i, (wav, delay) in enumerate(wavs, start=1):
        inputs += ["-i", str(wav)]
        lab = f"v{i}"
        filters.append(f"[{i}:a]adelay={delay}|{delay},volume=1.15[{lab}]")
        mix_labels.append(f"[{lab}]")
    filters.append("[0:a]volume=0.18[bg]")
    n_mix = 1 + len(wavs)
    filters.append(f"[bg]{''.join(mix_labels)}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0[a]")
    mixed = work / "mixed.m4a"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[a]",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(mixed),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    cmd = ["ffmpeg", "-y", "-i", "picture.mp4", "-i", "mixed.m4a"]
    for png, _, _ in captions:
        cmd += ["-i", png.name]
    parts = []
    last = "[0:v]"
    for i, (_, start, end) in enumerate(captions):
        src = f"[{i + 2}:v]"
        nxt = f"[s{i}]"
        parts.append(
            f"{last}{src}overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'{nxt}"
        )
        last = nxt
    fc = ";".join(parts) if parts else None
    cmd += [
        "-filter_complex",
        fc,
        "-map",
        last,
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    subprocess.check_call(cmd, cwd=str(work))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
