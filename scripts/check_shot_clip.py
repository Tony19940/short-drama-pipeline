#!/usr/bin/env python3
"""Clip QC for one official shot mp4: internal cuts, last frame, optional next-first diff.

Not a VLM. Bopha feet/shoes are only flagged when frame_desc.forbidden mentions 脚/鞋
and the clip exists — a leftover-text heuristic, not a visual check.

    python3 scripts/check_shot_clip.py --prod productions/010-gongpai --shot SH011

Unit tests inject `runner` / skip real ffmpeg.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import productions_root, safe_under

SHOT_ID = re.compile(r"^SH\d{3}$")
SCENE_HIT = re.compile(r"scene_score|lavfi\.scene_score", re.I)
SCENE_SCORE = re.compile(r"lavfi\.scene_score=([0-9eE.+-]+)")
PTS_TIME = re.compile(r"pts_time:([0-9.]+)")
FEET = re.compile(r"脚|鞋")
DEFAULT_SCENE = 0.40


class SceneCutError(RuntimeError):
    """FFmpeg could not decode the clip or the scene-detect filter failed."""


Runner = Callable[..., Any]


def episode_shot_dir(episode: int = 1) -> str:
    return "05-shots" if int(episode) == 1 else f"05-shots/ep{int(episode):02d}"


def episode_frame_dir(episode: int = 1) -> str:
    return "04-frames" if int(episode) == 1 else f"04-frames/ep{int(episode):02d}"


def clip_rel(shot_id: str, episode: int = 1) -> str:
    return f"{episode_shot_dir(episode)}/{shot_id}.mp4"


def extracted_last_rel(shot_id: str) -> str:
    return f"08-qc/clips/{shot_id}-last.jpg"


def _t(value: Any) -> str:
    return str(value or "").strip()


def default_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def scene_cuts(
    video: Path,
    *,
    threshold: float = DEFAULT_SCENE,
    runner: Optional[Runner] = None,
) -> list[dict]:
    """Return detected scene-change hits with score and optional pts.

    Uses `metadata=mode=print:key=lavfi.scene_score`. FFmpeg 7 showinfo no
    longer prints that key name, so counting `scene_score` in the log misses
    real hard cuts. Injected unit-test logs without the print filter still
    count via the legacy regex.
    """
    run = runner or default_runner
    filt = f"select=gt(scene\\,{threshold}),metadata=mode=print:key=lavfi.scene_score"
    proc = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", filt, "-f", "null", "-"], check=False)
    text = f"{getattr(proc, 'stderr', '') or ''}{getattr(proc, 'stdout', '') or ''}"
    code = getattr(proc, "returncode", 0)
    if code not in (0, None):
        blob = text.lower()
        decode_fail = any(
            token in blob
            for token in (
                "invalid data",
                "error opening",
                "does not contain any stream",
                "invalid argument",
                "moov atom not found",
                "could not find codec",
            )
        )
        if decode_fail or not Path(video).is_file():
            raise SceneCutError(f"ffmpeg could not inspect {Path(video).name} (exit {code})")
        if code not in (0, 1):
            raise SceneCutError(f"ffmpeg scene detect failed ({code}): {text[-400:]}")
    hits: list[dict] = []
    for match in SCENE_SCORE.finditer(text):
        try:
            score = float(match.group(1))
        except ValueError:
            score = 0.0
        window = text[max(0, match.start() - 240) : match.start()]
        pts_match = list(PTS_TIME.finditer(window))
        pts = float(pts_match[-1].group(1)) if pts_match else None
        hits.append({"score": score, "pts": pts})
    if hits:
        return hits
    # Unit tests inject `scene_score:` logs without running the print filter.
    return [{"score": None, "pts": None} for _ in SCENE_HIT.findall(text)]


def scene_cut_count(video: Path, *, threshold: float = DEFAULT_SCENE, runner: Optional[Runner] = None) -> int:
    """Count ffmpeg scene-change hits after the first frame."""
    return len(scene_cuts(video, threshold=threshold, runner=runner))


def extract_last_frame(video: Path, dest: Path, *, runner: Optional[Runner] = None) -> Path:
    run = runner or default_runner
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = run(
        ["ffmpeg", "-y", "-hide_banner", "-sseof", "-0.05", "-i", str(video), "-frames:v", "1", str(dest)],
        check=False,
    )
    if getattr(proc, "returncode", 0) not in (0, None) or not dest.exists():
        raise RuntimeError(f"ffmpeg could not extract last frame from {video.name}")
    return dest


def frame_mean_diff(first: Path, second: Path) -> Optional[float]:
    """Mean absolute channel difference in 0–1. None if Pillow missing or files unreadable."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        a = Image.open(first).convert("RGB")
        b = Image.open(second).convert("RGB")
    except OSError:
        return None
    if a.size != b.size:
        b = b.resize(a.size)
    pa, pb = list(a.getdata()), list(b.getdata())
    if not pa:
        return 0.0
    total = 0
    for ca, cb in zip(pa, pb):
        total += abs(ca[0] - cb[0]) + abs(ca[1] - cb[1]) + abs(ca[2] - cb[2])
    return total / (len(pa) * 3 * 255.0)


def next_shot_id(prod: Path, shot_id: str, episode: int = 1) -> str:
    from director.pipeline import episode_artifact_name, read_artifact

    shots = list((read_artifact(prod, episode_artifact_name("shot_list.json", episode)).get("shots") or []))
    ids = [_t(s.get("shot_id")) for s in shots if _t(s.get("shot_id"))]
    try:
        idx = ids.index(shot_id)
    except ValueError:
        return ""
    if idx + 1 >= len(ids):
        return ""
    return ids[idx + 1]


def forbidden_feet_note(prod: Path, shot_id: str, episode: int = 1) -> str:
    """Weak heuristic: frame_desc.forbidden mentions 脚/鞋. Not a visual feet check."""
    from director.pipeline import episode_artifact_name, read_artifact

    data = read_artifact(prod, episode_artifact_name("frame_descriptions.json", episode))
    for item in data.get("items") or []:
        if _t(item.get("shot_id")) != shot_id:
            continue
        blob = " ".join(_t(x) for x in (item.get("forbidden") or []))
        if FEET.search(blob):
            return f"{shot_id} frame_desc.forbidden mentions 脚/鞋; no VLM, visual feet/shoes not checked"
    return ""


def check_clip(
    prod: Path,
    shot_id: str,
    *,
    episode: int = 1,
    threshold: float = DEFAULT_SCENE,
    runner: Optional[Runner] = None,
    extract: bool = True,
    allow_internal_cuts: int = 0,
) -> dict:
    """Importable QC. `runner` mocks ffmpeg. Does not require ffmpeg when extract is False and cuts are injected via runner."""
    shot_id = shot_id.upper()
    if not SHOT_ID.match(shot_id):
        raise ValueError("shot 必须是 SH001 这种编号")
    prod = prod.resolve()
    rel = clip_rel(shot_id, episode)
    video = safe_under(prod, rel)
    errors: list[str] = []
    warnings: list[str] = []
    last_rel = ""
    cuts = 0
    nxt_diff: Optional[float] = None
    if not video.exists():
        errors.append(f"missing clip {rel}")
        return {
            "ok": False,
            "shot_id": shot_id,
            "clip": rel,
            "errors": errors,
            "warnings": warnings,
            "scene_cuts": 0,
            "last_frame": "",
            "next_first_diff": None,
        }
    try:
        cuts = scene_cut_count(video, threshold=threshold, runner=runner)
    except SceneCutError as exc:
        errors.append(str(exc))
        cuts = 0
    allowed = max(0, int(allow_internal_cuts or 0))
    if cuts > allowed:
        errors.append(f"{shot_id} has {cuts} internal scene cut(s)")
    if extract:
        dest = safe_under(prod, extracted_last_rel(shot_id))
        try:
            extract_last_frame(video, dest, runner=runner)
            last_rel = extracted_last_rel(shot_id)
        except RuntimeError as exc:
            errors.append(str(exc))
    nxt = next_shot_id(prod, shot_id, episode)
    if last_rel and nxt:
        nxt_first = safe_under(prod, f"{episode_frame_dir(episode)}/{nxt}.jpg")
        last_path = safe_under(prod, last_rel)
        if nxt_first.exists() and last_path.exists():
            nxt_diff = frame_mean_diff(last_path, nxt_first)
            if nxt_diff is not None and nxt_diff > 0.35:
                warnings.append(f"{shot_id} last frame vs {nxt} first differs {nxt_diff:.2f} (crude)")
    feet = forbidden_feet_note(prod, shot_id, episode)
    if feet:
        warnings.append(feet)
    setup_changed = False
    if nxt:
        from director.setup_anchors import camera_projection_changed, shot_row

        setup_changed = camera_projection_changed(
            shot_row(prod, shot_id, episode),
            shot_row(prod, nxt, episode),
        )
        if setup_changed and nxt_diff is not None and nxt_diff > 0.35:
            warnings[:] = [w for w in warnings if "last frame vs" not in w]
            warnings.append(f"{shot_id} last vs {nxt} first differs {nxt_diff:.2f}; setup changed, not a fail")
    from director.qc_layers import evaluate_clip_layers, layers_allow_auto_pass
    from director.vendor_request import media_hash

    layers = evaluate_clip_layers(
        technical_ok=not errors,
        technical_notes=list(errors),
        text_notes=[feet] if feet else [],
        media_hash=media_hash(prod, rel),
        next_first_diff=nxt_diff,
        setup_changed=setup_changed,
    )
    return {
        "ok": not errors,
        "shot_id": shot_id,
        "clip": rel,
        "errors": errors,
        "warnings": warnings,
        "scene_cuts": cuts,
        "last_frame": last_rel,
        "next_first_diff": nxt_diff,
        "layers": layers,
        "visual_auto_pass": layers_allow_auto_pass(layers),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--shot", required=True)
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SCENE)
    parser.add_argument("--allow-internal-cuts", type=int, default=0)
    args = parser.parse_args()
    prod_arg = Path(args.prod).expanduser()
    prod = prod_arg if prod_arg.exists() else productions_root() / args.prod
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")
    result = check_clip(
        prod.resolve(),
        args.shot,
        episode=args.episode,
        threshold=args.threshold,
        allow_internal_cuts=args.allow_internal_cuts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
