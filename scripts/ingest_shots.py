#!/usr/bin/env python3
"""Gate E return path for the manual Grok Imagine canvas route.

scan_inbox() only accepts stills, so canvas-generated clips had no door back
into the pipeline. This is that door: it takes SH*.mp4 out of .director/inbox/,
concatenates same-shot segments (SH003a + SH003b -> SH003.mp4), writes
05-shots/, and extracts 04-frames/{id}-last.jpg with the same ffmpeg call
render_shots.py uses, so R10 continuation keeps working.

  python3 scripts/ingest_shots.py --prod productions/004-yuye-jinlian
  python3 scripts/ingest_shots.py --prod productions/004-yuye-jinlian --only SH003
  python3 scripts/ingest_shots.py --prod productions/004-yuye-jinlian --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEGMENT_RE = re.compile(r"^(SH\d{3})([a-j])?$")
BANNED = ("kenburns", "still-pass")


def load_shots(prod: Path) -> list[dict]:
    path = prod / "03-storyboard" / "shots.json"
    if not path.exists():
        raise SystemExit(f"没有 {path}；Gate C2 未完成。")
    return json.loads(path.read_text(encoding="utf-8"))["shots"]


def probe_seconds(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def concat(parts: list[Path], dest: Path) -> None:
    """Stream-copy concat. No transition, no re-encode: segments of one long
    take must stay frame-continuous."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        shutil.copy2(parts[0], dest)
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for part in parts:
            fh.write(f"file '{part.resolve()}'\n")
        listing = Path(fh.name)
    try:
        subprocess.check_call(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        listing.unlink(missing_ok=True)


def mute(src: Path, dest: Path) -> None:
    """Swap the model's audio for a silent track of the same length.

    R12: AI-generated audio is never a sound track; room tone, foley and BGM go
    on in post. Canvas clips always ship with audio (unlike the silent Hailuo
    Fast default), so without this the AI bed rides through assemble.sh's
    -c copy straight into the export. A silent track is kept rather than no
    track at all, because mix_review_track.py ducks [0:a] as its bed and a
    uniform stream layout keeps concat -c copy safe.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["ffmpeg", "-y", "-i", str(src),
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-shortest", "-movflags", "+faststart", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def extract_last(prod: Path, shot_id: str, video: Path) -> Path:
    last = prod / "04-frames" / f"{shot_id}-last.jpg"
    last.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["ffmpeg", "-y", "-sseof", "-0.05", "-i", str(video),
         "-frames:v", "1", str(last)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return last


def main() -> None:
    p = argparse.ArgumentParser(description="把画布出的 mp4 收回 05-shots/ 并提末帧")
    p.add_argument("--prod", required=True, help="productions/<slug>")
    p.add_argument("--only", nargs="*", help="镜号，如 SH003")
    p.add_argument("--inbox", help="默认 <prod>/.director/inbox")
    p.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    p.add_argument(
        "--keep-audio",
        action="store_true",
        help="保留模型生成的音频（默认换成静音轨；R12 环境声/BGM 后期叠）",
    )
    args = p.parse_args()

    prod = Path(args.prod).resolve()
    inbox = Path(args.inbox).resolve() if args.inbox else prod / ".director" / "inbox"
    if not inbox.exists():
        raise SystemExit(f"inbox 不存在：{inbox}")

    shots = load_shots(prod)
    by_id = {s["id"]: s for s in shots}
    want = set(args.only or [])

    # group inbox mp4s by shot id, segments in suffix order
    groups: dict[str, list[tuple[str, Path]]] = {}
    unmatched: list[str] = []
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".mp4":
            continue
        if any(bad in path.name.lower() for bad in BANNED):
            raise SystemExit(f"Ken Burns / still-pass 不是成片路径：{path.name}")
        m = SEGMENT_RE.match(path.stem)
        if not m or m.group(1) not in by_id:
            unmatched.append(path.name)
            continue
        groups.setdefault(m.group(1), []).append((m.group(2) or "", path))

    if want:
        groups = {k: v for k, v in groups.items() if k in want}

    if not groups:
        print(f"inbox 里没有可识别的镜头 mp4：{inbox}")
        if unmatched:
            print("对不上 shots.json 的文件：" + "、".join(unmatched))
        return

    processed_dir = inbox / "processed"
    done: list[str] = []

    for shot_id in sorted(groups):
        parts = [path for _, path in sorted(groups[shot_id], key=lambda x: x[0])]
        shot = by_id[shot_id]
        target = int(shot.get("seconds") or 0)
        actual = round(sum(probe_seconds(x) for x in parts), 1)
        seg_note = f"{len(parts)} 段合并" if len(parts) > 1 else "单段"
        drift = "" if abs(actual - target) <= 1.0 else f"  ⚠ 与 shots.json 的 {target}s 差 {round(actual - target, 1)}s"
        print(f"{shot_id}  {seg_note}  {actual}s / 目标 {target}s{drift}")
        for _, path in sorted(groups[shot_id], key=lambda x: x[0]):
            print(f"    ← {path.name}")

        if args.dry_run:
            continue

        dest = prod / "05-shots" / f"{shot_id}.mp4"
        if args.keep_audio:
            concat(parts, dest)
            print(f"    → {dest.relative_to(prod)}  （保留模型音频，违反 R12，只用于排查）")
        else:
            staged = Path(tempfile.mkdtemp(prefix="ingest-")) / f"{shot_id}.mp4"
            concat(parts, staged)
            mute(staged, dest)
            shutil.rmtree(staged.parent, ignore_errors=True)
            print(f"    → {dest.relative_to(prod)}  （模型音频已换成静音轨）")
        last = extract_last(prod, shot_id, dest)
        print(f"    → {last.relative_to(prod)}")

        processed_dir.mkdir(parents=True, exist_ok=True)
        for part in parts:
            shutil.move(str(part), str(processed_dir / part.name))
        done.append(shot_id)

        nxt = next(
            (s for s in shots if s.get("from") == shot_id and s.get("cut") == "continue"),
            None,
        )
        if nxt:
            here = set(shot.get("characters") or [])
            there = set(nxt.get("characters") or [])
            if not here or not there or (here & there):
                print(f"    下一镜 {nxt['id']} 用这张末帧当首帧")
            else:
                print(
                    f"    下一镜 {nxt['id']} 覆盖切到 {'、'.join(sorted(there))}，"
                    "无人物交集 —— 用它自己的设计首帧，不要吃这张末帧"
                )

    if unmatched:
        print()
        print("对不上 shots.json 的文件（没动）：" + "、".join(unmatched))

    missing = [s["id"] for s in shots if not (prod / "05-shots" / f"{s['id']}.mp4").exists()]
    print()
    if args.dry_run:
        print("dry-run，没有写文件。")
    else:
        print(f"收了 {len(done)} 镜。")
    if missing:
        print(f"还缺 {len(missing)} 镜：" + "、".join(missing))
    else:
        print("全集齐了。下一步：")
        print(f"  python3 scripts/mix_review_track.py --prod {args.prod}   # Gate E+ 审剧情")
        print(f"  bash scripts/assemble.sh {args.prod}                     # 成片")


if __name__ == "__main__":
    main()
