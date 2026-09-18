"""Official EP fallback: Seedance face-block → MiniMax-H3 768p → local 1280×720.

Only InputImageSensitiveContentDetected.PrivacyInformation (and *.PrivacyInformation)
leaves Seedance. Quota, timeout, prompt 风控, payload bugs, and poll failures stay on
Seedance. CompShare is never selected. Official dest is never left at 768p.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

OFFICIAL_W = 1280
OFFICIAL_H = 720
OFFICIAL_SIZE = f"{OFFICIAL_W}x{OFFICIAL_H}"
H3_STAGING_DIR = "h3-staging"
NO_H3_KEY = "face-blocked, no H3 key"


def is_smoke_output(path: Path) -> bool:
    return "smoke" in path.as_posix().lower()


def h3_staging_path(dest: Path) -> Path:
    return dest.parent / H3_STAGING_DIR / dest.name


def clip_record_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".clip.json")


def scale_h3_cmd(src: Path, dest: Path) -> list[str]:
    """Local ffmpeg only. lanczos to 1280×720, aac stereo so concat -c copy can mix."""
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"scale={OFFICIAL_W}:{OFFICIAL_H}:flags=lanczos",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-ar",
        "44100",
        str(dest),
    ]


def scale_h3_to_official(src: Path, dest: Path) -> list[str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = scale_h3_cmd(src, dest)
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cmd


def write_clip_record(dest: Path, **fields: Any) -> dict:
    body = {
        "backend": fields.get("backend") or "minimax_h3",
        "fallback_from": fields.get("fallback_from") or "seedance",
        "scaled_to": fields.get("scaled_to") or OFFICIAL_SIZE,
        "dest": str(dest),
    }
    for key, value in fields.items():
        if key not in body and value is not None:
            body[key] = value
    path = clip_record_path(dest)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return body


def read_clip_record(dest: Path) -> dict:
    path = clip_record_path(dest)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def require_official_h3_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        raise RuntimeError(NO_H3_KEY)
    return key


def render_seedance_or_h3_fallback(
    backend: Any,
    image: Path,
    prompt: str,
    seconds: int,
    dest: Path,
    *,
    refs: list | None = None,
    mode: str = "i2v",
    last_frame: Optional[Path] = None,
    force: bool = False,
    generate_audio: bool = True,
    render_fn: Optional[Callable[..., None]] = None,
    scale_fn: Optional[Callable[[Path, Path], list[str]]] = None,
) -> dict:
    """Run Seedance. On face-block only, official H3 + local scale. Smoke dest never falls back."""
    from video_backends.seedance_ark import SeedanceFaceBlock

    if is_smoke_output(dest):
        _seedance_render(
            backend,
            image,
            prompt,
            seconds,
            dest,
            refs=refs,
            mode=mode,
            last_frame=last_frame,
            force=force,
            generate_audio=generate_audio,
        )
        return {"backend": "seedance", "dest": str(dest)}
    try:
        _seedance_render(
            backend,
            image,
            prompt,
            seconds,
            dest,
            refs=refs,
            mode=mode,
            last_frame=last_frame,
            force=force,
            generate_audio=generate_audio,
        )
        return {"backend": "seedance", "dest": str(dest)}
    except SeedanceFaceBlock as exc:
        print(f"  face-block {exc.code}; official MiniMax-H3 fallback (no CompShare)", flush=True)
        return official_h3_fallback(
            image,
            prompt,
            seconds,
            dest,
            last_frame=last_frame,
            mode=mode,
            force=force,
            render_fn=render_fn,
            scale_fn=scale_fn,
        )


def _seedance_render(
    backend: Any,
    image: Path,
    prompt: str,
    seconds: int,
    dest: Path,
    *,
    refs: list | None,
    mode: str,
    last_frame: Optional[Path],
    force: bool,
    generate_audio: bool,
) -> None:
    kwargs = {
        "refs": refs or [],
        "mode": mode,
        "last_frame": last_frame,
        "force": force,
    }
    try:
        backend.render(image, prompt, seconds, dest, generate_audio=generate_audio, **kwargs)
    except TypeError:
        backend.render(image, prompt, seconds, dest, **kwargs)


def official_h3_fallback(
    image: Path,
    prompt: str,
    seconds: int,
    dest: Path,
    *,
    last_frame: Optional[Path] = None,
    mode: str = "i2v",
    force: bool = False,
    render_fn: Optional[Callable[..., None]] = None,
    scale_fn: Optional[Callable[[Path, Path], list[str]]] = None,
) -> dict:
    """Official MiniMax-H3 only. Stage 768p, scale, then promote to dest."""
    if is_smoke_output(dest):
        raise RuntimeError("H3 fallback is official 05-shots only; smoke dest stays on Seedance")
    require_official_h3_key()
    staging = h3_staging_path(dest)
    staging.parent.mkdir(parents=True, exist_ok=True)
    if render_fn is None:
        from video_backends.minimax_h3 import MiniMaxH3

        render_fn = MiniMaxH3().render
    render_fn(
        image,
        prompt,
        seconds,
        staging,
        refs=[],
        mode=mode,
        last_frame=last_frame,
        force=force,
    )
    (scale_fn or scale_h3_to_official)(staging, dest)
    if dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        raise RuntimeError("H3 fallback scale produced an empty official clip")
    return write_clip_record(
        dest,
        backend="minimax_h3",
        fallback_from="seedance",
        scaled_to=OFFICIAL_SIZE,
        staging=str(staging),
    )
