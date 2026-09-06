"""Gate 0: reverse a finished short into a reviewable shot draft.

Pixels stay on disk. This never writes official shots.json and never renders video.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .paths import ROOT, media_url
from .production import load_json, save_json, write_text
from .store import load_jobs, save_jobs

REVERSE_DIR = "00-reverse"
MIN_SHOT = 1.2
MAX_SHOT = 15.0
SCENE_THRESHOLD = 8.0
WHISPER_TEST_MODEL = Path(
    "/opt/homebrew/Cellar/whisper-cpp/1.9.1/share/whisper-cpp/for-tests-ggml-tiny.bin"
)

SCALE_CYCLE = ("full", "close", "med", "close", "single")
SETUP_CYCLE = ("master", "close", "ots", "single", "close")
MOVE_WORDS = {
    "static": "locked-off static camera, faint handheld breath only",
    "push": "slow push in, faint handheld, no orbit",
    "pull": "slow pull out, faint handheld, no orbit",
    "pan": "one small pan, faint handheld, no orbit",
    "track": "short lateral track, faint handheld, no orbit",
}


class ReverseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def reverse_dir(prod: Path, create: bool = False) -> Path:
    path = prod / REVERSE_DIR
    if create:
        (path / "source").mkdir(parents=True, exist_ok=True)
        (path / "frames").mkdir(parents=True, exist_ok=True)
        (path / "audio").mkdir(parents=True, exist_ok=True)
    return path


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_video(path: Path) -> dict:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    if proc.returncode != 0:
        raise ReverseError("VIDEO_INVALID", proc.stderr.strip() or "ffprobe 失败")
    data = json.loads(proc.stdout or "{}")
    video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams") or [] if s.get("codec_type") == "audio"), None)
    if not video:
        raise ReverseError("VIDEO_INVALID", "没有视频轨")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    fps_raw = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        fps = 0.0
    aspect = "9:16" if height >= width else "16:9"
    return {
        "path": str(path),
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "aspect": aspect,
        "has_audio": bool(audio),
        "size_bytes": int((data.get("format") or {}).get("size") or path.stat().st_size),
    }


def ingest_video(prod: Path, src: Path, filename: str = "reference.mp4") -> dict:
    if not src.exists():
        raise ReverseError("VIDEO_INVALID", f"找不到视频：{src}")
    dest_dir = reverse_dir(prod, create=True)
    dest = dest_dir / "source" / "reference.mp4"
    suffix = src.suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        raise ReverseError("VIDEO_INVALID", f"不支持的格式：{suffix}")
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    info = probe_video(dest)
    if info["duration"] <= 0.4:
        raise ReverseError("VIDEO_INVALID", "视频太短")
    if info["duration"] > 10 * 60:
        raise ReverseError("VIDEO_TOO_LONG", "超过 10 分钟，先剪成一集再反推")
    info["filename"] = filename
    info["stored"] = "00-reverse/source/reference.mp4"
    save_json(prod, "00-reverse/source.json", info)
    return info


def detect_cuts(video: Path, duration: float, threshold: float = SCENE_THRESHOLD) -> list[dict]:
    times = [0.0]
    probes = [
        ["ffmpeg", "-hide_banner", "-i", str(video), "-vf", f"scdet=threshold={threshold}", "-an", "-f", "null", "-"],
        ["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "select='gt(scene,0.18)',showinfo", "-an", "-f", "null", "-"],
    ]
    blob = ""
    for cmd in probes:
        proc = _run(cmd, timeout=300)
        blob += "\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
    found = []
    for match in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", blob):
        found.append(float(match.group(1)))
    for match in re.finditer(r"pts_time:([0-9.]+)", blob):
        found.append(float(match.group(1)))
    for t in sorted(found):
        if t <= 0.15 or t >= duration - 0.12:
            continue
        if t - times[-1] < 0.8:
            continue
        times.append(t)
    times.append(duration)
    cuts = []
    for index, start in enumerate(times[:-1]):
        end = times[index + 1]
        if end - start < 0.35 and index < len(times) - 2:
            continue
        cuts.append({"start": round(start, 3), "end": round(end, 3)})
    if not cuts:
        cuts = [{"start": 0.0, "end": round(duration, 3)}]
    return cap_cuts(split_long_cuts(cuts), max_shots=12)


def cap_cuts(cuts: list[dict], max_shots: int = 12) -> list[dict]:
    items = [dict(cut) for cut in cuts]
    while len(items) > max_shots:
        best = 1
        best_span = 1e9
        for i in range(1, len(items)):
            span = float(items[i]["end"]) - float(items[i - 1]["start"])
            if span < best_span:
                best_span = span
                best = i
        left = items[best - 1]
        right = items[best]
        items[best - 1] = {"start": left["start"], "end": right["end"]}
        del items[best]
    return [{"start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3)} for c in items]


def split_long_cuts(cuts: list[dict]) -> list[dict]:
    out = []
    for cut in cuts:
        start = float(cut["start"])
        end = float(cut["end"])
        span = end - start
        if span <= MAX_SHOT:
            out.append({"start": round(start, 3), "end": round(end, 3)})
            continue
        pieces = max(2, math.ceil(span / 12.0))
        step = span / pieces
        cursor = start
        for i in range(pieces):
            nxt = end if i == pieces - 1 else cursor + step
            out.append({"start": round(cursor, 3), "end": round(nxt, 3)})
            cursor = nxt
    return out


def extract_frames(video: Path, cuts: list[dict], dest: Path) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, cut in enumerate(cuts, start=1):
        mid = (float(cut["start"]) + float(cut["end"])) / 2.0
        name = f"SH{index:03d}.jpg"
        path = dest / name
        proc = _run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-ss",
                f"{mid:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(path),
            ]
        )
        if proc.returncode != 0 or not path.exists():
            raise ReverseError("FRAME_FAILED", proc.stderr[-400:] or f"抽帧失败 {name}")
        frames.append(
            {
                "id": f"SH{index:03d}",
                "t": round(mid, 3),
                "path": f"00-reverse/frames/{name}",
            }
        )
    return frames


def extract_audio(video: Path, dest: Path) -> Optional[Path]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(dest),
        ]
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 64:
        return None
    return dest


def find_whisper_model() -> Optional[Path]:
    env = os.environ.get("WHISPER_MODEL", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env).expanduser())
    candidates.extend(
        [
            ROOT / "models" / "ggml-small.bin",
            ROOT / "models" / "ggml-base.bin",
            Path.home() / "models" / "ggml-small.bin",
            Path.home() / "models" / "ggml-base.bin",
        ]
    )
    if os.environ.get("WHISPER_ALLOW_TINY", "").strip() in {"1", "true", "yes"}:
        candidates.append(WHISPER_TEST_MODEL)
    min_size = 100_000 if os.environ.get("WHISPER_ALLOW_TINY") else 1_000_000
    for path in candidates:
        if path.exists() and path.stat().st_size > min_size:
            return path
    return None


def transcribe_audio(wav: Path, dest_json: Path, language: str = "auto") -> dict:
    model = find_whisper_model()
    if model is None:
        data = {"ok": False, "reason": "没有可用的 whisper 模型", "segments": []}
        dest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data
    out_base = dest_json.with_suffix("")
    cmd = [
        "whisper-cli",
        "-np",
        "-l",
        language,
        "-m",
        str(model),
        "-f",
        str(wav),
        "-oj",
        "-of",
        str(out_base),
    ]
    proc = _run(cmd, timeout=600)
    produced = Path(str(out_base) + ".json")
    if not produced.exists():
        data = {
            "ok": False,
            "reason": (proc.stderr or proc.stdout or "whisper 没有写出 json")[-400:],
            "segments": [],
        }
        dest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data
    raw = json.loads(produced.read_text(encoding="utf-8"))
    segments = []
    for item in raw.get("transcription") or raw.get("segments") or []:
        offsets = item.get("offsets") or {}
        start_ms = offsets.get("from", item.get("start", 0))
        end_ms = offsets.get("to", item.get("end", 0))
        if isinstance(start_ms, (int, float)) and start_ms > 1000:
            start = float(start_ms) / 1000.0
            end = float(end_ms) / 1000.0
        else:
            start = float(start_ms or 0)
            end = float(end_ms or 0)
        text = str(item.get("text") or item.get("word") or "").strip()
        if text:
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    data = {
        "ok": True,
        "model": str(model),
        "language": language,
        "segments": segments,
        "text": " ".join(seg["text"] for seg in segments).strip(),
    }
    dest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def lines_for_window(transcript: dict, start: float, end: float) -> str:
    bits = []
    for seg in transcript.get("segments") or []:
        if seg["end"] < start - 0.15 or seg["start"] > end + 0.15:
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            bits.append(text)
    return " ".join(bits).strip()


def guess_move(index: int, seconds: float) -> str:
    if seconds <= 5:
        return "static"
    if index % 5 == 1:
        return "push"
    return "static"


def guess_axis(index: int, setup: str) -> str:
    if setup == "master":
        return "center"
    return "left"


def seconds_of(cut: dict) -> int:
    span = max(MIN_SHOT, float(cut["end"]) - float(cut["start"]))
    value = int(round(span))
    return max(4, min(15, value))


def heuristic_shot(index: int, cut: dict, transcript: dict, frame: dict, aspect: str) -> dict:
    sid = f"SH{index:03d}"
    setup = SETUP_CYCLE[(index - 1) % len(SETUP_CYCLE)]
    scale = SCALE_CYCLE[(index - 1) % len(SCALE_CYCLE)]
    move = guess_move(index, float(cut["end"]) - float(cut["start"]))
    axis = guess_axis(index, setup)
    line = lines_for_window(transcript, cut["start"], cut["end"]) or "（无对白，只推进一件画面信息。）"
    caption = line[:24] + ("…" if len(line) > 24 else "")
    camera = MOVE_WORDS[move]
    action = f"one body beat between {cut['start']:.1f}s and {cut['end']:.1f}s"
    look = f"{aspect} photoreal frame, keep this shot's geography and wardrobe, match reverse still {frame['path']}"
    video_prompt = (
        f"Vertical {aspect} photoreal {setup} {scale} shot. {camera}. "
        f"Hold the same people, clothes and room as reverse still {frame['path']}. "
        "One motion only. No subtitle, no watermark, no lip-sync speech."
    )
    scene = "scene-01" if setup != "master" or index == 1 else f"scene-{(index // 4) + 1:02d}"
    if index == 1:
        scene = "scene-01"
        derived = "scene-01.blocking"
        cut_kind = "hard"
        prev = None
    else:
        derived = f"SH{index - 1:03d}"
        cut_kind = "continue"
        prev = f"SH{index - 1:03d}"
        scene = "scene-01"
    return {
        "id": sid,
        "seconds": seconds_of(cut),
        "tier": "fast",
        "scale": scale,
        "setup": setup,
        "move": move,
        "cut": cut_kind,
        "from": prev,
        "derived_from": derived,
        "facing": "scene" if setup == "master" else "camera" if setup == "close" else "scene",
        "expression": "held",
        "blocking": f"keep marks from reverse still {sid}",
        "start": f"Hold the reverse still {sid} geography at second 0; people already in their marks, no motion finished",
        "scene": scene,
        "characters": ["lead"],
        "new_info": f"beat {index}: {line[:48] or action}",
        "line_kind": "dialogue" if line and "无对白" not in line else "narration",
        "line": line,
        "caption": caption,
        "on_screen": "",
        "frame": f"04-frames/{sid}.jpg",
        "last_frame": f"04-frames/{sid}-last.jpg",
        "prompt": f"{setup} {scale}. One motion only. [{move}]",
        "lens": "35mm" if setup == "master" else "85mm" if setup == "close" else "50mm",
        "axis": axis,
        "camera": camera,
        "action": action,
        "look": look,
        "video_prompt": video_prompt,
        "negatives": (
            "no subtitles, no captions, no watermark, no logo, no extra person, "
            "no clothing change, no face drift, no orbit, no crash zoom, no beauty filter, no lip-sync speech"
        ),
        "source_start": cut["start"],
        "source_end": cut["end"],
        "source_frame": frame["path"],
    }


def heuristic_draft(info: dict, cuts: list[dict], frames: list[dict], transcript: dict) -> dict:
    shots = []
    for index, cut in enumerate(cuts, start=1):
        frame = frames[index - 1] if index - 1 < len(frames) else {"path": ""}
        shots.append(heuristic_shot(index, cut, transcript, frame, info.get("aspect") or "9:16"))
    return {
        "episode": "ep01",
        "kind": "shortdrama",
        "aspect": info.get("aspect") or "9:16",
        "origin": "reverse-heuristic",
        "shots": shots,
    }


def grok_refine_shots(draft: dict, transcript: dict, brief: str = "") -> dict:
    from .grok_text import chat_json

    system = (
        "You reverse-engineer a finished short into a director shot list. "
        "Return JSON only: {episode, kind, aspect, shots:[...]}. "
        "Each shot must include id, seconds, tier, scale, setup, move, cut, from, derived_from, "
        "facing, expression, blocking, start, scene, characters, new_info, line_kind, line, caption, "
        "on_screen, frame, last_frame, prompt, lens, axis, camera, action, look, video_prompt, negatives. "
        "start is the second-0 stance only and must not copy action. Continue shots must change start. "
        "Keep 6-12 shots, 50-75s total if possible. First shot of a scene derived_from is <scene>.blocking. "
        "continue shots keep the same scene. hard cut only when scene changes. "
        "video_prompt is English, cinematic, one move, no dialogue text, no subtitles. "
        "Dialogue stays in line/caption. No orbit/crash zoom. No lip-sync instruction."
    )
    user = json.dumps(
        {
            "brief": brief,
            "draft": draft,
            "transcript": transcript.get("text") or "",
            "segments": (transcript.get("segments") or [])[:80],
        },
        ensure_ascii=False,
    )
    data = chat_json(system, user)
    if not isinstance(data, dict) or not data.get("shots"):
        raise ReverseError("GROK_JSON", "Grok 没有返回 shots")
    data.setdefault("episode", "ep01")
    data.setdefault("kind", "shortdrama")
    data.setdefault("aspect", draft.get("aspect") or "9:16")
    data["origin"] = "reverse-grok"
    for src, dest in zip(draft.get("shots") or [], data.get("shots") or []):
        for key in ("source_start", "source_end", "source_frame"):
            if key in src and key not in dest:
                dest[key] = src[key]
    return data


def _is_placeholder(text: str, markers: tuple[str, ...]) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True
    return all(marker in raw for marker in markers)


def reverse_docs(draft: dict, transcript: dict, info: dict, title: str) -> dict[str, str]:
    lines = [
        f"# {title}",
        "",
        f"- 片源：`{info.get('stored')}`",
        f"- 时长：{info.get('duration')}s · {info.get('width')}x{info.get('height')} · {info.get('aspect')}",
        f"- 镜头：{len(draft.get('shots') or [])}",
        f"- origin：{draft.get('origin')}",
        "",
        "## 事件线",
        "",
    ]
    for shot in draft.get("shots") or []:
        lines.append(
            f"- {shot['id']} [{shot.get('source_start', '?')}–{shot.get('source_end', '?')}] "
            f"{shot.get('setup')}/{shot.get('move')} {shot.get('new_info')}"
        )
    lines += ["", "## 转写", "", transcript.get("text") or "（无对白）", ""]
    beats = ["# 节拍 · 反推草稿", "", "| 起 | 止 | 节拍 | 新信息 | 地点 | 人 |", "|---|---|---|---|---|---|"]
    coverage = ["# 覆盖 · 反推草稿", ""]
    scenes: dict[str, list] = {}
    t = 0
    for shot in draft.get("shots") or []:
        start = t
        t += int(shot.get("seconds") or 4)
        beats.append(
            f"| {start} | {t} | {shot['id']} | {shot.get('new_info')} | {shot.get('scene')} | {','.join(shot.get('characters') or [])} |"
        )
        scenes.setdefault(shot.get("scene") or "scene-01", []).append(shot)
    for scene, items in scenes.items():
        coverage.append(f"## {scene}")
        coverage.append("")
        coverage.append("| setup | 镜 | 秒 | 机位 | 新信息 |")
        coverage.append("|---|---|---|---|---|")
        for shot in items:
            coverage.append(
                f"| {shot.get('setup')} | {shot['id']} | {shot.get('seconds')} | {shot.get('camera')} | {shot.get('new_info')} |"
            )
        coverage.append("")
    return {
        "summary": "\n".join(lines) + "\n",
        "beats": "\n".join(beats) + "\n",
        "coverage": "\n".join(coverage) + "\n",
    }


def write_original_docs(prod: Path, draft: dict, transcript: dict, info: dict) -> None:
    docs = reverse_docs(draft, transcript, info, f"反推原稿 · {prod.name}")
    write_text(prod, "00-reverse/original.md", docs["summary"])
    write_text(prod, "00-reverse/beats.md", docs["beats"])
    write_text(prod, "00-reverse/coverage.md", docs["coverage"])


def maybe_seed_storyboard_docs(prod: Path, beats: str, coverage: str) -> dict:
    seeded = []
    beats_path = prod / "03-storyboard" / "beats.md"
    coverage_path = prod / "03-storyboard" / "coverage.md"
    if _is_placeholder(beats_path.read_text(encoding="utf-8") if beats_path.exists() else "", ("必须发生在第几秒",)):
        write_text(prod, "03-storyboard/beats.md", beats)
        seeded.append("03-storyboard/beats.md")
    if _is_placeholder(coverage_path.read_text(encoding="utf-8") if coverage_path.exists() else "", ("<scene-slug>",)):
        write_text(prod, "03-storyboard/coverage.md", coverage)
        seeded.append("03-storyboard/coverage.md")
    return {"seeded": seeded}


def analyze_production(prod: Path, *, use_grok: bool = True, brief: str = "") -> dict:
    info_path = prod / "00-reverse" / "source.json"
    video = prod / "00-reverse" / "source" / "reference.mp4"
    if not video.exists():
        raise ReverseError("VIDEO_INVALID", "还没有参考视频，先上传")
    info = load_json(prod, "00-reverse/source.json", {}) if info_path.exists() else probe_video(video)
    if not info:
        info = probe_video(video)
    cuts = detect_cuts(video, float(info["duration"]))
    frames = extract_frames(video, cuts, prod / "00-reverse" / "frames")
    wav = extract_audio(video, prod / "00-reverse" / "audio" / "reference.wav")
    transcript = {"ok": False, "segments": [], "text": "", "reason": "无音轨"}
    if wav:
        transcript = transcribe_audio(wav, prod / "00-reverse" / "audio" / "transcript.json")
    save_json(prod, "00-reverse/cuts.json", {"cuts": cuts, "frames": frames})
    draft = heuristic_draft(info, cuts, frames, transcript)
    grok_error = None
    if use_grok:
        try:
            draft = grok_refine_shots(draft, transcript, brief)
        except Exception as exc:
            grok_error = str(exc)
            draft["origin"] = "reverse-heuristic"
            draft["grok_error"] = grok_error
    save_json(prod, "00-reverse/original.shots.json", draft)
    save_json(prod, "03-storyboard/shots.draft.json", draft)
    write_original_docs(prod, draft, transcript, info)
    docs = reverse_docs(draft, transcript, info, f"反推原稿 · {prod.name}")
    maybe_seed_storyboard_docs(prod, docs["beats"], docs["coverage"])
    analysis = {
        "ok": True,
        "source": info,
        "cut_count": len(cuts),
        "shot_count": len(draft.get("shots") or []),
        "transcript_ok": bool(transcript.get("ok")),
        "origin": draft.get("origin"),
        "grok_error": grok_error,
        "updated_at": int(time.time()),
    }
    save_json(prod, "00-reverse/analysis.json", analysis)
    return {
        "analysis": analysis,
        "draft": draft,
        "cuts": cuts,
        "frames": frames,
        "transcript": transcript,
    }


KHMER_DEFAULT_BRIEF = (
    "把故事改成金边都市短剧。人名用高棉名，地点用制衣厂、出租房、borey、钻石岛或路边婚礼棚。"
    "服装用厂服、sampot、sbai、krama。钱是美元和瑞尔，社交是 Facebook/Telegram。"
    "禁止旗袍、秀禾、故宫、微信、支付宝、人民币机关。工作轨中文，本地轨保留高棉名。"
)

NAME_MAP = [
    (re.compile(r"女主|女孩|她|lead|heroine|lin|诗音", re.I), "sophea"),
    (re.compile(r"反派|女配|姐姐|嫂子|总裁女|rival", re.I), "chenda"),
    (re.compile(r"男主|总裁|少爷|hero|boyfriend", re.I), "vireak"),
    (re.compile(r"母亲|老太太|yeay|婆婆|罗丝", re.I), "ros"),
]

PLACE_MAP = [
    (re.compile(r"工厂|车间|制衣", re.I), "factory-floor"),
    (re.compile(r"走廊|办公室|玻璃", re.I), "factory-office"),
    (re.compile(r"别墅|豪宅|庄园", re.I), "borey-gate"),
    (re.compile(r"餐厅|包间|订婚", re.I), "restaurant-private"),
    (re.compile(r"出租|宿舍|家", re.I), "rental-room"),
]


def slugify_name(text: str, fallback: str) -> str:
    for pat, slug in NAME_MAP:
        if pat.search(text or ""):
            return slug
    return fallback


def slugify_place(text: str, fallback: str) -> str:
    for pat, slug in PLACE_MAP:
        if pat.search(text or ""):
            return slug
    return fallback


def heuristic_localize(draft: dict, brief: str = "") -> dict:
    brief = brief or KHMER_DEFAULT_BRIEF
    out = json.loads(json.dumps(draft))
    out["origin"] = "reverse-localized-heuristic"
    scene_map: dict[str, str] = {}
    char_map: dict[str, str] = {"lead": "sophea"}
    prev_id = None
    prev_scene = None
    for index, shot in enumerate(out.get("shots") or [], start=1):
        old_scene = str(shot.get("scene") or "scene-01")
        if old_scene not in scene_map:
            guessed = slugify_place(
                " ".join([shot.get("look") or "", shot.get("new_info") or "", brief, old_scene]),
                "factory-floor" if index == 1 else "factory-office" if index > 3 else "factory-floor",
            )
            scene_map[old_scene] = guessed
        scene = scene_map[old_scene]
        people = []
        for name in shot.get("characters") or ["lead"]:
            if name not in char_map:
                char_map[name] = slugify_name(str(name), f"cast-{len(char_map)+1:02d}")
            people.append(char_map[name])
        shot["scene"] = scene
        shot["characters"] = people or ["sophea"]
        shot["look"] = (
            "Photoreal Khmer faces, olive-to-bronze skin, Phnom Penh. "
            + str(shot.get("look") or "")
            + ". Factory blouse or sampot, no qipao, no palace roof."
        )
        prompt = str(shot.get("video_prompt") or "")
        if "Khmer" not in prompt:
            prompt = "Photoreal Khmer adult faces, olive skin. " + prompt
        shot["video_prompt"] = prompt.replace("16:9", "9:16")
        shot["negatives"] = (
            str(shot.get("negatives") or "")
            + ", no qipao, no tangzhuang, no Forbidden City, no WeChat wallet, no RMB bills as plot device"
        )
        line = str(shot.get("line") or "")
        line = (
            line.replace("总裁", "集团负责人")
            .replace("顾家", "金莲家")
            .replace("林诗音", "Sophea")
            .replace("女主", "Sophea")
        )
        shot["line"] = line or "（画面推进，对白待填。）"
        shot["new_info"] = str(shot.get("new_info") or "").replace("女主", "Sophea")
        if index == 1 or scene != prev_scene:
            shot["cut"] = "hard"
            shot["from"] = None
            shot["derived_from"] = f"{scene}.blocking"
        else:
            shot["cut"] = "continue"
            shot["from"] = prev_id
            shot["derived_from"] = prev_id
        prev_id = shot["id"]
        prev_scene = scene
    out["aspect"] = "9:16"
    out["character_map"] = char_map
    out["scene_map"] = scene_map
    out["brief"] = brief
    return out


def grok_localize(draft: dict, brief: str, culture: str) -> dict:
    from .grok_text import chat_json

    system = (
        "Rewrite this reversed shot list into a Cambodian urban short-drama episode. "
        "Keep shot count, camera grammar, setup/move/axis, and cut logic. "
        "Change names, places, clothes, money, humiliation to Khmer culture. "
        "Working-track dialogue in Chinese, character names remain Khmer romanization. "
        "video_prompt stays English and must not contain dialogue. Return JSON shot list only."
    )
    user = json.dumps({"brief": brief, "culture": culture[:4000], "draft": draft}, ensure_ascii=False)
    data = chat_json(system, user)
    if not isinstance(data, dict) or not data.get("shots"):
        raise ReverseError("GROK_JSON", "本地化没有返回 shots")
    data["origin"] = "reverse-localized-grok"
    data.setdefault("aspect", "9:16")
    data.setdefault("kind", "shortdrama")
    data.setdefault("episode", "ep01")
    for src, dest in zip(draft.get("shots") or [], data.get("shots") or []):
        for key in ("source_start", "source_end", "source_frame"):
            if key in src and key not in dest:
                dest[key] = src[key]
    return data


def draft_to_episode_markdown(draft: dict, title: str = "反推本地化第 01 集") -> str:
    shots = draft.get("shots") or []
    total = sum(int(s.get("seconds") or 0) for s in shots)
    lines = [
        f"# 第 01 集：{title}",
        "",
        "- **状态**：draft · 来自参考片反推，未锁定",
        f"- **时长**：{total} 秒",
        "- **画幅**：9:16",
        "- **一句**：把参考片的冲突改成金边能认的空间和身体。",
        "",
        "## 节拍",
        "",
        "| # | 秒 | 镜 | 地点 | 新信息 |",
        "|---|---|---|---|---|",
    ]
    t = 0
    for shot in shots:
        lines.append(
            f"| {shot['id']} | {t} | {shot.get('setup')} | {shot.get('scene')} | {shot.get('new_info')} |"
        )
        t += int(shot.get("seconds") or 0)
    lines += ["", "## 对白（工作轨）", ""]
    for shot in shots:
        who = ",".join(shot.get("characters") or [])
        lines.append(f"- {shot['id']}（{who}）：{shot.get('line')}")
    lines += ["", "## 资产需求", ""]
    people = sorted({c for s in shots for c in (s.get("characters") or [])})
    scenes = sorted({s.get("scene") for s in shots if s.get("scene")})
    lines.append("- 角色：" + ", ".join(people))
    lines.append("- 场景：" + ", ".join(scenes))
    lines.append("")
    return "\n".join(lines)



def write_sets_draft(prod: Path, draft: dict) -> dict:
    scenes = []
    seen: set[str] = set()
    for shot in draft.get("shots") or []:
        scene = str(shot.get("scene") or "").strip()
        if not scene or scene in seen:
            continue
        seen.add(scene)
        marks = [{"id": "camera", "x": 0.5, "y": 0.95, "note": "与空镜同一轴"}]
        for index, name in enumerate(shot.get("characters") or []):
            marks.append({"id": name, "x": round(0.28 + index * 0.18, 2), "y": 0.62, "note": name})
        scenes.append(
            {
                "id": scene,
                "master": f"02-assets/scenes/{scene}/master.jpg",
                "blocking": f"02-assets/scenes/{scene}/blocking.jpg",
                "axis": str(shot.get("look") or "")[:80],
                "marks": marks,
            }
        )
    payload = {"sets": scenes}
    save_json(prod, "00-reverse/sets.draft.json", payload)
    return payload



def seed_asset_folders(prod: Path, draft: dict, create_missing: bool = True) -> list[str]:
    created = []
    names = sorted({c for s in (draft.get("shots") or []) for c in (s.get("characters") or [])})
    existing_chars = {child.name for child in (prod / "02-assets" / "characters").glob("*") if child.is_dir()} if (prod / "02-assets" / "characters").exists() else set()
    aliases = {"yeay-ros": "ros", "guard": "bodyguard"}
    for name in names:
        mapped = aliases.get(name, name)
        if mapped in existing_chars:
            continue
        if name in existing_chars:
            continue
        if not create_missing:
            continue
        folder = prod / "02-assets" / "characters" / mapped
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(str(folder.relative_to(prod)))
        card = prod / "02-assets" / "characters" / f"{mapped}.md"
        if not card.exists():
            card.write_text(f"# {mapped}\n\n草稿角色。先出 master/face/sheet，再锁 Gate B。\n", encoding="utf-8")
            created.append(str(card.relative_to(prod)))
    for scene in sorted({s.get("scene") for s in (draft.get("shots") or []) if s.get("scene")}):
        folder = prod / "02-assets" / "scenes" / scene
        if folder.exists():
            continue
        if not create_missing:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        created.append(str(folder.relative_to(prod)))
        card = prod / "02-assets" / "scenes" / f"{scene}.md"
        if not card.exists():
            card.write_text(f"# {scene}\n\n草稿场景。先出空镜 master，再打 blocking。\n", encoding="utf-8")
            created.append(str(card.relative_to(prod)))
    return created


def localize_production(prod: Path, *, brief: str = "", use_grok: bool = True) -> dict:
    draft = load_json(prod, "00-reverse/original.shots.json", {})
    if not draft.get("shots"):
        draft = load_json(prod, "03-storyboard/shots.draft.json", {})
    if not draft.get("shots"):
        raise ReverseError("NO_DRAFT", "还没有反推草稿，先分析参考片")
    brief = brief.strip() or KHMER_DEFAULT_BRIEF
    culture = ""
    culture_path = ROOT / "CULTURE.md"
    if culture_path.exists():
        culture = culture_path.read_text(encoding="utf-8")
    localized = heuristic_localize(draft, brief)
    grok_error = None
    if use_grok:
        try:
            localized = grok_localize(draft, brief, culture)
        except Exception as exc:
            grok_error = str(exc)
            localized["grok_error"] = grok_error
    save_json(prod, "03-storyboard/shots.draft.json", localized)
    save_json(prod, "00-reverse/localized.shots.json", localized)
    write_sets_draft(prod, localized)
    seeded_assets = seed_asset_folders(prod, localized)
    episode_md = draft_to_episode_markdown(localized)
    write_text(prod, "00-reverse/localized.md", episode_md)
    write_text(
        prod,
        "00-reverse/localize.md",
        "# 本地化说明\n\n" + brief + "\n\norigin: " + str(localized.get("origin")) + "\n",
    )
    docs = reverse_docs(
        localized,
        load_json(prod, "00-reverse/audio/transcript.json", {}),
        load_json(prod, "00-reverse/source.json", {}),
        f"本地化分镜 · {prod.name}",
    )
    write_text(prod, "00-reverse/beats.md", docs["beats"])
    write_text(prod, "00-reverse/coverage.md", docs["coverage"])
    seeded = maybe_seed_storyboard_docs(prod, docs["beats"], docs["coverage"])
    ep01 = prod / "01-bible" / "ep01.md"
    seeded_bible = False
    if _is_placeholder(ep01.read_text(encoding="utf-8") if ep01.exists() else "", ("他必须 ______",)):
        write_text(prod, "01-bible/ep01.md", episode_md)
        seeded_bible = True
    return {
        "ok": True,
        "draft": localized,
        "grok_error": grok_error,
        "seeded": seeded["seeded"] + seeded_assets + (["01-bible/ep01.md"] if seeded_bible else []),
    }


def snapshot_reverse(prod: Path) -> dict:
    info = load_json(prod, "00-reverse/source.json", {})
    analysis = load_json(prod, "00-reverse/analysis.json", {})
    draft = load_json(prod, "03-storyboard/shots.draft.json", {"shots": []})
    original = load_json(prod, "00-reverse/original.shots.json", {"shots": []})
    frames = []
    frame_dir = prod / "00-reverse" / "frames"
    if frame_dir.exists():
        for path in sorted(frame_dir.glob("*.jpg")):
            frames.append(
                {
                    "id": path.stem,
                    "path": f"00-reverse/frames/{path.name}",
                    "url": media_url(prod, f"00-reverse/frames/{path.name}"),
                }
            )
    video = prod / "00-reverse" / "source" / "reference.mp4"
    return {
        "source": info,
        "analysis": analysis,
        "draft": draft,
        "original": original,
        "frames": frames,
        "video_url": media_url(prod, "00-reverse/source/reference.mp4"),
        "has_source": video.exists(),
        "whisper_model": str(find_whisper_model() or ""),
        "grok_text": bool(os.environ.get("XAI_API_KEY", "").strip()),
    }


def enqueue_reverse(prod: Path, *, action: str, brief: str = "", use_grok: bool = True) -> dict:
    job = {
        "id": f"rev-{uuid.uuid4().hex[:10]}",
        "kind": "reverse",
        "action": action,
        "status": "queued",
        "brief": brief,
        "use_grok": use_grok,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "log": [],
        "error": None,
        "outputs": [],
    }
    data = load_jobs(prod)
    data.setdefault("jobs", [])
    data["jobs"].insert(0, job)
    save_jobs(prod, data)
    try:
        if action == "analyze":
            result = analyze_production(prod, use_grok=use_grok, brief=brief)
            job["status"] = "ready"
            job["outputs"] = ["00-reverse/analysis.json", "03-storyboard/shots.draft.json"]
            job["result"] = result["analysis"]
        elif action == "localize":
            result = localize_production(prod, brief=brief, use_grok=use_grok)
            job["status"] = "ready"
            job["outputs"] = ["03-storyboard/shots.draft.json", "00-reverse/localized.shots.json"]
            job["result"] = {
                "origin": result["draft"].get("origin"),
                "grok_error": result.get("grok_error"),
                "seeded": result.get("seeded") or [],
            }
        else:
            raise ReverseError("BAD_ACTION", f"未知反推动作 {action}")
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["updated_at"] = int(time.time())
        data = load_jobs(prod)
        for item in data.get("jobs") or []:
            if item.get("id") == job["id"]:
                item.update(job)
        save_jobs(prod, data)
        raise
    job["updated_at"] = int(time.time())
    data = load_jobs(prod)
    for item in data.get("jobs") or []:
        if item.get("id") == job["id"]:
            item.update(job)
    save_jobs(prod, data)
    return job
