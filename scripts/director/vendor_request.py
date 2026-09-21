"""Immutable vendor request used for confirm, fingerprint, and the paid submit."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

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


def resolve_vendor_identity(raw: str) -> tuple[str, str]:
    """(capability_profile_id, vendor_model_id). An explicit catalog ID stays exact."""
    from .video_profiles import get_profile

    raw_s = str(raw or "").strip()
    profile = get_profile(raw_s or None)
    profile_id = str(profile["id"])
    models = [str(item) for item in (profile.get("vendor_models") or [])]
    if not models:
        raise UnknownModelError(f"profile {profile_id} has no vendor_models")
    for model in models:
        if raw_s == model:
            return profile_id, model
    lowered = raw_s.lower()
    for model in models:
        if lowered == model.lower():
            return profile_id, model
    return profile_id, models[0]


def canonical_vendor_model(profile_id: str) -> str:
    """Profile default vendor model. Prefer resolve_vendor_identity for an explicit ID."""
    _profile_id, model = resolve_vendor_identity(profile_id)
    return model


def submit_ratio_for(task_kind: str, model: str, ratio: str) -> str:
    """Actual ratio sent to the vendor. Seedance 2.5 hard frames require adaptive."""
    kind = str(task_kind or "").strip()
    if kind in {"extend", "edit"}:
        return "adaptive"
    blob = str(model or "")
    if ("2-5" in blob or "2.5" in blob) and kind in {"first_frame", "first_last"}:
        return "adaptive"
    return str(ratio or "16:9")


def task_needs_first_frame(kind: str) -> bool:
    return str(kind or "").strip() in {"first_frame", "first_last"}


def task_needs_last_frame(kind: str) -> bool:
    return str(kind or "").strip() == "first_last"


def task_needs_source_video(kind: str) -> bool:
    return str(kind or "").strip() in {"extend", "edit"}


def task_needs_refs(kind: str) -> bool:
    return str(kind or "").strip() == "reference"


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
    media_hashes: tuple[tuple[str, str], ...] = ()
    dialogue_language: str = ""
    speech_mode: str = ""
    compiler_version: str = COMPILER_VERSION
    production_id: str = ""
    episode_id: str = ""
    revision_id: str = ""
    submit_duration_sec: int = 0
    submit_ratio: str = ""
    watermark: bool = False
    allow_h3_fallback: bool = False

    def __post_init__(self) -> None:
        require_implemented_task(self.task_kind)
        if not self.model or not self.profile_id:
            raise UnknownModelError("VendorRequest requires model and profile_id")
        if int(self.duration_sec) <= 0:
            raise DurationOutOfRange("duration_sec must be > 0")
        hashes = self.media_hashes
        if isinstance(hashes, Mapping):
            frozen = tuple(sorted((str(key), str(value)) for key, value in hashes.items() if str(key).strip()))
            object.__setattr__(self, "media_hashes", frozen)
        elif hashes:
            object.__setattr__(
                self,
                "media_hashes",
                tuple((str(key), str(value)) for key, value in hashes),
            )
        if self.task_kind == "edit":
            if int(self.submit_duration_sec or 0) == 0:
                object.__setattr__(self, "submit_duration_sec", -1)
        elif int(self.submit_duration_sec or 0) == 0:
            object.__setattr__(self, "submit_duration_sec", int(self.duration_sec))
        if not self.submit_ratio:
            object.__setattr__(self, "submit_ratio", submit_ratio_for(self.task_kind, self.model, self.ratio))

    def media_hash_map(self) -> dict[str, str]:
        return {key: value for key, value in self.media_hashes}

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
            "submit_duration_sec": int(self.submit_duration_sec),
            "submit_ratio": self.submit_ratio,
            "generate_audio": bool(self.generate_audio),
            "watermark": bool(self.watermark),
            "allow_h3_fallback": bool(self.allow_h3_fallback),
            "prompt": self.prompt,
            "shot_id": self.shot_id,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "source_video": self.source_video,
            "refs": list(self.refs),
            "media_hashes": self.media_hash_map(),
            "dialogue_language": self.dialogue_language,
            "speech_mode": self.speech_mode,
            "production_id": self.production_id,
            "episode_id": self.episode_id,
            "revision_id": self.revision_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VendorRequest":
        raw = dict(data or {})
        hashes = raw.get("media_hashes") or ()
        if isinstance(hashes, Mapping):
            hashes = tuple(sorted((str(key), str(value)) for key, value in hashes.items() if str(key).strip()))
        return cls(
            provider=str(raw.get("provider") or "ark"),
            model=str(raw.get("model") or ""),
            profile_id=str(raw.get("profile_id") or ""),
            task_kind=str(raw.get("task_kind") or ""),
            ratio=str(raw.get("ratio") or "16:9"),
            resolution=str(raw.get("resolution") or "720p"),
            duration_sec=int(raw.get("duration_sec") or 0),
            generate_audio=bool(raw.get("generate_audio", True)),
            prompt=str(raw.get("prompt") or ""),
            shot_id=str(raw.get("shot_id") or ""),
            first_frame=str(raw.get("first_frame") or ""),
            last_frame=str(raw.get("last_frame") or ""),
            source_video=str(raw.get("source_video") or ""),
            refs=tuple(str(item) for item in (raw.get("refs") or []) if str(item).strip()),
            media_hashes=tuple(hashes),
            dialogue_language=str(raw.get("dialogue_language") or ""),
            speech_mode=str(raw.get("speech_mode") or ""),
            compiler_version=str(raw.get("compiler_version") or COMPILER_VERSION),
            production_id=str(raw.get("production_id") or ""),
            episode_id=str(raw.get("episode_id") or ""),
            revision_id=str(raw.get("revision_id") or ""),
            submit_duration_sec=int(raw.get("submit_duration_sec") or 0),
            submit_ratio=str(raw.get("submit_ratio") or ""),
            watermark=bool(raw.get("watermark", False)),
            allow_h3_fallback=bool(raw.get("allow_h3_fallback", False)),
        )

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
    raw_model = str(pkg.get("target_model") or pkg.get("profile") or pkg.get("episode_target_model") or "").strip()
    profile = get_profile(raw_model or None)
    profile_id, vendor_model = resolve_vendor_identity(raw_model or str(profile["id"]))
    gen_mode = str(pkg.get("gen_mode") or "i2v_first").strip()
    kind = task_kind_for_gen_mode(gen_mode)
    require_implemented_task(kind)
    prefix = episode_frame_dir(episode)
    sid = str(pkg.get("shot_id") or "").strip()
    first = str(frame.get("first_frame_file") or pkg.get("first_frame") or "").replace("\\", "/")
    if not first and task_needs_first_frame(kind):
        first = f"{prefix}/{sid}.jpg"
    last = ""
    if kind == "first_last":
        last = str(frame.get("last_frame_file") or pkg.get("last_frame") or "").replace("\\", "/")
    source_video = ""
    if kind in {"extend", "edit"}:
        source_video = str(
            pkg.get("source_video") or pkg.get("reference_video") or frame.get("source_video") or ""
        ).replace("\\", "/")
    raw_refs = refs if refs is not None else pkg.get("refs") or []
    ref_list = tuple(str(x).replace("\\", "/") for x in raw_refs if str(x).strip())
    seconds = resolve_render_seconds({
        **pkg,
        "target_model": profile_id,
        "seedance_min_sec": pkg.get("seedance_min_sec") or profile.get("min_shot_sec"),
        "seedance_max_sec": pkg.get("seedance_max_sec") or profile.get("max_shot_sec"),
    })
    hashes = hash_media_rels(prod, [first, last, source_video, *ref_list])
    ratio = str(pkg.get("aspect_ratio") or pkg.get("ratio") or "16:9")
    return VendorRequest(
        provider="ark",
        model=vendor_model,
        profile_id=profile_id,
        task_kind=kind,
        ratio=ratio,
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
        submit_duration_sec=-1 if kind == "edit" else seconds,
        submit_ratio=submit_ratio_for(kind, vendor_model, ratio),
        watermark=bool(pkg.get("watermark", False)),
        allow_h3_fallback=bool(pkg.get("allow_h3_fallback") or pkg.get("force_h3_fallback")),
    )
