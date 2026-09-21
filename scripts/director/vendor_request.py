"""Immutable vendor request used for confirm, fingerprint, and the paid submit."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

COMPILER_VERSION = "vendor-request-v1"
TASK_KINDS = ("first_frame", "first_last", "reference", "edit", "extend")
IMPLEMENTED_TASK_KINDS = set(TASK_KINDS)
GEN_MODE_TO_TASK = {
    "i2v_first": "first_frame",
    "flf2v": "first_last",
    "video_extend": "extend",
    "r2v": "reference",
    "edit": "edit",
}
TASK_TO_SEEDANCE_MODE = {
    "first_frame": "i2v",
    "first_last": "flf",
    "extend": "extend",
    "edit": "edit",
    "reference": "reference",
}


class UnknownModelError(ValueError):
    pass


class UnsupportedTaskKind(ValueError):
    pass


class DurationOutOfRange(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_hash(prod: Path, rel: str) -> str:
    rel = str(rel or "").strip().replace("\\", "/").lstrip("./")
    if not rel:
        return ""
    path = Path(prod) / rel
    if not path.is_file():
        return ""
    return sha256_file(path)


def canonical_vendor_model(profile_id: str) -> str:
    from .video_profiles import get_profile

    profile = get_profile(profile_id)
    models = list(profile.get("vendor_models") or [])
    if not models:
        raise UnknownModelError(f"profile {profile_id} has no vendor_models")
    return str(models[0])


def task_kind_for_gen_mode(gen_mode: str) -> str:
    kind = GEN_MODE_TO_TASK.get(str(gen_mode or "").strip())
    if not kind:
        raise UnsupportedTaskKind(f"unknown gen_mode: {gen_mode}")
    return kind


def require_implemented_task(kind: str) -> str:
    kind = str(kind or "").strip()
    if kind not in TASK_KINDS:
        raise UnsupportedTaskKind(f"unknown task_kind: {kind}")
    if kind not in IMPLEMENTED_TASK_KINDS:
        raise UnsupportedTaskKind(f"{kind} is not implemented; refusing to disguise it as i2v")
    return kind


def seedance_mode_for_task(kind: str) -> str:
    require_implemented_task(kind)
    return TASK_TO_SEEDANCE_MODE[kind]


def resolve_render_seconds(pkg: dict) -> int:
    """Legal render seconds. Short paper may bump to min; over-max is an error."""
    from .video_profiles import get_profile

    model = str(pkg.get("target_model") or pkg.get("profile") or "").strip()
    profile = get_profile(model) if model else get_profile(None)
    min_sec = int(pkg.get("seedance_min_sec") or profile.get("min_shot_sec") or 4)
    max_sec = int(pkg.get("seedance_max_sec") or profile.get("max_shot_sec") or 15)
    raw = pkg.get("render_duration_sec")
    if raw in (None, ""):
        raw = pkg.get("duration_sec") or min_sec
    try:
        seconds = int(round(float(raw)))
    except (TypeError, ValueError) as exc:
        raise DurationOutOfRange(f"invalid duration {raw!r}") from exc
    if seconds < min_sec:
        if pkg.get("render_duration_sec") not in (None, ""):
            raise DurationOutOfRange(
                f"render_duration_sec {seconds} below {profile.get('id')} min {min_sec}"
            )
        seconds = min_sec
    if seconds > max_sec:
        raise DurationOutOfRange(
            f"duration {seconds}s exceeds {profile.get('id')} max {max_sec}s; replan, do not clamp"
        )
    return seconds


@dataclass(frozen=True)
class VendorRequest:
    provider: str
    model: str
    profile_id: str
    task_kind: str
    ratio: str
    resolution: str
    duration_sec: int
    generate_audio: bool
    prompt: str
    shot_id: str
    first_frame: str = ""
    last_frame: str = ""
    source_video: str = ""
    refs: tuple[str, ...] = ()
    media_hashes: dict[str, str] = field(default_factory=dict)
    dialogue_language: str = ""
    speech_mode: str = ""
    compiler_version: str = COMPILER_VERSION
    production_id: str = ""
    episode_id: str = ""
    revision_id: str = ""

    def __post_init__(self) -> None:
        require_implemented_task(self.task_kind)
        if not self.model or not self.profile_id:
            raise UnknownModelError("VendorRequest requires model and profile_id")
        if int(self.duration_sec) <= 0:
            raise DurationOutOfRange("duration_sec must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "provider": self.provider,
            "model": self.model,
            "profile_id": self.profile_id,
            "task_kind": self.task_kind,
            "ratio": self.ratio,
            "resolution": self.resolution,
            "duration_sec": int(self.duration_sec),
            "generate_audio": bool(self.generate_audio),
            "prompt": self.prompt,
            "shot_id": self.shot_id,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "source_video": self.source_video,
            "refs": list(self.refs),
            "media_hashes": dict(self.media_hashes),
            "dialogue_language": self.dialogue_language,
            "speech_mode": self.speech_mode,
            "production_id": self.production_id,
            "episode_id": self.episode_id,
            "revision_id": self.revision_id,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def seedance_mode(self) -> str:
        return seedance_mode_for_task(self.task_kind)


def hash_media_rels(prod: Path, rels: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in rels:
        rel = str(rel or "").strip().replace("\\", "/").lstrip("./")
        if not rel:
            continue
        out[rel] = media_hash(prod, rel)
    return out


def vendor_request_from_package(
    prod: Path,
    pkg: dict,
    frame: Optional[dict] = None,
    *,
    episode: Any = 1,
    refs: Optional[list[str]] = None,
    resolution: str = "720p",
) -> VendorRequest:
    from .context import ProductionContext
    from .pipeline import episode_frame_dir
    from .video_profiles import get_profile

    ctx = ProductionContext.resolve(prod, episode)
    frame = frame or {}
    profile = get_profile(pkg.get("target_model") or pkg.get("profile") or pkg.get("episode_target_model"))
    profile_id = str(profile["id"])
    gen_mode = str(pkg.get("gen_mode") or "i2v_first").strip()
    kind = task_kind_for_gen_mode(gen_mode)
    require_implemented_task(kind)
    prefix = episode_frame_dir(episode)
    sid = str(pkg.get("shot_id") or "").strip()
    first = str(frame.get("first_frame_file") or pkg.get("first_frame") or f"{prefix}/{sid}.jpg").replace("\\", "/")
    last = ""
    if kind == "first_last":
        last = str(frame.get("last_frame_file") or pkg.get("last_frame") or "").replace("\\", "/")
    source_video = ""
    if kind in {"extend", "edit"}:
        source_video = str(
            pkg.get("source_video") or pkg.get("reference_video") or frame.get("source_video") or ""
        ).replace("\\", "/")
    ref_list = tuple(str(x).replace("\\", "/") for x in (refs if refs is not None else pkg.get("refs") or []) if str(x).strip())
    seconds = resolve_render_seconds({**pkg, "target_model": profile_id, "seedance_min_sec": pkg.get("seedance_min_sec") or profile.get("min_shot_sec"), "seedance_max_sec": pkg.get("seedance_max_sec") or profile.get("max_shot_sec")})
    hashes = hash_media_rels(prod, [first, last, source_video, *ref_list])
    return VendorRequest(
        provider="ark",
        model=canonical_vendor_model(profile_id),
        profile_id=profile_id,
        task_kind=kind,
        ratio=str(pkg.get("aspect_ratio") or pkg.get("ratio") or "16:9"),
        resolution=str(pkg.get("resolution") or resolution),
        duration_sec=seconds,
        generate_audio=bool(pkg.get("generate_audio", True)),
        prompt=str(pkg.get("motion_prompt") or "").strip(),
        shot_id=sid,
        first_frame=first,
        last_frame=last,
        source_video=source_video,
        refs=ref_list,
        media_hashes=hashes,
        dialogue_language=str(pkg.get("dialogue_language") or ""),
        speech_mode=str(pkg.get("speech_mode") or ""),
        production_id=ctx.production_id,
        episode_id=ctx.episode_id or f"ep{ctx.episode_no:02d}",
        revision_id=ctx.revision_id,
    )
