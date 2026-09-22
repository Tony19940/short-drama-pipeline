"""ScenePlan lives on the writer scene. It is not a parallel planning system.

Canonical intent (goals, events, lines) stays here. Observation and accepted
realization stay on Takes / QC.
"""

from __future__ import annotations

from typing import Any, Optional


def _t(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _beat(item: Any, index: int) -> Optional[dict]:
    if isinstance(item, str) and _t(item):
        return {"beat_id": f"beat-{index + 1:02d}", "text": _t(item), "kind": "event"}
    if not isinstance(item, dict):
        return None
    text = _t(item.get("text") or item.get("event") or item.get("what"))
    if not text:
        return None
    return {
        "beat_id": _t(item.get("beat_id") or item.get("id")) or f"beat-{index + 1:02d}",
        "text": text,
        "kind": _t(item.get("kind") or item.get("type") or "event"),
        "line_id": _t(item.get("line_id")),
        "stimulus": _t(item.get("stimulus") or item.get("cue")),
    }


def scene_plan_of(scene: Optional[dict]) -> dict:
    """Normalize a scene-level plan from fields the writer already has, plus optional extras."""
    scene = scene if isinstance(scene, dict) else {}
    raw_beats = scene.get("beats") or scene.get("events") or scene.get("scene_beats") or []
    beats = []
    for index, item in enumerate(_list(raw_beats)):
        beat = _beat(item, index)
        if beat:
            beats.append(beat)
    if not beats and _t(scene.get("action")):
        beats.append({"beat_id": "beat-01", "text": _t(scene.get("action"))[:160], "kind": "event", "line_id": "", "stimulus": ""})
    dialogue = [item for item in _list(scene.get("dialogue")) if isinstance(item, dict)]
    audience = [_t(x) for x in _list(scene.get("audience_info") or scene.get("reveal_order")) if _t(x)]
    sounds = [_t(x) if not isinstance(x, dict) else _t(x.get("event") or x.get("sound")) for x in _list(scene.get("sound_events") or scene.get("key_sounds"))]
    sounds = [item for item in sounds if item]
    return {
        "scene_id": _t(scene.get("scene_id")),
        "goals": [_t(x) for x in _list(scene.get("goals") or scene.get("character_goals")) if _t(x)]
        or ([_t(scene.get("scene_job"))] if _t(scene.get("scene_job")) else []),
        "resistance": _t(scene.get("resistance") or scene.get("obstacle")),
        "turn": _t(scene.get("turn") or (scene.get("turning_point") if not isinstance(scene.get("turning_point"), dict) else scene.get("turning_point", {}).get("what"))),
        "viewpoint": _t(scene.get("viewpoint") or scene.get("whose_scene") or scene.get("pov")),
        "start_state": _t(scene.get("start_state")),
        "end_state": _t(scene.get("end_state")),
        "beats": beats,
        "audience_info": audience,
        "sound_events": sounds,
        "choices": [_t(x) for x in _list(scene.get("choices") or scene.get("directable")) if _t(x)],
        "space_ref": _t(scene.get("location_id") or scene.get("space_ref")),
        "line_ids": [_t(item.get("line_id") or item.get("id")) for item in dialogue if _t(item.get("line_id") or item.get("id"))],
    }


def set_spatial_brief(row: dict) -> dict:
    """Simplified blocking the design agent can use: cameras, marks, sight, visibility."""
    cameras = []
    for item in _list(row.get("cameras")):
        if not isinstance(item, dict):
            continue
        cameras.append({
            "id": _t(item.get("id")),
            "lens": _t(item.get("lens")),
            "label": _t(item.get("label")),
            "facing_deg": item.get("facing_deg"),
        })
    marks = []
    for item in _list(row.get("marks") or row.get("blocking")):
        if not isinstance(item, dict):
            continue
        marks.append({"id": _t(item.get("id")), "note": _t(item.get("note"))})
    return {
        "id": _t(row.get("id")),
        "name": _t(row.get("name")),
        "axis": row.get("axis"),
        "notes": _t(row.get("notes")),
        "cameras": cameras[:8],
        "marks": marks[:12],
        "eyelines": row.get("eyelines") or row.get("sightlines") or [],
        "visibility": row.get("visibility") or [],
    }


def performance_intent_of(shot: Optional[dict], scene: Optional[dict] = None) -> dict:
    """What the still / video / animatic should observe at t=0 and along the clip."""
    shot = shot if isinstance(shot, dict) else {}
    plan = scene_plan_of(scene)
    timing = shot.get("action_timing") or shot.get("performance_beats") or []
    beats = [item for item in _list(timing) if isinstance(item, dict)]
    stimulus = _t(shot.get("stimulus") or shot.get("stimulus_line"))
    if not stimulus:
        for item in _list(shot.get("dialogue_ref")):
            if isinstance(item, dict) and _t(item.get("line")):
                stimulus = _t(item.get("line"))
                break
            if isinstance(item, str) and _t(item):
                stimulus = _t(item)
                break
    return {
        "start_state": _t(shot.get("in_from") or shot.get("still_start") or plan.get("start_state")),
        "t0_phase": _t(shot.get("t0_phase") or "onset"),
        "stimulus": stimulus,
        "beats": beats,
        "cut_in": _t(shot.get("cut_in") or shot.get("in_from")),
        "cut_out": _t(shot.get("cut_out") or shot.get("out_to")),
        "beat_ids": _beat_refs(shot.get("beat_ids") if shot.get("beat_ids") is not None else shot.get("covers"), plan),
    }


def _beat_refs(raw: Any, plan: dict) -> list[str]:
    known = {str(item.get("beat_id") or "") for item in (plan.get("beats") or []) if isinstance(item, dict)}
    known.discard("")
    refs: list[str] = []
    for item in _list(raw):
        if isinstance(item, str):
            ref = _t(item)
        elif isinstance(item, dict):
            ref = _t(item.get("beat_id") or item.get("id"))
        else:
            raise ValueError("beat reference must be a string or an object with beat_id")
        if not ref:
            continue
        if known and ref not in known:
            raise ValueError(f"beat_id {ref} is not in this scene")
        if ref not in refs:
            refs.append(ref)
    return refs
