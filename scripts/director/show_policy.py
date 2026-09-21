"""Show policy vs vendor capabilities.

ModelCapabilities is what the API actually allows. ShowPolicy is this
production's aspect, art direction, review roles, and house rules.
Director taste must not be written as if it were a vendor limit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .defaults import ASPECTS, DEFAULT_ASPECT, production_aspect

POLICY_REL = ".pipeline/show_policy.json"
ART_DIRECTIONS = ("digital_cg", "photoreal", "painterly")

# 010-gongpai locked review roles. Other shows override via show_policy.json.
GONGPAI_REVIEW_SHOTS = {
    2: {"starts": ["SH001", "SH014", "SH020"], "hardest": ["SH005", "SH013", "SH017", "SH028"]},
    3: {"starts": ["SH001", "SH009", "SH021"], "hardest": ["SH006", "SH011", "SH023"]},
    4: {"starts": ["SH001", "SH012", "SH021"], "hardest": ["SH007", "SH015", "SH024"]},
    5: {"starts": ["SH001", "SH008", "SH014", "SH020"], "hardest": ["SH004", "SH010", "SH017", "SH029"]},
}
GONGPAI_BLOCK_STILLS_FROM = 6


@dataclass(frozen=True)
class ModelCapabilities:
    profile_id: str
    vendor_models: tuple[str, ...]
    min_shot_sec: int
    max_shot_sec: int
    max_ref_images: int
    aspects: tuple[str, ...]
    task_kinds: tuple[str, ...]
    first_last_frame: bool
    native_dialogue_audio: bool
    verified: bool

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> "ModelCapabilities":
        from .vendor_request import TASK_KINDS

        kinds = tuple(profile.get("task_kinds") or TASK_KINDS)
        if not profile.get("first_last_frame"):
            kinds = tuple(k for k in kinds if k != "first_last")
        return cls(
            profile_id=str(profile.get("id") or ""),
            vendor_models=tuple(str(x) for x in (profile.get("vendor_models") or [])),
            min_shot_sec=int(profile.get("min_shot_sec") or 4),
            max_shot_sec=int(profile.get("max_shot_sec") or 15),
            max_ref_images=int(profile.get("max_ref_images") or 9),
            aspects=tuple(str(x) for x in (profile.get("aspects") or ASPECTS)),
            task_kinds=kinds,
            first_last_frame=bool(profile.get("first_last_frame")),
            native_dialogue_audio=bool(profile.get("native_dialogue_audio")),
            verified=bool(profile.get("verified")),
        )


def model_capabilities(model: Optional[str] = None) -> ModelCapabilities:
    from .video_profiles import get_profile

    return ModelCapabilities.from_profile(get_profile(model))


@dataclass(frozen=True)
class ShowPolicy:
    production_id: str
    aspect: str = DEFAULT_ASPECT
    art_direction: str = "digital_cg"
    allow_internal_cuts: bool = False
    animatic_required: bool = False
    scene_rehearsal_required: bool = False
    paper_long_is_warning: bool = True
    review_shots: dict[int, dict[str, list[str]]] = field(default_factory=dict)
    block_stills_from_episode: int = 0

    def still_style_opener(self) -> str:
        return still_style_opener(self.aspect, self.art_direction)

    def review_role(self, episode, shot_id: str) -> str:
        spec = self.review_shots.get(int(episode) if str(episode).isdigit() else 0) or {}
        sid = str(shot_id or "").strip()
        if sid in (spec.get("starts") or []):
            return "scene_start"
        if sid in (spec.get("hardest") or []):
            return "hardest"
        return "normal"


def still_style_opener(aspect: str = DEFAULT_ASPECT, art_direction: str = "digital_cg") -> str:
    aspect = aspect if aspect in ASPECTS or ":" in str(aspect) else DEFAULT_ASPECT
    direction = art_direction if art_direction in ART_DIRECTIONS else "digital_cg"
    if direction == "photoreal":
        return f"电影写实静帧，{aspect}。"
    if direction == "painterly":
        return f"绘画静帧，{aspect}，有体积和绘画颗粒。"
    return f"数字电影 CG 静帧，{aspect}，非真人、非 photoreal、非 real person。"


def still_style_close(art_direction: str = "digital_cg") -> str:
    if art_direction == "photoreal":
        return "电影感写实静帧，皮肤有纹理，保留毛孔。"
    if art_direction == "painterly":
        return "绘画静帧，有体积和绘画颗粒，不是照片，不是动漫。"
    return "数字电影感绘画静帧，有体积和绘画颗粒，不是照片，不是动漫。皮肤有纹理，保留毛孔，非磨皮塑料脸。"


def _art_from_text(text: str) -> str:
    """Only an explicit 艺术方向 / 画风 line changes the default CG lock."""
    for line in str(text or "").splitlines():
        if "艺术方向" not in line and "画风" not in line and "art_direction" not in line.lower():
            continue
        low = line.lower()
        if "非 photoreal" in low or "非写实" in line or "非真人" in line:
            return "digital_cg"
        if "photoreal" in low or "写实" in line:
            return "photoreal"
        if "绘画" in line or "painterly" in low:
            return "painterly"
    return "digital_cg"


def load_show_policy(prod: Optional[Path] = None) -> ShowPolicy:
    prod_path = Path(prod) if prod is not None else None
    production_id = prod_path.name if prod_path is not None else ""
    aspect = production_aspect(prod_path)
    art = "digital_cg"
    review: dict[int, dict[str, list[str]]] = {}
    block = 0
    animatic_required = False
    scene_rehearsal_required = False
    allow_cuts = False
    if production_id == "010-gongpai":
        review = {int(k): dict(v) for k, v in GONGPAI_REVIEW_SHOTS.items()}
        block = GONGPAI_BLOCK_STILLS_FROM
    if prod_path is not None:
        confirm = prod_path / "01-bible" / "confirm.md"
        if confirm.is_file():
            try:
                text = confirm.read_text(encoding="utf-8")
            except OSError:
                text = ""
            art = _art_from_text(text)
        raw = prod_path / POLICY_REL
        if raw.is_file():
            try:
                data = json.loads(raw.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            if isinstance(data, dict):
                if data.get("aspect") in ASPECTS:
                    aspect = str(data["aspect"])
                if data.get("art_direction") in ART_DIRECTIONS:
                    art = str(data["art_direction"])
                if "animatic_required" in data:
                    animatic_required = bool(data["animatic_required"])
                if "scene_rehearsal_required" in data:
                    scene_rehearsal_required = bool(data["scene_rehearsal_required"])
                    animatic_required = animatic_required or scene_rehearsal_required
                if "allow_internal_cuts" in data:
                    allow_cuts = bool(data["allow_internal_cuts"])
                if data.get("block_stills_from_episode"):
                    block = int(data["block_stills_from_episode"])
                stored = data.get("review_shots") or {}
                if isinstance(stored, dict):
                    parsed: dict[int, dict[str, list[str]]] = {}
                    for key, value in stored.items():
                        try:
                            parsed[int(key)] = {
                                "starts": [str(x) for x in (value or {}).get("starts") or []],
                                "hardest": [str(x) for x in (value or {}).get("hardest") or []],
                            }
                        except (TypeError, ValueError):
                            continue
                    if parsed:
                        review = parsed
    return ShowPolicy(
        production_id=production_id,
        aspect=aspect,
        art_direction=art,
        allow_internal_cuts=allow_cuts,
        animatic_required=animatic_required,
        scene_rehearsal_required=scene_rehearsal_required,
        review_shots=review,
        block_stills_from_episode=block,
    )
