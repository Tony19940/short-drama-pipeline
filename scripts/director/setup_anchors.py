"""Camera setup identity and first-frame parent selection.

A setup is a camera placement (coverage + side + scale), not a scene.
Reverse / OTC / insert get their own anchors. Same-setup action may
continue from the previous approved last frame. A new setup does not
inherit the previous shot's left/right composition.
"""

from __future__ import annotations

from typing import Any, Optional

from pathlib import Path


def _t(value: Any) -> str:
    return str(value or "").strip()


REVERSE_COVERAGE = {"reverse", "otc", "ots"}


def setup_id_of(shot: Optional[dict]) -> str:
    shot = shot or {}
    explicit = _t(shot.get("setup_id"))
    if explicit:
        return explicit
    scene = _t(shot.get("scene_id"))
    coverage = _t(shot.get("coverage_type"))
    side = _t(shot.get("camera_side"))
    scale = _t(shot.get("scale") or shot.get("shot_size"))
    return f"{scene}|{coverage}|{side}|{scale}"


def camera_projection_changed(prev: Optional[dict], shot: Optional[dict]) -> bool:
    """True when the camera, not the subject, moved."""
    if not prev or not shot:
        return False
    if _t(prev.get("scene_id")) != _t(shot.get("scene_id")):
        return True
    a, b = _t(prev.get("setup_id")), _t(shot.get("setup_id"))
    if a and b and a != b:
        return True
    cov_a, cov_b = _t(prev.get("coverage_type")), _t(shot.get("coverage_type"))
    side_a, side_b = _t(prev.get("camera_side")), _t(shot.get("camera_side"))
    if cov_b in REVERSE_COVERAGE or cov_a in REVERSE_COVERAGE:
        if cov_a != cov_b or (side_a and side_b and side_a != side_b):
            return True
    if side_a and side_b and side_a != side_b:
        return True
    return False


def same_setup(prev: Optional[dict], shot: Optional[dict]) -> bool:
    if not prev or not shot:
        return False
    if _t(prev.get("scene_id")) != _t(shot.get("scene_id")):
        return False
    return not camera_projection_changed(prev, shot)


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
    """Same-setup previous last (or passing first). None when this is a new setup."""
    from director.review_state import can_use_as_parent
    from place_codex_frame import dest_rel, identity_gate_of

    prev = previous_same_setup_shot(prod, shot_id, episode)
    if not prev:
        return None
    pid = _t(prev.get("shot_id") or prev.get("id"))
    if not pid:
        return None
    last = dest_rel(pid, "last", episode)
    from director.paths import safe_under

    if safe_under(prod, last).exists() and can_use_as_parent(identity_gate_of(prod, last)):
        return last
    first = dest_rel(pid, "first", episode)
    if safe_under(prod, first).exists() and can_use_as_parent(identity_gate_of(prod, first)):
        return first
    return None


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
