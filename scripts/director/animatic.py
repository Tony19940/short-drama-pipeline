"""Stills animatic: the locked keyframes cut to the shot table's seconds.

A review tool, not a finish path. It answers "does the rhythm hold" before any
video is rendered. Output lives only under `03-storyboard/animatic/`; nothing
here may write into `05-shots/` or `06-export/`, and `assemble.sh` / the cut
job never read that folder.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from .production import load_json
from .shot_table import SCHEMA as SHOT_TABLE_SCHEMA

WIDTH, HEIGHT = 1672, 941
STRIP_H = 96
GREY = (54, 54, 54)
STRIP_BG = (0, 0, 0)
STRIP_FG = (243, 241, 234)
MISSING_FG = (154, 149, 136)
FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
ANIMATIC_DIR = "03-storyboard/animatic"
FORBIDDEN_DIRS = ("05-shots", "06-export")


def _t(value: Any) -> str:
    return str(value or "").strip()


def _sec(value: Any, default: float = 4.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out > 0 else default


def _episode_token(episode: Any = 1) -> str:
    from .takes import episode_key

    return episode_key(episode)


def _animatic_stem(episode: Any = 1) -> str:
    key = _episode_token(episode)
    return "ep01" if key == "1" else key


def episode_shot_list_name(episode: Any = 1) -> str:
    from .pipeline import episode_artifact_name

    return episode_artifact_name("shot_list.json", episode)


def episode_frames_dir(episode: Any = 1) -> str:
    from .pipeline import episode_frame_dir

    return episode_frame_dir(episode)


def animatic_rel(episode: Any = 1, *, prod: Optional[Path] = None) -> str:
    if prod is not None:
        from .revisions import resolve_binding

        episode = resolve_binding(prod, episode).episode_token
    return f"{ANIMATIC_DIR}/{_animatic_stem(episode)}.animatic.mp4"


def animatic_output_path(prod: Path, episode: int = 1, out: Optional[str] = None) -> Path:
    """Only `03-storyboard/animatic/*.mp4`. Anything under 05-shots / 06-export is refused."""
    rel = _t(out) or animatic_rel(episode, prod=prod)
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise PermissionError(f"animatic 输出路径非法：{rel}")
    parts = [p.lower() for p in rel_path.parts]
    for bad in FORBIDDEN_DIRS:
        if bad in parts:
            raise PermissionError(f"animatic 是审片工具，不能写进 {bad}/")
    if rel_path.parts[:2] != ("03-storyboard", "animatic"):
        raise PermissionError(f"animatic 只能写到 {ANIMATIC_DIR}/，不是 {rel}")
    if rel_path.suffix.lower() != ".mp4":
        raise PermissionError("animatic 输出必须是 .mp4")
    if not (Path(prod) / rel_path).resolve().is_relative_to(Path(prod).resolve()):
        raise PermissionError("animatic 输出必须在项目内")
    return prod / rel_path


def load_shots(prod: Path, episode: int = 1) -> list[dict]:
    """Shot rows with id and seconds: v2 table first, legacy shots.json second."""
    from .revisions import resolve_binding

    binding = resolve_binding(prod, episode)
    table = binding.read_artifact("shot_list.json")

    def rows_from(shots: list[dict], *, v2: bool) -> list[dict]:
        rows: list[dict] = []
        for shot in shots:
            sid = _t(shot.get("shot_id") or shot.get("id"))
            if not sid:
                continue
            rows.append({
                "shot_id": sid,
                "seconds": _sec(shot.get("duration_sec") if v2 else (shot.get("seconds") or shot.get("duration_sec"))),
                "scale": _t(shot.get("scale") or ("" if v2 else shot.get("setup"))),
                "coverage": _t(shot.get("coverage_type") or ("" if v2 else shot.get("setup"))),
                "one_action": _t(shot.get("one_action") or shot.get("action") or shot.get("start")),
                "t0_phase": _t(shot.get("t0_phase")),
                "in_from": _t(shot.get("in_from") or shot.get("start")),
                "out_to": _t(shot.get("out_to")),
                "action_timing": list(shot.get("action_timing") or shot.get("performance_beats") or []),
                "stimulus": _t(shot.get("stimulus") or shot.get("stimulus_line")),
                "dialogue": shot.get("dialogue") or shot.get("dialogue_ref") or shot.get("line") or "",
            })
        return rows

    if _t(table.get("schema")) == SHOT_TABLE_SCHEMA or binding.mode == "registered":
        rows = rows_from(list(table.get("shots") or []), v2=True)
        if rows:
            return rows
        if binding.mode == "registered":
            return []
    from .pipeline import episode_label

    label = episode_label(episode)
    legacy_rel = "03-storyboard/shots.json" if not label else f"03-storyboard/shots.{label}.json"
    legacy = load_json(prod, legacy_rel, {"shots": []})
    rows = rows_from(list(legacy.get("shots") or []), v2=False)
    if rows:
        return rows
    return rows_from(list(table.get("shots") or []), v2=False)


def _label(row: dict, seconds: float, part: str = "") -> str:
    size = row.get("scale") or ""
    if row.get("coverage") and row.get("coverage") != row.get("scale"):
        size = f"{size}/{row['coverage']}" if size else row["coverage"]
    bits = [row["shot_id"] + (f" {part}" if part else ""), f"{seconds:g}s"]
    if size:
        bits.append(size)
    action = _t(row.get("one_action"))
    if action:
        bits.append(action[:48])
    return " · ".join(bits)


def _absolute_beats(row: dict, seconds: float) -> Optional[list[dict]]:
    """Keep from/to. Overlaps are refused instead of being rescaled into a sequence."""
    raw = row.get("action_timing") or []
    if not isinstance(raw, list) or not raw:
        return None
    windows: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("from_sec", item.get("from", 0)))
            end = float(item.get("to_sec", item.get("to", start)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{row.get('shot_id')} beat times must be numbers") from exc
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError(f"{row.get('shot_id')} beat needs a finite range with to > from")
        if start < -0.001 or end > seconds + 0.05:
            raise ValueError(f"{row.get('shot_id')} beat {start:g}-{end:g}s is outside {seconds:g}s")
        windows.append({
            "from_sec": round(start, 3),
            "to_sec": round(min(end, seconds), 3),
            "text": _t(item.get("text") or item.get("action") or item.get("stimulus")),
        })
    if not windows:
        return None
    windows.sort(key=lambda item: (item["from_sec"], item["to_sec"]))
    for prev, nxt in zip(windows, windows[1:]):
        if nxt["from_sec"] < prev["to_sec"] - 0.001:
            raise ValueError(f"{row.get('shot_id')} beats overlap; refusing to play them in sequence")
    return windows


def _card_image(from_sec: float, to_sec: float, seconds: float, first_rel: str, last_rel: str, first_ok: bool, last_ok: bool) -> tuple[Optional[str], str, bool]:
    """t=0 uses the first still. The last still is only the window that lands at the end."""
    if from_sec <= 0.001:
        return (first_rel if first_ok else None), "first", not first_ok
    if last_ok and abs(to_sec - seconds) <= 0.05 and from_sec > 0.001:
        return last_rel, "last", False
    return None, "hold", True


def plan_animatic(prod: Path, episode: Any = 1) -> list[dict]:
    """Pure: which image shows for how long, in table order. No PIL, no ffmpeg.

    Written beats keep their absolute times. Gaps are explicit holds.
    Without beats, a locked last frame still splits first half / second half.
    """
    from .revisions import resolve_binding
    from place_codex_frame import frame_role_info

    binding = resolve_binding(prod, episode)
    frames = binding.frames_dir
    keyframes = binding.read_artifact("keyframes.json")
    by_id = {item.get("shot_id"): item for item in (keyframes.get("keyframes") or keyframes.get("frames") or []) if isinstance(item, dict)}
    packages = binding.read_artifact("gen_packages.json")
    package_by_id = {item.get("shot_id"): item for item in (packages.get("packages") or packages.get("gen_packages") or []) if isinstance(item, dict)}
    plan: list[dict] = []
    for row in load_shots(prod, episode):
        sid = row["shot_id"]
        seconds = float(row["seconds"])
        frame = by_id.get(sid) or {}
        first_rel = _t(frame.get("first_frame_file")) or f"{frames}/{sid}.jpg"
        declared_end = _t(frame.get("planned_end_file") or frame.get("end_frame_file") or frame.get("last_frame_file"))
        last_rel = declared_end or (f"{frames}/{sid}-end.jpg" if (prod / frames / f"{sid}-end.jpg").is_file() else f"{frames}/{sid}-last.jpg")
        first_ok = (prod / first_rel).exists()
        generated_end = frame_role_info(prod, last_rel)["frame_role"] == "generated_end" or last_rel.startswith("05-shots/")
        last_ok = first_ok and (prod / last_rel).is_file() and not generated_end
        needs_end = bool(declared_end) or generated_end or (package_by_id.get(sid) or {}).get("keyframe_plan") == "first_last"
        beats = _absolute_beats(row, seconds)
        if beats:
            cursor = 0.0
            spans: list[dict] = []
            for beat in beats:
                if beat["from_sec"] > cursor + 0.001:
                    spans.append({"from_sec": round(cursor, 3), "to_sec": beat["from_sec"], "text": "空档", "hold": True})
                spans.append({**beat, "hold": False})
                cursor = beat["to_sec"]
            if cursor < seconds - 0.001:
                spans.append({"from_sec": round(cursor, 3), "to_sec": round(seconds, 3), "text": "空档", "hold": True})
            for span in spans:
                image, part, missing = _card_image(span["from_sec"], span["to_sec"], seconds, first_rel, last_rel, first_ok, last_ok)
                dur = round(span["to_sec"] - span["from_sec"], 3)
                if span.get("hold") or missing:
                    note = "该状态尚无图" if missing and not span.get("hold") else span["text"]
                    if missing and span.get("hold") and span["from_sec"] > 0.001:
                        note = "空档·该状态尚无图"
                else:
                    note = span["text"]
                extra = f" {note[:24]}" if note else ""
                plan.append({
                    "shot_id": sid,
                    "image": image,
                    "seconds": dur,
                    "from_sec": span["from_sec"],
                    "to_sec": span["to_sec"],
                    "label": _label(row, seconds, "尾" if part == "last" else "首") + extra + ("" if not missing else " · 缺图"),
                    "missing": missing,
                    "part": part,
                    "beat": span["text"],
                    "stimulus": row.get("stimulus") or "",
                    "one_action": row.get("one_action") or "",
                })
            continue
        if last_ok or needs_end:
            half = round(seconds / 2, 3)
            plan.append({"shot_id": sid, "image": first_rel if first_ok else None, "seconds": half, "from_sec": 0, "to_sec": half, "label": _label(row, seconds, "首"), "missing": not first_ok, "part": "first", "beat": "", "stimulus": row.get("stimulus") or "", "one_action": row.get("one_action") or ""})
            plan.append({"shot_id": sid, "image": last_rel if last_ok else None, "seconds": round(seconds - half, 3), "from_sec": half, "to_sec": round(seconds, 3), "label": _label(row, seconds, "尾") + ("" if last_ok else " · 缺设计尾"), "missing": not last_ok, "part": "last", "beat": "", "stimulus": row.get("stimulus") or "", "one_action": row.get("one_action") or ""})
        else:
            plan.append({
                "shot_id": sid,
                "image": first_rel if first_ok else None,
                "seconds": round(seconds, 3),
                "from_sec": 0,
                "to_sec": round(seconds, 3),
                "label": _label(row, seconds) + ("" if first_ok else " · 缺首帧"),
                "missing": not first_ok,
                "part": "first",
                "beat": "",
                "stimulus": row.get("stimulus") or "",
                "one_action": row.get("one_action") or "",
            })
    for item in plan:
        if item.get("image"):
            role = frame_role_info(prod, item["image"])
            item["frame_role"] = role["frame_role"]
            item["role_warnings"] = role["warnings"]
    return plan


def find_font(size: int):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_card(image: Optional[Path], label: str, dest: Path, *, missing: bool = False) -> Path:
    """One 1672×941 frame: the still letterboxed onto a dark canvas, label strip burned at the bottom."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (WIDTH, HEIGHT), GREY if missing or image is None else (0, 0, 0))
    if image is not None and image.exists() and not missing:
        still = Image.open(image).convert("RGB")
        box_h = HEIGHT - STRIP_H
        ratio = min(WIDTH / still.width, box_h / still.height)
        size = (max(1, int(still.width * ratio)), max(1, int(still.height * ratio)))
        still = still.resize(size, Image.LANCZOS)
        canvas.paste(still, ((WIDTH - size[0]) // 2, (box_h - size[1]) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, HEIGHT - STRIP_H, WIDTH, HEIGHT), fill=STRIP_BG)
    font = find_font(34)
    text = label
    while text and draw.textlength(text, font=font) > WIDTH - 48:
        text = text[:-2]
    draw.text((24, HEIGHT - STRIP_H + 28), text, font=font, fill=MISSING_FG if missing else STRIP_FG)
    if missing:
        big = find_font(72)
        draw.text((WIDTH // 2 - 120, HEIGHT // 2 - 90), "缺首帧", font=big, fill=MISSING_FG)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=90)
    return dest


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def build_animatic(
    prod: Path,
    episode: Any = 1,
    *,
    audio: Optional[str] = None,
    audio_file: Optional[str] = None,
    fps: int = 24,
    out: Optional[str] = None,
) -> dict:
    """Cards → concat demuxer → mp4 under 03-storyboard/animatic/. Returns the plan and the file."""
    from .revisions import resolve_binding

    episode_key = _episode_token(resolve_binding(prod, episode).episode_token)
    dest = animatic_output_path(prod, episode, out)
    plan = plan_animatic(prod, episode)
    if not plan:
        raise PermissionError("没有镜头表，先拆镜再出 animatic")
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg")
    if audio and audio_file and _t(audio) != _t(audio_file):
        raise ValueError("audio 与 audio_file 不能指向不同音轨")
    audio = audio_file or audio
    audio_path: Optional[Path] = None
    if _t(audio):
        audio_path = Path(audio) if Path(audio).is_absolute() else prod / audio
        if not audio_path.exists():
            raise ValueError(f"音轨不存在：{audio}")
    fps = max(1, int(fps or 24))
    total = round(sum(float(item["seconds"]) for item in plan), 3)
    input_fingerprint = animatic_input_fingerprint(prod, episode, audio_file=audio)
    with tempfile.TemporaryDirectory(prefix="animatic-") as tmp:
        work = Path(tmp)
        lines: list[str] = []
        last_card: Optional[Path] = None
        for index, item in enumerate(plan):
            card = work / f"card{index:03d}.jpg"
            image = prod / item["image"] if item.get("image") else None
            render_card(image, item["label"], card, missing=bool(item.get("missing")))
            lines.append(f"file '{card}'")
            lines.append(f"duration {float(item['seconds']):.3f}")
            last_card = card
        if last_card is not None:
            lines.append(f"file '{last_card}'")  # concat demuxer needs the last file twice to honour its duration
        list_path = work / "concat.txt"
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path)]
        if audio_path is not None:
            cmd += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"]
        # libx264 needs even dimensions; the official 1672×941 card loses one row here, nothing else.
        # `-t` pins the length to the table's seconds: the demuxer's handling of the last image varies by ffmpeg version.
        even_w, even_h = WIDTH - WIDTH % 2, HEIGHT - HEIGHT % 2
        cmd += [
            "-vf", f"fps={fps},scale={even_w}:{even_h}", "-r", str(fps), "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-movflags", "+faststart",
            "-t", f"{total:.3f}", str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg 失败")[-1200:])
    sidecar = dest.with_suffix(".json")
    sidecar.write_text(
        json.dumps({
            "schema": "animatic-build-v3", "episode": episode_key, "fps": fps,
            "total_sec": total, "audio": _t(audio) or None, "audio_file": _t(audio) or None,
            "audio_sha256": _audio_digest(prod, _t(audio)), "plan": plan,
            "input_fingerprint": input_fingerprint, "media_sha256": _digest(dest),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "file": str(dest.relative_to(prod)),
        "sidecar": str(sidecar.relative_to(prod)),
        "episode": episode_key,
        "fps": fps,
        "total_sec": total,
        "cards": len(plan),
        "missing": [item["shot_id"] for item in plan if item.get("missing")],
        "plan": plan,
        "note": "审片工具，不是成片路径。不进 05-shots / 06-export。",
    }


def _digest(path: Path) -> str:
    from .vendor_request import sha256_file

    return sha256_file(path) if path.is_file() else ""


def _audio_digest(prod: Path, audio_file: str) -> str:
    if not audio_file:
        return ""
    path = Path(audio_file)
    return _digest(path if path.is_absolute() else Path(prod) / path)


def _audio_required(prod: Path, episode: Any) -> bool:
    """An audio stream is necessary evidence when this table assigns audible story."""
    from .revisions import resolve_binding

    binding = resolve_binding(prod, episode)
    table = binding.read_artifact("shot_list.json")
    if binding.mode == "legacy" and not table.get("shots"):
        from .pipeline import episode_label

        label = episode_label(binding.episode_token)
        table = load_json(prod, f"03-storyboard/shots.{label}.json" if label else "03-storyboard/shots.json", {})
    if table.get("audio_required") or table.get("sound_required"):
        return True
    for shot in table.get("shots") or []:
        dialogue = shot.get("dialogue") or shot.get("dialogue_ref")
        if isinstance(dialogue, dict):
            dialogue = dialogue.get("line_work_zh") or dialogue.get("line") or dialogue.get("text")
        if dialogue or (shot.get("line") and shot.get("line_kind") not in {"reaction", "sms"}):
            return True
        if shot.get("audio_required") or shot.get("sound_required") or shot.get("sound_events") or shot.get("sound_ref") or shot.get("sfx"):
            return True
    return False


def _probe_animatic(path: Path) -> dict:
    """Inspect the actual review movie, not a sidecar claim about its streams."""
    if not path.is_file():
        return {"video": False, "audio": False}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        streams = data.get("streams") or []
        duration = float((data.get("format") or {}).get("duration") or 0)
        return {"video": duration > 0 and any(row.get("codec_type") == "video" for row in streams),
                "audio": any(row.get("codec_type") == "audio" for row in streams)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"video": False, "audio": False}


def animatic_input_fingerprint(prod: Path, episode: Any = 1, *, audio_file: Optional[str] = None) -> str:
    """Bind pictures, the complete shot contract and the optional source sound."""
    import hashlib

    from .vendor_request import media_hash
    from .revisions import resolve_binding

    binding = resolve_binding(prod, episode)
    plan = plan_animatic(prod, episode)
    source = binding.artifact_path("shot_list.json")
    if binding.mode == "legacy" and not source.is_file():
        from .pipeline import episode_label

        label = episode_label(binding.episode_token)
        source = prod / (f"03-storyboard/shots.{label}.json" if label else "03-storyboard/shots.json")
    payload = {
        "version": "rehearsal-v3",
        "episode": _episode_token(binding.episode_token),
        "binding": binding.to_dict(),
        "shot_list_sha256": _digest(source),
        "audio_file": _t(audio_file),
        "audio_sha256": _audio_digest(prod, _t(audio_file)),
        "cards": [
            {
                "shot_id": item.get("shot_id"),
                "from_sec": item.get("from_sec"),
                "to_sec": item.get("to_sec"),
                "seconds": item.get("seconds"),
                "part": item.get("part"),
                "beat": item.get("beat") or "",
                "stimulus": item.get("stimulus") or "",
                "one_action": item.get("one_action") or "",
                "image": item.get("image") or "",
                "image_hash": media_hash(prod, _t(item.get("image"))) if item.get("image") else "missing",
                "frame_role": item.get("frame_role") or "unknown",
            }
            for item in plan
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def animatic_approval_path(prod: Path, episode: Any = 1) -> Path:
    from .revisions import resolve_binding

    return Path(prod) / ANIMATIC_DIR / f"{_animatic_stem(resolve_binding(prod, episode).episode_token)}.approval.json"


def write_animatic_approval(
    prod: Path, episode: Any = 1, reviewer: str = "", *, notes: str = "",
    file: Optional[str] = None, input_only: bool = False,
) -> dict:
    """Sign a built movie; an explicit input-only note cannot authorize paid output."""
    from .revisions import resolve_binding

    if not _t(reviewer) or _t(reviewer).lower() == "unknown":
        raise PermissionError("animatic 审批需要实名 reviewer")
    movie = animatic_output_path(prod, episode, file)
    rel = movie.relative_to(prod).as_posix()
    metadata: dict = {}
    if not input_only:
        if not _t(notes):
            raise PermissionError("animatic 审批需要看片结论 notes")
        if not movie.is_file() or not movie.with_suffix(".json").is_file():
            raise PermissionError("animatic 未构建；必须先审实际 MP4，不能只批准输入")
        try:
            metadata = json.loads(movie.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PermissionError("animatic 构建记录不可读") from exc
        if not isinstance(metadata, dict):
            raise PermissionError("animatic 构建记录必须是对象")
        audio = _t(metadata.get("audio_file") or metadata.get("audio"))
        current = animatic_input_fingerprint(prod, episode, audio_file=audio)
        if metadata.get("schema") != "animatic-build-v3" or metadata.get("input_fingerprint") != current or metadata.get("media_sha256") != _digest(movie):
            raise PermissionError("animatic 构建证据已过期；重新构建后审片")
        plan = plan_animatic(prod, episode)
        if not plan or any(item.get("missing") for item in plan):
            raise PermissionError("animatic 有缺图/缺状态，不能批准收费出片")
        probe = _probe_animatic(movie)
        if not probe["video"]:
            raise PermissionError("animatic MP4 不可读")
        if audio and not _audio_digest(prod, audio):
            raise PermissionError("animatic 源音轨缺失")
        if _audio_required(prod, episode) and (not audio or not probe["audio"]):
            raise PermissionError("对白/声音需要声画预演，静音稿不能批准收费出片")
    else:
        audio = ""
        current = animatic_input_fingerprint(prod, episode)
    dest = animatic_approval_path(prod, episode)
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": "animatic-approval-v3",
        "episode": _episode_token(resolve_binding(prod, episode).episode_token),
        "fingerprint": current,
        "reviewer": _t(reviewer), "notes": _t(notes),
        "approved_at": __import__("time").time(),
        "file": rel,
        "kind": "input_only" if input_only else "rehearsal",
        "input_only": bool(input_only),
        "media_sha256": "" if input_only else _digest(movie),
        "audio_file": audio, "audio_sha256": _audio_digest(prod, audio),
    }
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return body


def animatic_approval_status(prod: Path, episode: Any = 1) -> dict:
    path = animatic_approval_path(prod, episode)
    current = animatic_input_fingerprint(prod, episode)
    if not path.is_file():
        return {"exists": False, "ok": False, "stale": False, "fingerprint": "", "current": current}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "ok": False, "stale": True, "fingerprint": "", "current": current}
    if not isinstance(data, dict):
        return {"exists": True, "ok": False, "stale": True, "fingerprint": "", "current": current}
    stored = _t(data.get("fingerprint"))
    audio = _t(data.get("audio_file"))
    current = animatic_input_fingerprint(prod, episode, audio_file=audio)
    input_only = data.get("input_only") is True or data.get("schema") != "animatic-approval-v3" or not data.get("media_sha256")
    reasons: list[str] = []
    if input_only:
        reasons.append("input_only 审批不能用于收费出片")
    if not _t(data.get("reviewer")) or _t(data.get("reviewer")).lower() == "unknown" or not _t(data.get("notes")):
        reasons.append("缺审核者或看片结论")
    try:
        movie = animatic_output_path(prod, episode, _t(data.get("file")) or None)
    except PermissionError:
        movie = None
        reasons.append("审批媒体路径非法")
    media_digest = _digest(movie) if movie is not None else ""
    stale = stored != current or (not input_only and media_digest != _t(data.get("media_sha256")))
    probe = _probe_animatic(movie) if movie is not None and not input_only else {"video": False, "audio": False}
    if not input_only and not probe["video"]:
        reasons.append("缺可播放预演 MP4")
    plan = plan_animatic(prod, episode)
    if not plan or any(item.get("missing") for item in plan):
        reasons.append("预演缺图/缺状态")
    if audio and (not _audio_digest(prod, audio) or _audio_digest(prod, audio) != _t(data.get("audio_sha256"))):
        stale = True
    if _audio_required(prod, episode) and (not audio or not probe["audio"]):
        reasons.append("对白/声音未以声画预演审阅")
    return {
        "exists": True,
        "ok": bool(stored) and not stale and not reasons,
        "stale": stale,
        "fingerprint": stored,
        "current": current,
        "reviewer": _t(data.get("reviewer")),
        "input_only": input_only, "reasons": reasons, "file": _t(data.get("file")),
    }


def require_animatic_approval(prod: Path, episode: Any = 1) -> dict:
    status = animatic_approval_status(prod, episode)
    if not status["exists"]:
        raise PermissionError("animatic 未审批，不能收费出片")
    if status["stale"]:
        raise PermissionError("animatic 审批已过期（镜头表或首帧已变），重新审预演")
    if not status["ok"]:
        raise PermissionError("animatic 审批证据不完整：" + "；".join(status.get("reasons") or []))
    return status


def snapshot_animatic(prod: Path, episode: Any = 1) -> dict:
    """What the studio shows before/after building: the plan, the file if it exists."""
    from .paths import media_url
    from .revisions import resolve_binding

    rel = animatic_rel(episode, prod=prod)
    path = prod / rel
    plan = plan_animatic(prod, episode)
    frames: dict[str, str] = {}
    last_frames: dict[str, str] = {}
    for item in plan:
        if item.get("image") and not item.get("missing"):
            url = media_url(prod, item["image"])
            if not url:
                continue
            if item.get("part") == "last":
                last_frames[item["shot_id"]] = url
            elif item.get("part") == "first":
                frames[item["shot_id"]] = url
    return {
        "episode": _episode_token(resolve_binding(prod, episode).episode_token),
        "exists": path.exists(),
        "file": rel if path.exists() else None,
        "url": media_url(prod, rel),
        "cards": len(plan),
        "missing": [item["shot_id"] for item in plan if item.get("missing")],
        "total_sec": round(sum(float(item["seconds"]) for item in plan), 3),
        "ffmpeg": ffmpeg_available(),
        "frames": frames,
        "last_frames": last_frames,
        "approval": animatic_approval_status(prod, episode),
    }
