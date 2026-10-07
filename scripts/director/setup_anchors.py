"""Camera setup identity and first-frame parent selection.

A setup is a camera placement (coverage + side + scale), not a scene.
Reverse / OTC / insert get their own anchors. Same-setup action may
continue from a verified generated video end. Planned ends and legacy
stills are visual references only. A new setup does not
inherit the previous shot's left/right composition.
"""

from __future__ import annotations

from typing import Any, Optional

from pathlib import Path


def _t(value: Any) -> str:
    return str(value or "").strip()


def setup_id_of(shot: Optional[dict]) -> str:
    shot = shot or {}
    explicit = _t(shot.get("setup_id"))
    if explicit:
        return explicit
    scene = _t(shot.get("scene_id"))
    coverage = _t(shot.get("coverage_type"))
    side = _t(shot.get("camera_side"))
    scale = _t(shot.get("scale") or shot.get("shot_size"))
    camera = _t(shot.get("camera_id"))
    return f"{scene}|{coverage}|{side}|{scale}|{camera}"


def camera_projection_changed(prev: Optional[dict], shot: Optional[dict]) -> bool:
    """True when the camera placement, not the subject, changed."""
    if not prev or not shot:
        return False
    if _t(prev.get("scene_id")) != _t(shot.get("scene_id")):
        return True
    return setup_id_of(prev) != setup_id_of(shot)


def same_setup(prev: Optional[dict], shot: Optional[dict]) -> bool:
    if not prev or not shot:
        return False
    if _t(prev.get("scene_id")) != _t(shot.get("scene_id")):
        return False
    return setup_id_of(prev) == setup_id_of(shot)


def shot_row(prod: Path, shot_id: str, episode=1) -> Optional[dict]:
    from place_codex_frame import load_shot_table_rows

    sid = _t(shot_id)
    for row in load_shot_table_rows(prod, episode):
        if _t(row.get("shot_id") or row.get("id")) == sid:
            return row
    return None


def previous_same_setup_shot(prod: Path, shot_id: str, episode=1) -> Optional[dict]:
    from place_codex_frame import load_shot_table_rows, previous_same_scene_shot

    current = shot_row(prod, shot_id, episode)
    if not current:
        return None
    prev = previous_same_scene_shot(prod, shot_id, episode)
    if prev and same_setup(prev, current):
        return prev
    # Walk further back for the last matching setup in this scene.
    rows = load_shot_table_rows(prod, episode)
    scene = _t(current.get("scene_id"))
    last = None
    for row in rows:
        sid = _t(row.get("shot_id") or row.get("id"))
        if sid == _t(shot_id):
            return last
        if _t(row.get("scene_id")) == scene and same_setup(row, current):
            last = row
    return last


def resolve_continuity_parent(prod: Path, shot_id: str, episode=1) -> Optional[str]:
    """Compatibility path API; use the info API to display role/provenance warnings."""
    return resolve_continuity_parent_info(prod, shot_id, episode).get("path")


def resolve_continuity_parent_info(prod: Path, shot_id: str, episode=1) -> dict:
    """Prefer actual video evidence, then planned still references in the same setup.

    This selects an edit canvas, not proof that the next shot's in_from agrees
    with the preceding video. Legacy filenames retain compatibility and are
    explicitly unknown rather than being relabeled as actual ends.
    """
    from director.review_state import can_use_as_parent
    from place_codex_frame import dest_rel, frame_role_info, identity_gate_of, resolve_generated_end
    from director.paths import safe_under
    from director.context import context_for

    prev = previous_same_setup_shot(prod, shot_id, episode)
    if not prev:
        return {"path": None, "frame_role": "unknown", "provenance_status": "unknown", "warnings": []}
    pid = _t(prev.get("shot_id") or prev.get("id"))
    if not pid:
        return {"path": None, "frame_role": "unknown", "provenance_status": "unknown", "warnings": []}
    actual = resolve_generated_end(prod, pid, episode)
    if actual:
        return {"path": actual, **frame_role_info(prod, actual)}
    warnings = []
    extracted = f"{context_for(prod, episode).shot_dir()}/{pid}-last.jpg"
    if safe_under(prod, extracted).exists():
        warnings.extend(frame_role_info(prod, extracted)["warnings"])
    for slot in ("end", "last", "first"):
        rel = dest_rel(pid, slot, episode, prod=prod)
        if not safe_under(prod, rel).exists() or not can_use_as_parent(identity_gate_of(prod, rel)):
            continue
        info = frame_role_info(prod, rel)
        # A stale actual frame must not silently become a planned reference.
        if info["frame_role"] == "generated_end" or info["provenance_status"] == "invalid":
            warnings.extend(info["warnings"])
            continue
        info["warnings"] = warnings + info["warnings"]
        info["warnings"].append(f"{pid}: 未采用已核实视频实际尾；此父图仅锁人物和空间，本镜仍按 in_from 设计")
        return {"path": rel, **info}
    return {"path": None, "frame_role": "unknown", "provenance_status": "unknown", "warnings": warnings}


def resolve_first_parent(prod: Path, shot_id: str, episode=1, location_id: str = "") -> tuple[str, bool]:
    """(parent_rel, allow_master). New setups re-anchor to the scene plate."""
    from director.codex_stills import scene_master_rel

    current = shot_row(prod, shot_id, episode) or {}
    hint = _t(current.get("still_parent")).replace("\\", "/").lstrip("./")
    if hint:
        return hint, True
    cont = resolve_continuity_parent(prod, shot_id, episode)
    if cont:
        return cont, False
    loc = _t(location_id) or _t(current.get("location_id"))
    if loc:
        return scene_master_rel(loc), True
    return "", True
