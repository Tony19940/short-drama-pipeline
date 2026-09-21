"""Stills animatic: the locked keyframes cut to the shot table's seconds.

A review tool, not a finish path. It answers "does the rhythm hold" before any
video is rendered. Output lives only under `03-storyboard/animatic/`; nothing
here may write into `05-shots/` or `06-export/`, and `assemble.sh` / the cut
job never read that folder.
"""

from __future__ import annotations

import json
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


def episode_shot_list_name(episode: int) -> str:
    return "shot_list.json" if int(episode) == 1 else f"shot_list.ep{int(episode):02d}.json"


def episode_frames_dir(episode: int) -> str:
    return "04-frames" if int(episode) == 1 else f"04-frames/ep{int(episode):02d}"


def animatic_rel(episode: int) -> str:
    return f"{ANIMATIC_DIR}/ep{int(episode):02d}.animatic.mp4"


def animatic_output_path(prod: Path, episode: int = 1, out: Optional[str] = None) -> Path:
    """Only `03-storyboard/animatic/*.mp4`. Anything under 05-shots / 06-export is refused."""
    rel = _t(out) or animatic_rel(episode)
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
    return prod / rel_path


def load_shots(prod: Path, episode: int = 1) -> list[dict]:
    """Shot rows with id and seconds: v2 table first, legacy shots.json second."""
    from .pipeline import read_artifact

    table = read_artifact(prod, episode_shot_list_name(episode))

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
            })
        return rows

    if _t(table.get("schema")) == SHOT_TABLE_SCHEMA:
        rows = rows_from(list(table.get("shots") or []), v2=True)
        if rows:
            return rows
    legacy_rel = "03-storyboard/shots.json" if int(episode) == 1 else f"03-storyboard/shots.ep{int(episode):02d}.json"
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


def _beat_splits(row: dict, seconds: float) -> Optional[list[tuple[float, str]]]:
    """Performance-node windows. None means keep the old first/last half split."""
    raw = row.get("action_timing") or []
    if not isinstance(raw, list) or not raw:
        return None
    windows: list[tuple[float, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("from_sec", item.get("from", 0)) or 0)
            end = float(item.get("to_sec", item.get("to", start)) or start)
        except (TypeError, ValueError):
            continue
        dur = max(0.0, end - start)
        if dur <= 0:
            continue
        label = _t(item.get("text") or item.get("action") or item.get("stimulus"))
        windows.append((dur, label))
    if not windows:
        return None
    total = sum(item[0] for item in windows)
    if total <= 0:
        return None
    scale = seconds / total
    return [(round(dur * scale, 3), label) for dur, label in windows]


def plan_animatic(prod: Path, episode: int = 1) -> list[dict]:
    """Pure: which image shows for how long, in table order. No PIL, no ffmpeg.

    Performance beats, when present, decide when the picture changes.
    Without beats, a locked last frame still splits first half / second half.
    A shot without a first frame becomes a grey card flagged `missing`.
    """
    frames = episode_frames_dir(episode)
    plan: list[dict] = []
    for row in load_shots(prod, episode):
        sid = row["shot_id"]
        seconds = float(row["seconds"])
        first_rel = f"{frames}/{sid}.jpg"
        last_rel = f"{frames}/{sid}-last.jpg"
        first_ok = (prod / first_rel).exists()
        last_ok = first_ok and (prod / last_rel).exists()
        splits = _beat_splits(row, seconds)
        if splits and last_ok:
            last_index = len(splits) - 1
            for index, (dur, beat_label) in enumerate(splits):
                part = "last" if index == last_index else "first"
                image = last_rel if part == "last" else first_rel
                tag = "尾" if part == "last" else "首"
                extra = f" {beat_label[:24]}" if beat_label else ""
                plan.append({
                    "shot_id": sid,
                    "image": image,
                    "seconds": dur,
                    "label": _label(row, seconds, tag) + extra,
                    "missing": False,
                    "part": part,
                    "beat": beat_label,
                })
        elif splits:
            for index, (dur, beat_label) in enumerate(splits):
                extra = f" {beat_label[:24]}" if beat_label else ""
                plan.append({
                    "shot_id": sid,
                    "image": first_rel if first_ok else None,
                    "seconds": dur,
                    "label": _label(row, seconds) + extra + ("" if first_ok else " · 缺首帧"),
                    "missing": not first_ok,
                    "part": "first" if index == 0 else f"beat{index + 1}",
                    "beat": beat_label,
                })
        elif last_ok:
            half = round(seconds / 2, 3)
            plan.append({"shot_id": sid, "image": first_rel, "seconds": half, "label": _label(row, seconds, "首"), "missing": False, "part": "first"})
            plan.append({"shot_id": sid, "image": last_rel, "seconds": round(seconds - half, 3), "label": _label(row, seconds, "尾"), "missing": False, "part": "last"})
        else:
            plan.append({
                "shot_id": sid,
                "image": first_rel if first_ok else None,
                "seconds": round(seconds, 3),
                "label": _label(row, seconds) + ("" if first_ok else " · 缺首帧"),
                "missing": not first_ok,
                "part": "first",
            })
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
    episode: int = 1,
    *,
    audio: Optional[str] = None,
    fps: int = 24,
    out: Optional[str] = None,
) -> dict:
    """Cards → concat demuxer → mp4 under 03-storyboard/animatic/. Returns the plan and the file."""
    dest = animatic_output_path(prod, episode, out)
    plan = plan_animatic(prod, episode)
    if not plan:
        raise PermissionError("没有镜头表，先拆镜再出 animatic")
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg")
    audio_path: Optional[Path] = None
    if _t(audio):
        audio_path = Path(audio) if Path(audio).is_absolute() else prod / audio
        if not audio_path.exists():
            raise ValueError(f"音轨不存在：{audio}")
    fps = max(1, int(fps or 24))
    total = round(sum(float(item["seconds"]) for item in plan), 3)
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
        json.dumps({"episode": int(episode), "fps": fps, "total_sec": total, "audio": _t(audio) or None, "plan": plan}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "file": str(dest.relative_to(prod)),
        "sidecar": str(sidecar.relative_to(prod)),
        "episode": int(episode),
        "fps": fps,
        "total_sec": total,
        "cards": len(plan),
        "missing": [item["shot_id"] for item in plan if item.get("missing")],
        "plan": plan,
        "note": "审片工具，不是成片路径。不进 05-shots / 06-export。",
    }


def animatic_input_fingerprint(prod: Path, episode: int = 1) -> str:
    """Hash of the shot list durations plus each still's bytes. Approval binds to this."""
    import hashlib

    from .vendor_request import media_hash

    plan = plan_animatic(prod, episode)
    parts = []
    for item in plan:
        rel = _t(item.get("image"))
        digest = media_hash(prod, rel) if rel else "missing"
        parts.append(f"{item.get('shot_id')}:{item.get('seconds')}:{rel}:{digest}:{item.get('part')}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def animatic_approval_path(prod: Path, episode: int = 1) -> Path:
    return Path(prod) / ANIMATIC_DIR / f"ep{int(episode):02d}.approval.json"


def write_animatic_approval(prod: Path, episode: int = 1, reviewer: str = "") -> dict:
    dest = animatic_approval_path(prod, episode)
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "episode": int(episode),
        "fingerprint": animatic_input_fingerprint(prod, episode),
        "reviewer": _t(reviewer) or "unknown",
        "approved_at": __import__("time").time(),
        "file": animatic_rel(episode),
    }
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return body


def animatic_approval_status(prod: Path, episode: int = 1) -> dict:
    path = animatic_approval_path(prod, episode)
    current = animatic_input_fingerprint(prod, episode)
    if not path.is_file():
        return {"exists": False, "ok": False, "stale": False, "fingerprint": "", "current": current}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "ok": False, "stale": True, "fingerprint": "", "current": current}
    stored = _t(data.get("fingerprint"))
    stale = stored != current
    return {
        "exists": True,
        "ok": bool(stored) and not stale,
        "stale": stale,
        "fingerprint": stored,
        "current": current,
        "reviewer": _t(data.get("reviewer")),
    }


def require_animatic_approval(prod: Path, episode: int = 1) -> dict:
    status = animatic_approval_status(prod, episode)
    if not status["exists"]:
        raise PermissionError("animatic 未审批，不能收费出片")
    if status["stale"]:
        raise PermissionError("animatic 审批已过期（镜头表或首帧已变），重新审预演")
    return status


def snapshot_animatic(prod: Path, episode: int = 1) -> dict:
    """What the studio shows before/after building: the plan, the file if it exists."""
    from .paths import media_url

    rel = animatic_rel(episode)
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
        "episode": int(episode),
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
