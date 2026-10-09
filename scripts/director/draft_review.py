"""Reviewing a draft pass (e.g. Seedance 2.0 mini 480p) before the paid render.

Two jobs, both review-only (never a take, never an EDL):

- QC evidence per clip: a dense frame strip (every 0.25s by default), the last frame at full size, and a local
  speech-to-text transcript compared with the line the shot should speak. 012 EP01 showed why: four evenly
  spaced frames missed SH001's mud landing between 2.0s and 2.5s, and the reviewer called a working shot broken.
  A claim that an action did not happen needs the strip, not four thumbnails.
- A review cut of the whole episode: each clip trimmed to its paper length, joined, with the Khmer name and
  place/time cards and Chinese review subtitles, so the human judges the story in sequence.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

WHISPER_CANDIDATES = (
    "~/models/ggml-large-v3-turbo.bin",
    "~/models/ggml-large-v3-turbo-q5_0.bin",
    "~/Library/Application Support/PhoneRecordingBridge/models/ggml-large-v3-turbo-q5_0.bin",
    "~/Library/Application Support/PhoneRecordingBridge/models/ggml-large-v3.bin",
    "~/models/ggml-small.bin",
    "~/models/ggml-base.bin",
)
PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’「」…—\-（）()]+")
TIME_RE = re.compile(r"\[(\d+):(\d+):([\d.]+) --> (\d+):(\d+):([\d.]+)\]\s*(.*)")
SPEECH_PAD_BEFORE = 0.15
SPEECH_PAD_AFTER = 0.35
SUB_MAX_CHARS = 18


def _t(value: Any) -> str:
    return str(value or "").strip()


def probe_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip() or 0)


# --- speech -----------------------------------------------------------------------------------


def find_whisper() -> Optional[tuple[str, str]]:
    """(whisper-cli binary, ggml model) or None. WHISPER_MODEL overrides the search."""
    binary = shutil.which("whisper-cli")
    if not binary:
        return None
    env = os.environ.get("WHISPER_MODEL", "").strip()
    for raw in ([env] if env else []) + list(WHISPER_CANDIDATES):
        path = Path(raw).expanduser()
        if path.is_file():
            return binary, str(path)
    return None


def parse_segments(stdout: str) -> list[dict]:
    segs = []
    for line in stdout.splitlines():
        match = TIME_RE.match(line.strip())
        if not match:
            continue
        a = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        b = int(match[4]) * 3600 + int(match[5]) * 60 + float(match[6])
        segs.append({"start": round(a, 3), "end": round(b, 3), "text": match[7].strip()})
    return segs


def transcribe(clip: Path, workdir: Path, *, language: str = "zh") -> Optional[dict]:
    """{text, segments} for the clip's audio, cached next to the QC files; None without whisper."""
    found = find_whisper()
    if not found:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    stat = clip.stat()
    cache = workdir / f"{clip.stem}.asr.json"
    key = f"{stat.st_size}:{int(stat.st_mtime)}:{language}:{Path(found[1]).name}"
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data
    wav = workdir / f"{clip.stem}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-ar", "16000", "-ac", "1", str(wav)], check=True)
    out = subprocess.run([found[0], "-m", found[1], "-l", language, "-np", "-f", str(wav)], capture_output=True, text=True).stdout
    segments = parse_segments(out)
    data = {"key": key, "text": "".join(s["text"] for s in segments), "segments": segments}
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    wav.unlink(missing_ok=True)
    return data


def similarity(expected: str, heard: str) -> float:
    """Character overlap of two Chinese strings, punctuation ignored (homophone slips still score high)."""
    a = PUNCT_RE.sub("", _t(expected))
    b = PUNCT_RE.sub("", _t(heard))
    if not a:
        return 1.0 if not b else 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 2)


def speech_span(segments: list[dict]) -> Optional[tuple[float, float]]:
    if not segments:
        return None
    return float(segments[0]["start"]), float(segments[-1]["end"])


# --- trimming -----------------------------------------------------------------------------------


def trim_window(shot: dict, clip_sec: float, span: Optional[tuple[float, float]] = None) -> tuple[float, float]:
    """In/out seconds of a draft clip for the review cut.

    Paper length wins. A shot that speaks on camera keeps its whole line (paper is stretched if the line
    needs it). A silent shot keeps the tail: drafts tend to land the action late (012 SH001's mud at 2.2s
    of a 3s beat), and the tail is where the landing is.
    """
    try:
        paper = float(shot.get("duration_sec") or clip_sec)
    except (TypeError, ValueError):
        paper = clip_sec
    if paper >= clip_sec - 0.05:
        return 0.0, round(clip_sec, 3)
    speaks = _t(shot.get("dialogue_delivery")) == "on_camera" and bool(shot.get("dialogue_ref"))
    if speaks and span:
        start = max(0.0, span[0] - SPEECH_PAD_BEFORE) if span[0] > 0.2 else 0.0
        end = min(clip_sec, max(span[1] + SPEECH_PAD_AFTER, start + paper))
        if end - start < paper:
            start = max(0.0, end - paper)
        return round(start, 3), round(end, 3)
    if speaks:
        return 0.0, round(paper, 3)
    return round(clip_sec - paper, 3), round(clip_sec, 3)


# --- subtitles --------------------------------------------------------------------------------


def subtitle_chunks(text: str, max_chars: int = SUB_MAX_CHARS) -> list[str]:
    """Split a line at clause marks into on-screen chunks; commas and full stops become wide spaces."""
    parts = [p for p in re.split(r"(?<=[，。？！])", _t(text)) if p.strip()]
    merged: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) > max_chars:
            merged.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        merged.append(buf)
    return [re.sub(r"[，。]+", "  ", m).strip() for m in merged]


def review_tag(ref: dict, shot: dict, kind: str, who: str) -> str:
    """Prefix for lines that have no sound in the draft: post dubs, phone voices, inner monologue."""
    if _t(shot.get("dialogue_delivery")) != "post":
        return ""
    if kind == "inner":
        return f"（{who}·内心）"
    if kind == "narration":
        return f"（{who}·旁白）"
    return f"（{who}·画外）"


# --- frames -----------------------------------------------------------------------------------


def dense_strip(clip: Path, out: Path, *, step: float = 0.25, width: int = 320, columns: int = 8) -> Path:
    """Contact sheet of frames every `step` seconds, time-stamped, so a fast action cannot hide between samples."""
    from PIL import Image, ImageDraw, ImageFont

    total = probe_seconds(clip)
    times = []
    t = 0.0
    while t < total - 0.05:
        times.append(round(t, 2))
        t += step
    times.append(round(max(0.0, total - 0.15), 2))  # the very last timestamp can sit past the final frame
    tmp = out.parent / f".{clip.stem}-strip"
    tmp.mkdir(parents=True, exist_ok=True)
    tiles = []
    for index, at in enumerate(times):
        frame = tmp / f"{index:03d}.jpg"
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{at:.2f}", "-i", str(clip), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", "-q:v", "4", str(frame)])
        if frame.exists():
            tiles.append((at, Image.open(frame).convert("RGB")))
    if not tiles:
        raise RuntimeError(f"no frames from {clip}")
    tile_h = tiles[0][1].height
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (width * columns, tile_h * rows), "black")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except OSError:
        font = ImageFont.load_default()
    for index, (at, image) in enumerate(tiles):
        x, y = (index % columns) * width, (index // columns) * tile_h
        sheet.paste(image, (x, y))
        draw.rectangle((x, y, x + 58, y + 20), fill="black")
        draw.text((x + 4, y + 2), f"{at:.2f}s", fill="yellow", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def last_frame(clip: Path, out: Path) -> Path:
    total = probe_seconds(clip)
    for back in (0.1, 0.25, 0.5):
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{max(0.0, total - back):.2f}", "-i", str(clip),
                        "-frames:v", "1", "-q:v", "2", str(out)])
        if out.exists():
            return out
    raise RuntimeError(f"no last frame from {clip}")


def subtitle_font() -> Optional[tuple[str, int]]:
    for path, index in (("/System/Library/Fonts/Hiragino Sans GB.ttc", 1), ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
                        ("/System/Library/Fonts/PingFang.ttc", 0)):
        if Path(path).is_file():
            return path, index
    return None
