"""Shot table v2: the design station writes filmable shots, the machine checks filmability.

One artifact (`.pipeline/shot_list.json`, schema `shot-table-v2`) carries what
InkOS puts in one table row (scale / lens / move / seconds / dialogue / in-out)
plus what the director desk always had (per-scene axis lock, continuity bible,
hardest shot, dropped shots). Everything below is deterministic: no model call.
"""

from __future__ import annotations

import re
from typing import Any, Optional

SCHEMA = "shot-table-v2"

SCALES = ("wide", "full", "medium", "close", "otc", "insert", "pov")
TIGHT_SCALES = {"close", "otc", "insert"}
ANGLES = ("eye", "high", "low")
HEIGHTS = ("standing", "chest", "low", "ground", "high", "underwater", "eye")
COVERAGE = ("master", "otc", "ots", "reverse", "reaction", "insert", "empty", "continuous", "close", "single", "pov", "follow")
DELIVERY = ("none", "post", "on_camera")
FORBIDDEN_KEYS = ("prompt", "video_prompt", "image_prompt", "motion_prompt", "asset_id", "image_file", "keyframe_file")
# Per-shot world state. Costume is a free state id that must resolve to an asset; binding is an enum so the
# machine can tell "hands behind" from "hands in front" without reading Chinese.
BINDINGS = ("none", "wrists_front", "wrists_behind", "pillar", "snared", "held")
CHAR_STATE_KEYS = ("costume", "binding", "bound_with", "carrying")
BINDING_ZH = {
    "none": "",
    "wrists_front": "双手在身前被绑",
    "wrists_behind": "双手反剪在身后被绑",
    "pillar": "被绑在柱上",
    "snared": "被绳套套住",
    "held": "被人按住",
}

DISTANT_WORDS = ("远处", "远岸", "对岸", "远景", "一行行", "一排排", "成排", "整个", "全景", "队伍", "人马", "大军", "群", "全貌", "航拍")
FORBIDDEN_MOVE_WORDS = {
    "orbit": ("环绕", "orbit", "绕拍"),
    "drone": ("航拍", "无人机", "drone"),
    "crash_zoom": ("crash zoom", "急推", "猛推"),
    "whip_pan": ("甩镜", "whip pan", "闪摇"),
}
CLAUSE_SPLIT = re.compile(r"[，；。→;,]|然后|接着|随即|再(?=[\u4e00-\u9fff])")
MOVE_INTENSITY = {"static": 0, "push": 3, "pull": 3, "pan": 3, "tilt": 3, "track": 5, "follow": 5, "handheld": 4, "crane": 6}
CHARS_PER_SEC = 4.0
LINE_PAUSE_SEC = 0.8
CLAUSE_SEC = 1.5
BASE_ACTION_SEC = 2.0


def _t(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def dialogue_seconds(lines: list[str]) -> float:
    total = 0.0
    for line in lines:
        text = re.sub(r"[\s，。！？；：、“”…—（）()!?,.]", "", _t(line))
        if not text:
            continue
        total += len(text) / CHARS_PER_SEC + LINE_PAUSE_SEC
    return round(total, 1)


def clauses_of(action: str) -> list[str]:
    return [c.strip() for c in CLAUSE_SPLIT.split(_t(action)) if c.strip()]


def needed_seconds(shot: dict) -> float:
    lines = [_t(item.get("line")) for item in (shot.get("dialogue_ref") or []) if isinstance(item, dict)]
    clauses = clauses_of(shot.get("one_action") or shot.get("action_ref") or "")
    action_sec = BASE_ACTION_SEC + CLAUSE_SEC * max(0, len(clauses) - 1)
    return round(action_sec + dialogue_seconds(lines), 1)


def writer_lines(writer: Optional[dict]) -> dict[str, list[str]]:
    """scene_id -> verbatim lines (dialogue only; narration is not a shot line)."""
    out: dict[str, list[str]] = {}
    for scene in (writer or {}).get("scenes") or []:
        sid = _t(scene.get("scene_id"))
        out[sid] = [_t(item.get("line")) for item in scene.get("dialogue") or [] if _t(item.get("line"))]
    return out


def writer_locations(writer: Optional[dict]) -> dict[str, str]:
    return {_t(s.get("scene_id")): _t(s.get("location_id")) for s in (writer or {}).get("scenes") or []}


def look_forbidden_tokens(look_text: str) -> list[str]:
    """Parse `禁止：a、b、c` lines out of LOOK.md."""
    tokens: list[str] = []
    for line in _t(look_text).splitlines():
        match = re.search(r"禁止[:：](.+)$", line)
        if not match:
            continue
        for token in re.split(r"[、,，;； ]+", match.group(1)):
            token = token.strip("。 ")
            if token:
                tokens.append(token)
    return tokens


def _scene_ids_in_order(shots: list[dict]) -> list[str]:
    seen: list[str] = []
    for shot in shots:
        sid = _t(shot.get("scene_id"))
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def cast_names(writer: Optional[dict]) -> dict[str, str]:
    """cast id -> display name, from writer.series_bible.characters."""
    out: dict[str, str] = {}
    for item in ((writer or {}).get("series_bible") or {}).get("characters") or []:
        cid = _t(item.get("id"))
        if cid:
            out[cid] = _t(item.get("name")) or cid
    return out


def bible_prop_index(bible: dict) -> dict[str, dict]:
    """asset bind id -> continuity_bible.props entry. Empty when the bible names no assets."""
    out: dict[str, dict] = {}
    for prop in bible.get("props") or []:
        if not isinstance(prop, dict):
            continue
        assets = prop.get("assets") or ([prop.get("asset")] if prop.get("asset") else [])
        for asset in assets:
            if _t(asset):
                out[_t(asset)] = prop
    return out


def prop_words(prop: dict) -> list[str]:
    words = [_t(prop.get("name"))]
    aliases = prop.get("aliases")
    if isinstance(aliases, str):
        aliases = [aliases]
    words.extend(_t(a) for a in (aliases or []))
    return [w for w in words if w]


def normalize_state(state: Any) -> Optional[dict]:
    """Shape a shot's `state` block; returns None when the shot has no state at all."""
    if not isinstance(state, dict):
        return None
    raw_chars = state.get("characters") if isinstance(state.get("characters"), dict) else {}
    characters: dict[str, dict] = {}
    for cid, raw in raw_chars.items():
        item = dict(raw) if isinstance(raw, dict) else {}
        carrying = item.get("carrying")
        if isinstance(carrying, str):
            carrying = [carrying]
        characters[_t(cid)] = {
            "costume": _t(item.get("costume")),
            "binding": _t(item.get("binding")) or "none",
            "bound_with": _t(item.get("bound_with")),
            "carrying": sorted(_t(x) for x in (carrying or []) if _t(x)),
            "in_frame": item.get("in_frame", True) is not False,
        }
    props = state.get("props")
    if isinstance(props, str):
        props = [props]
    return {
        "characters": characters,
        "props": [_t(x) for x in (props or []) if _t(x)],
        "location": _t(state.get("location")),
        "note": _t(state.get("note")),
    }


def shot_text(shot: dict) -> str:
    parts = [shot.get("shot_job"), shot.get("one_action"), shot.get("left"), shot.get("right"), shot.get("eyeline")]
    for cut in shot.get("internal_cuts") or []:
        if isinstance(cut, dict):
            parts.append(cut.get("one_action"))
    return " ".join(_t(p) for p in parts)


def state_sentence(state: Optional[dict], bible: Optional[dict] = None) -> str:
    """Fallback one-liner when the designer wrote no note: binding + bound prop, per character."""
    if not state:
        return ""
    if state.get("note"):
        return state["note"]
    index = bible_prop_index(bible or {})
    bits: list[str] = []
    for cid, item in (state.get("characters") or {}).items():
        label = BINDING_ZH.get(item.get("binding") or "none", "")
        if label:
            prop = index.get(item.get("bound_with") or "")
            name = _t(prop.get("name")) if prop else _t(item.get("bound_with"))
            bits.append(f"{cid} {label}" + (f"（{name}）" if name else ""))
    return "；".join(bits)


def validate_state_chain(data: dict, *, writer: Optional[dict] = None) -> tuple[list[str], list[str]]:
    """Walk the table in order and keep each character's costume / binding / carried props.

    A difference from the carried state must be declared in `state_changes` (e.g. `sokha.binding`).
    Props and bound/carried items must sit inside their continuity_bible scene span.
    """
    errors: list[str] = []
    warnings: list[str] = []
    shots = list(data.get("shots") or [])
    bible = data.get("continuity_bible") if isinstance(data.get("continuity_bible"), dict) else {}
    if not any(isinstance(s.get("state"), dict) for s in shots):
        warnings.append("table has no per-shot state; costume, binding and prop continuity are unchecked")
        return errors, warnings

    cast = cast_names(writer)
    prop_index = bible_prop_index(bible)
    scene_ids = _scene_ids_in_order(shots)
    scene_order = {sid: i for i, sid in enumerate([_t(s.get("scene_id")) for s in (writer or {}).get("scenes") or []] or scene_ids)}
    for sid in scene_ids:
        scene_order.setdefault(sid, len(scene_order))
    current: dict[str, dict] = {}

    def check_span(sid: str, here: int, pid: str, role: str) -> None:
        prop = prop_index.get(pid)
        if not prop:
            if prop_index:
                warnings.append(f"{sid} {role} {pid} is not an asset named in continuity_bible.props")
            return
        last_scene = _t(prop.get("last_scene"))
        first_scene = _t(prop.get("first_scene"))
        if last_scene in scene_order and here > scene_order[last_scene]:
            errors.append(f"{sid} state keeps {pid} after its last scene {last_scene}")
        if first_scene in scene_order and here < scene_order[first_scene]:
            errors.append(f"{sid} state shows {pid} before its first scene {first_scene}")

    for shot in shots:
        sid = _t(shot.get("shot_id")) or "?"
        state = normalize_state(shot.get("state"))
        if state is None:
            errors.append(f"{sid} missing state while other shots carry state")
            continue
        if not state["note"]:
            errors.append(f"{sid} state needs a note: one line the frame must obey")
        here = scene_order.get(_t(shot.get("scene_id")), -1)
        declared = {_t(x) for x in (shot.get("state_changes") or []) if _t(x)}
        seen: set[str] = set()
        for cid, item in state["characters"].items():
            if cast and cid not in cast:
                warnings.append(f"{sid} state character {cid} is not a writer cast id")
            prev = current.get(cid)
            if not item["costume"]:
                if prev:
                    item["costume"] = prev["costume"]
                else:
                    errors.append(f"{sid} {cid} first appearance needs costume")
            if item["binding"] not in BINDINGS:
                errors.append(f"{sid} {cid} binding must be one of {list(BINDINGS)}")
            if item["binding"] != "none" and not item["bound_with"]:
                errors.append(f"{sid} {cid} binding {item['binding']} needs bound_with")
            if prev:
                for key in CHAR_STATE_KEYS:
                    if item[key] != prev[key]:
                        tag = f"{cid}.{key}"
                        seen.add(tag)
                        if tag not in declared:
                            errors.append(f"{sid} {tag} changes {prev[key]!s}→{item[key]!s} without state_changes")
            for pid in item["carrying"]:
                check_span(sid, here, pid, "carried prop")
            if item["bound_with"]:
                check_span(sid, here, item["bound_with"], "binding prop")
            current[cid] = item
        for pid in state["props"]:
            check_span(sid, here, pid, "prop")
        for tag in sorted(declared - seen):
            warnings.append(f"{sid} declares state change {tag} but nothing changed")
        text = shot_text(shot)
        for cid, name in cast.items():
            if name and name in text and cid not in state["characters"]:
                warnings.append(f"{sid} mentions {name} but state.characters has no {cid}")
    return errors, warnings


def validate_shot_table(
    data: dict,
    *,
    writer: Optional[dict] = None,
    sets: Optional[dict] = None,
    profile: Optional[dict] = None,
    look_text: str = "",
    scene_scope: Optional[list[str]] = None,
    partial: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings).

    `scene_scope` limits per-scene rules to those scenes; `partial=True` means later scenes are not
    designed yet, so "evidence never claimed" is not an error yet.
    """
    errors: list[str] = []
    warnings: list[str] = []
    shots = list(data.get("shots") or [])
    profile = profile or {}
    min_sec = int(profile.get("min_shot_sec") or 1)
    max_sec = int(profile.get("max_shot_sec") or 60)
    allowed_moves = set(profile.get("allowed_moves") or MOVE_INTENSITY)
    forbidden_moves = set(profile.get("forbidden_moves") or ())
    max_cuts = int(profile.get("max_internal_cuts") or 0)
    native_dialogue = bool(profile.get("native_dialogue_audio"))
    look_tokens = look_forbidden_tokens(look_text)

    if _t(data.get("schema")) != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not shots:
        errors.append("shot table empty")
        return errors, warnings
    if data.get("visible_change_without_dialogue") != "pass":
        errors.append("visible_change_without_dialogue must be pass")

    lock = data.get("left_right_lock")
    scene_ids = _scene_ids_in_order(shots)
    if isinstance(lock, dict):
        for sid in scene_ids:
            if not _t(lock.get(sid)):
                errors.append(f"left_right_lock missing scene {sid}")
    elif not _t(lock):
        errors.append("missing left_right_lock")

    bible = data.get("continuity_bible") if isinstance(data.get("continuity_bible"), dict) else {}
    for key in ("eyeline", "wardrobe", "day_night", "props"):
        if key not in bible:
            errors.append(f"continuity_bible missing {key}")

    set_ids = {_t(s.get("id")) for s in (sets or {}).get("sets") or [] if _t(s.get("id"))}
    set_names = {_t(s.get("id")): _t(s.get("name")) for s in (sets or {}).get("sets") or [] if _t(s.get("id"))}
    scene_location = writer_locations(writer)
    lines_by_scene = writer_lines(writer)
    all_writer_lines = {line for lines in lines_by_scene.values() for line in lines}

    ids: list[str] = []
    order: dict[str, int] = {}
    used_lines: dict[str, list[str]] = {}
    prev: Optional[dict] = None
    per_scene_scales: dict[str, set] = {}
    per_scene_sides: dict[str, dict[str, str]] = {}

    for index, shot in enumerate(shots):
        sid = _t(shot.get("shot_id") or shot.get("id")) or f"#{index + 1}"
        ids.append(sid)
        order[sid] = index
        scene_id = _t(shot.get("scene_id"))
        text = _t(shot.get("shot_job")) + " " + _t(shot.get("one_action")) + " " + _t(shot.get("action_ref"))

        for key in ("scene_id", "beat", "shot_job", "coverage_type", "scale", "lens", "one_action", "in_from", "out_to"):
            if not _t(shot.get(key)):
                errors.append(f"{sid} missing {key}")
        for key in FORBIDDEN_KEYS:
            if _t(shot.get(key)):
                errors.append(f"{sid} design cannot carry {key}")

        coverage = _t(shot.get("coverage_type"))
        if coverage and coverage not in COVERAGE:
            errors.append(f"{sid} bad coverage_type {coverage}")
        scale = _t(shot.get("scale"))
        if scale and scale not in SCALES:
            errors.append(f"{sid} scale must be one of {list(SCALES)}")
        angle = _t(shot.get("angle") or "eye")
        if angle not in ANGLES:
            errors.append(f"{sid} angle must be one of {list(ANGLES)}")
        if _t(shot.get("lens")) and not re.fullmatch(r"\d{2,3}mm", _t(shot.get("lens"))):
            errors.append(f"{sid} lens must look like 35mm")

        duration = _int(shot.get("duration_sec"), 0)
        if duration <= 0:
            errors.append(f"{sid} duration_sec must be a positive integer")
        else:
            if duration > max_sec:
                errors.append(f"{sid} duration {duration}s exceeds model max {max_sec}s")
            if duration < min_sec:
                warnings.append(f"{sid} duration {duration}s below model min {min_sec}s; render at {min_sec}s and trim in cut")
            need = needed_seconds(shot)
            if need > duration + 0.05:
                errors.append(f"{sid} needs about {need}s for its action and lines but has {duration}s; split the shot or add seconds")

        clauses = clauses_of(shot.get("one_action") or "")
        if len(clauses) > 5:
            errors.append(f"{sid} one_action has {len(clauses)} clauses; one shot, one beat")

        move = _t(shot.get("move_type") or ("static" if _t(shot.get("move_needed")) in ("", "static") else ""))
        if not move:
            errors.append(f"{sid} missing move_type")
        elif move in forbidden_moves or (allowed_moves and move not in allowed_moves):
            errors.append(f"{sid} move_type {move} not allowed for {profile.get('id') or 'this model'}")
        if move and move != "static" and not _t(shot.get("move_reason")):
            errors.append(f"{sid} move needs a reason")
        blob = (text + " " + _t(shot.get("move_reason"))).lower()
        for move_key, words in FORBIDDEN_MOVE_WORDS.items():
            if move_key in forbidden_moves and any(w.lower() in blob for w in words):
                errors.append(f"{sid} text asks for {move_key} ({'/'.join(words)}), forbidden for this model")
        for token in look_tokens:
            if token and token.lower() in blob and token not in ("字幕烧进画面",):
                errors.append(f"{sid} text contains LOOK.md forbidden item {token}")

        if scale in TIGHT_SCALES and any(word in text for word in DISTANT_WORDS):
            hit = next(word for word in DISTANT_WORDS if word in text)
            errors.append(f"{sid} {scale} cannot show distant content ({hit}); use wide/full or give it a cutaway")

        cuts = shot.get("internal_cuts") or []
        if cuts and max_cuts == 0:
            errors.append(f"{sid} internal_cuts not supported by {profile.get('id') or 'this model'}")
        elif len(cuts) > max_cuts:
            errors.append(f"{sid} has {len(cuts)} internal cuts, model allows {max_cuts}")
        for cut in cuts:
            if not isinstance(cut, dict) or not _t(cut.get("scale")) or not _t(cut.get("one_action")):
                errors.append(f"{sid} internal cut needs scale and one_action")
                break
            if duration and _int(cut.get("at_sec"), -1) >= duration:
                errors.append(f"{sid} internal cut at_sec must be inside the shot")
                break

        dialogue = [item for item in (shot.get("dialogue_ref") or []) if isinstance(item, dict)]
        if len(dialogue) > 2:
            errors.append(f"{sid} carries {len(dialogue)} lines; max 2 per shot, give the rest a reverse")
        delivery = _t(shot.get("dialogue_delivery") or ("none" if not dialogue else "post"))
        if delivery not in DELIVERY:
            errors.append(f"{sid} dialogue_delivery must be one of {list(DELIVERY)}")
        if delivery == "on_camera" and not native_dialogue:
            errors.append(f"{sid} on_camera dialogue not supported by {profile.get('id') or 'this model'}; use post")
        if dialogue and delivery == "none":
            errors.append(f"{sid} has lines but dialogue_delivery=none")
        for item in dialogue:
            line = _t(item.get("line"))
            if all_writer_lines and line not in all_writer_lines:
                errors.append(f"{sid} line is not a writer line: {line[:20]}")
            used_lines.setdefault(line, []).append(sid)

        if set_ids:
            loc = _t(shot.get("location_id"))
            if loc and loc not in set_ids:
                errors.append(f"{sid} location_id {loc} not in sets.json")
            expected = scene_location.get(scene_id)
            if loc and expected and loc != expected:
                errors.append(f"{sid} location_id {loc} differs from writer scene {scene_id} ({expected})")
            others = [name for oid, name in set_names.items() if name and oid != loc and name in text]
            if loc and others:
                errors.append(f"{sid} one shot cannot visit two sets ({others[0]})")
        if re.search(r"(拖进|拖入|带进|走进|进入|押进)", text) and re.search(r"(门外|寨门|外面|门口)", text):
            warnings.append(f"{sid} moves from outside to inside in one shot; split if the model cannot hold both")

        left, right = _t(shot.get("left")), _t(shot.get("right"))
        sides = per_scene_sides.setdefault(scene_id, {})
        for token, side in ((left, "left"), (right, "right")):
            if not token or token in ("空", "—", "-", "无"):
                continue
            if sides.get(token) and sides[token] != side:
                errors.append(f"{sid} {token} flips to {side} inside scene {scene_id}; axis lock broken")
            sides.setdefault(token, side)

        if scale:
            per_scene_scales.setdefault(scene_id, set()).add(scale)
        if prev is not None and _t(prev.get("scene_id")) == scene_id:
            same = (
                _t(prev.get("scale")) == scale
                and _t(prev.get("coverage_type")) == coverage
                and _t(prev.get("left")) == left
                and _t(prev.get("right")) == right
                and coverage not in ("pov", "insert", "continuous")
            )
            if same:
                errors.append(f"{sid} repeats {_t(prev.get('shot_id'))}: same scene, scale, coverage, and sides in a row")
        prev = shot

    if len(ids) != len(set(ids)):
        errors.append("duplicate shot_id")

    scope = set(scene_scope or scene_ids)
    for scene_id in scope:
        scales = per_scene_scales.get(scene_id) or set()
        count = sum(1 for s in shots if _t(s.get("scene_id")) == scene_id)
        if count >= 3 and len(scales) < 2:
            warnings.append(f"scene {scene_id} has {count} shots but only one scale; add a tighter or wider setup")
        for line in lines_by_scene.get(scene_id) or []:
            if line not in used_lines:
                errors.append(f"scene {scene_id} line not assigned to any shot: {line[:20]}")
    for line, owners in used_lines.items():
        if len(owners) > 1:
            warnings.append(f"line appears in {len(owners)} shots ({', '.join(owners)}): {line[:16]}")

    scene_order = {sid: i for i, sid in enumerate([_t(s.get("scene_id")) for s in (writer or {}).get("scenes") or []] or scene_ids)}
    for sid in scene_ids:
        scene_order.setdefault(sid, len(scene_order))
    props = bible.get("props") if isinstance(bible.get("props"), list) else []
    for prop in props:
        if not isinstance(prop, dict):
            continue
        name = _t(prop.get("name"))
        if not name:
            continue
        last_scene = _t(prop.get("last_scene"))
        first_scene = _t(prop.get("first_scene"))
        for shot in shots:
            sid = _t(shot.get("shot_id"))
            text = _t(shot.get("shot_job")) + _t(shot.get("one_action"))
            if name not in text:
                continue
            here = scene_order.get(_t(shot.get("scene_id")), -1)
            if last_scene in scene_order and here > scene_order[last_scene]:
                errors.append(f"{sid} still shows {name} after its last scene {last_scene}")
            if first_scene in scene_order and here < scene_order[first_scene]:
                errors.append(f"{sid} shows {name} before its first scene {first_scene}")

    evidence = bible.get("evidence") if isinstance(bible.get("evidence"), list) else []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        what = _t(item.get("what"))
        if not what:
            continue
        claimants = [s for s in shots if what in [_t(e) for e in (s.get("evidence") or [])]]
        if not claimants:
            if not partial and (not scene_scope or _t(item.get("scene_id")) in scope):
                errors.append(f"evidence not claimed by any shot: {what}")
            continue
        if len(claimants) > 1:
            warnings.append(f"evidence {what} claimed by {len(claimants)} shots")
        for shot in claimants:
            if _t(shot.get("scale")) == "wide":
                errors.append(f"evidence {what} sits in wide shot {_t(shot.get('shot_id'))}; it must be readable")
            if _t(item.get("scene_id")) and _t(shot.get("scene_id")) != _t(item.get("scene_id")):
                warnings.append(f"evidence {what} planned for {_t(item.get('scene_id'))} but shown in {_t(shot.get('scene_id'))}")

    declared = data.get("total_sec")
    actual = sum(_int(s.get("duration_sec"), 0) for s in shots)
    if declared not in (None, "") and _int(declared) != actual:
        errors.append(f"total_sec {declared} != sum of shots {actual}")

    state_errors, state_warnings = validate_state_chain(data, writer=writer)
    errors.extend(state_errors)
    warnings.extend(state_warnings)
    return errors, warnings


def sanitize_shot_table(data: dict, *, writer: Optional[dict] = None) -> dict:
    """Fill derivable fields, strip forbidden keys. Never invents sides, lines, or seconds."""
    payload = dict(data or {})
    payload["schema"] = SCHEMA
    locations = writer_locations(writer)
    shots = []
    for index, raw in enumerate(payload.get("shots") or []):
        shot = dict(raw or {})
        for key in FORBIDDEN_KEYS:
            shot.pop(key, None)
        shot.pop("lens_mm", None)
        if not _t(shot.get("shot_id")) and _t(shot.get("id")):
            shot["shot_id"] = _t(shot.get("id"))
        if not _t(shot.get("shot_id")):
            shot["shot_id"] = f"SH{index + 1:03d}"
        if not _t(shot.get("location_id")) and _t(shot.get("scene_id")) in locations:
            shot["location_id"] = locations[_t(shot.get("scene_id"))]
        if shot.get("duration_sec") not in (None, ""):
            shot["duration_sec"] = _int(shot.get("duration_sec"), 0)
        move = _t(shot.get("move_type"))
        if not move:
            move = "static" if _t(shot.get("move_needed")) in ("", "static") else _t(shot.get("move_needed"))
            shot["move_type"] = move
        shot["move_needed"] = "static" if move == "static" else "move"
        if move == "static":
            shot["move_reason"] = _t(shot.get("move_reason"))
        dialogue = shot.get("dialogue_ref")
        if dialogue is None:
            dialogue = []
        if isinstance(dialogue, dict):
            dialogue = [dialogue]
        shot["dialogue_ref"] = [item if isinstance(item, dict) else {"character": "", "line": _t(item)} for item in dialogue]
        if not shot["dialogue_ref"]:
            shot["dialogue_delivery"] = "none"
        elif not _t(shot.get("dialogue_delivery")):
            shot["dialogue_delivery"] = "post"
        if not _t(shot.get("angle")):
            shot["angle"] = "eye"
        if shot.get("key_sfx") is None:
            shot["key_sfx"] = []
        if isinstance(shot.get("key_sfx"), str):
            shot["key_sfx"] = [s.strip() for s in re.split(r"[、,，;；]", shot["key_sfx"]) if s.strip()]
        if shot.get("internal_cuts") is None:
            shot["internal_cuts"] = []
        evidence = shot.get("evidence")
        if evidence is None or evidence == "":
            evidence = []
        if isinstance(evidence, str):
            evidence = [evidence]
        shot["evidence"] = [_t(e) for e in evidence if _t(e)]
        shot.setdefault("visual_turn", False)
        shot.setdefault("hardest", False)
        if not _t(shot.get("action_ref")):
            shot["action_ref"] = _t(shot.get("one_action"))
        state = normalize_state(shot.get("state"))
        if state is not None:
            shot["state"] = state
            changes = shot.get("state_changes")
            if isinstance(changes, str):
                changes = [c.strip() for c in re.split(r"[、,，;； ]+", changes) if c.strip()]
            shot["state_changes"] = [_t(c) for c in (changes or []) if _t(c)]
        shots.append(shot)
    payload["shots"] = shots
    payload["total_sec"] = sum(_int(s.get("duration_sec"), 0) for s in shots)
    payload.setdefault("dropped_shots", [])
    payload.setdefault("design_steps_done", [1, 2, 3, 4, 5, 6, 7])
    payload.setdefault("visible_change_without_dialogue", "pass")
    bible = payload.get("continuity_bible") if isinstance(payload.get("continuity_bible"), dict) else {}
    for key in ("eyeline", "wardrobe", "day_night"):
        bible.setdefault(key, "")
    if not isinstance(bible.get("props"), list):
        bible["props"] = [] if not bible.get("props") else [{"name": _t(bible.get("props"))}]
    if not isinstance(bible.get("evidence"), list):
        bible["evidence"] = []
    payload["continuity_bible"] = bible
    if not _t(payload.get("scene_id")):
        payload["scene_id"] = "EP01"
    return payload


def light_of(shot: dict, bible: dict) -> dict[str, str]:
    light = shot.get("light") if isinstance(shot.get("light"), dict) else {}
    day_night = _t(light.get("day_night"))
    if not day_night:
        dn = bible.get("day_night")
        if isinstance(dn, dict):
            day_night = _t(dn.get(_t(shot.get("scene_id"))))
        else:
            day_night = _t(dn)
    return {
        "day_night": day_night or "day",
        "key_light_dir": _t(light.get("key_dir") or light.get("key_light_dir")) or "side",
        "quality": _t(light.get("quality")) or "soft",
        "color_mood": _t(light.get("color") or light.get("color_mood")) or "",
    }


def compile_specs_from_shot_table(data: dict, *, aspect: str = "16:9") -> dict:
    """5.1 for a v2 table is a projection, not a second model pass."""
    bible = data.get("continuity_bible") if isinstance(data.get("continuity_bible"), dict) else {}
    lock = data.get("left_right_lock")
    shots = list(data.get("shots") or [])
    specs = []
    for index, shot in enumerate(shots):
        sid = _t(shot.get("shot_id"))
        lines = [_t(item.get("line")) for item in shot.get("dialogue_ref") or [] if _t(item.get("line"))]
        move = _t(shot.get("move_type") or "static")
        light = light_of(shot, bible)
        axis = lock.get(_t(shot.get("scene_id"))) if isinstance(lock, dict) else lock
        subject = _t(shot.get("left")) if _t(shot.get("left")) not in ("", "空") else (clauses_of(shot.get("one_action") or "")[:1] or [""])[0]
        specs.append({
            "shot_id": sid,
            "scene_id": _t(shot.get("scene_id")),
            "content": _t(shot.get("one_action")),
            "subject": subject,
            "action_now": _t(shot.get("one_action")),
            "shot_size": _t(shot.get("scale")),
            "angle": _t(shot.get("angle") or "eye"),
            "height": _t(shot.get("height") or "eye"),
            "focal_length": _t(shot.get("lens")),
            "aspect_ratio": _t(data.get("aspect")) or aspect,
            "move_type": move,
            "move_detail": _t(shot.get("move_detail")) or ("固定机位" if move == "static" else _t(shot.get("move_reason"))),
            "move_reason": _t(shot.get("move_reason")) or ("无叙事位移" if move == "static" else ""),
            "intensity": 0 if move == "static" else MOVE_INTENSITY.get(move, 3),
            "left": _t(shot.get("left")),
            "right": _t(shot.get("right")),
            "eyeline": _t(shot.get("eyeline")),
            "body_facing": _t(shot.get("body_facing") or shot.get("eyeline")),
            "day_night": light["day_night"],
            "key_light_dir": light["key_light_dir"],
            "quality": light["quality"],
            "color_mood": light["color_mood"],
            "duration_sec": float(_int(shot.get("duration_sec"), 0)),
            "dialogue_line": lines[0] if lines else "",
            "dialogue_lines": lines,
            "dialogue_delivery": _t(shot.get("dialogue_delivery") or ("post" if lines else "none")),
            "dialogue_start_sec": (shot.get("dialogue_start_sec") if shot.get("dialogue_start_sec") not in (None, "") else (0.6 if lines else None)),
            "key_sfx": list(shot.get("key_sfx") or []),
            "axis_side": _t(axis),
            "in_from": _t(shot.get("in_from")),
            "out_to": _t(shot.get("out_to")),
            "internal_cuts": list(shot.get("internal_cuts") or []),
            "costume_state_id": "",
            "location_state_id": _t(shot.get("location_id")),
            "state": normalize_state(shot.get("state")),
            "state_changes": list(shot.get("state_changes") or []),
        })
    return {"shot_specs": specs, "status": "draft", "origin": "compiled-from-shot-table", "schema": SCHEMA}


def table_context(prod, target_model: Optional[str] = None) -> dict:
    """Everything the validator and the renderer need from disk: writer, sets, look text, model profile."""
    from .pipeline import read_artifact
    from .production import load_json, read_text
    from .video_profiles import get_profile, resolve_target_model

    model = resolve_target_model(prod, target_model)
    return {
        "writer": read_artifact(prod, "writer.json"),
        "sets": load_json(prod, "03-storyboard/sets.json", {"sets": []}),
        "look_text": read_text(prod, "02-assets/LOOK.md"),
        "profile": get_profile(model),
    }


def _md_cell(value: Any) -> str:
    text = _t(value) if not isinstance(value, list) else "、".join(_t(v) for v in value)
    return text.replace("|", "／").replace("\n", " ") or "—"


def render_shot_table_md(data: dict, *, title: str = "", profile: Optional[dict] = None, warnings: Optional[list[str]] = None) -> str:
    profile = profile or {}
    shots = list(data.get("shots") or [])
    total = sum(_int(s.get("duration_sec"), 0) for s in shots)
    lock = data.get("left_right_lock")
    bible = data.get("continuity_bible") if isinstance(data.get("continuity_bible"), dict) else {}
    lines: list[str] = []
    lines.append(f"# 分镜表 · {title or data.get('scene_id') or '第 01 集'}")
    lines.append("")
    status = _t(data.get("status")) or "draft"
    if status == "locked":
        lines.append(f"- **状态**：locked（人已接受 {len(shots)} 镜 / {total} 秒）")
    else:
        lines.append(f"- **状态**：{status}（机器校验已过，人未锁）")
    lines.append(f"- **画幅**：{_t(data.get('aspect')) or '16:9'}")
    lines.append(f"- **视点**：{_t(data.get('whose_pov')) or '—'}")
    lines.append(f"- **目标模型**：{_t(profile.get('label') or data.get('target_model')) or '—'}")
    lines.append(f"- **总镜数**：{len(shots)}")
    lines.append(f"- **总时长**：{total} 秒（各镜相加）")
    hardest = [_t(s.get("shot_id")) for s in shots if s.get("hardest")]
    if hardest:
        lines.append(f"- **最难一颗**：{', '.join(hardest)}（先做）")
    dropped = data.get("dropped_shots") or []
    if dropped:
        lines.append(f"- **删掉的镜**：{'；'.join(_t(d) for d in dropped)}")
    if warnings:
        lines.append("- **警告**：" + "；".join(warnings))
    lines.append("")
    lines.append("## 左右锁")
    lines.append("")
    if isinstance(lock, dict):
        lines.append("| 场 | 锁 |")
        lines.append("|---|---|")
        for sid, text in lock.items():
            lines.append(f"| {_md_cell(sid)} | {_md_cell(text)} |")
    else:
        lines.append(_t(lock) or "—")
    lines.append("")
    lines.append("## 连戏圣经")
    lines.append("")
    lines.append("| 项 | 规定 |")
    lines.append("|---|---|")
    for key, label in (("eyeline", "视线"), ("wardrobe", "服装"), ("day_night", "日夜")):
        value = bible.get(key)
        if isinstance(value, dict):
            value = "；".join(f"{k} {v}" for k, v in value.items())
        lines.append(f"| {label} | {_md_cell(value)} |")
    props = bible.get("props") if isinstance(bible.get("props"), list) else []
    if props:
        cells = []
        for prop in props:
            if isinstance(prop, dict):
                span = " → ".join(x for x in (_t(prop.get("first_scene")), _t(prop.get("last_scene"))) if x)
                cells.append(f"{_t(prop.get('name'))}（{span or '全程'}）{(' ' + _t(prop.get('note'))) if _t(prop.get('note')) else ''}")
        lines.append(f"| 道具 | {_md_cell('；'.join(cells))} |")
    evidence = bible.get("evidence") if isinstance(bible.get("evidence"), list) else []
    if evidence:
        cells = []
        for item in evidence:
            if isinstance(item, dict):
                what = _t(item.get("what"))
                owners = [_t(s.get("shot_id")) for s in shots if what in [_t(e) for e in (s.get("evidence") or [])]]
                cells.append(what + " → " + ("、".join(owners) if owners else _t(item.get("scene_id")) or "未指派"))
        lines.append(f"| 证据镜 | {_md_cell('；'.join(cells))} |")
    lines.append("")
    lines.append("## 总表")
    lines.append("")
    lines.append("| 镜号 | 场 | 秒 | 覆盖 | 景别 | 焦段 | 运镜 | 左 | 右 | 这一镜干什么 | 一个动作 | 对白 | 音效 | 入 | 出 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for shot in shots:
        dialogue = " / ".join(f"{_t(d.get('character'))}：{_t(d.get('line'))}" if _t(d.get("character")) else _t(d.get("line")) for d in shot.get("dialogue_ref") or [])
        move = _t(shot.get("move_type") or "static")
        if move != "static" and _t(shot.get("move_reason")):
            move = f"{move}（{_t(shot.get('move_reason'))}）"
        cuts = shot.get("internal_cuts") or []
        job = _t(shot.get("shot_job"))
        if cuts:
            job += f"【片内切 {len(cuts)}】"
        lines.append(
            "| " + " | ".join(_md_cell(v) for v in (
                shot.get("shot_id"), shot.get("scene_id"), shot.get("duration_sec"), shot.get("coverage_type"), shot.get("scale"),
                shot.get("lens"), move, shot.get("left"), shot.get("right"), job, shot.get("one_action"), dialogue or "—",
                shot.get("key_sfx"), shot.get("in_from"), shot.get("out_to"),
            )) + " |"
        )
    lines.append("")
    lines.append("## 逐镜")
    lines.append("")
    for shot in shots:
        sid = _t(shot.get("shot_id"))
        light = light_of(shot, bible)
        lines.append(f"### {sid} · {_t(shot.get('scene_id'))} · {_t(shot.get('location_id')) or '—'} · {_int(shot.get('duration_sec'))}s")
        lines.append("")
        lines.append(f"- **节拍**：{_t(shot.get('beat'))}")
        lines.append(f"- **任务**：{_t(shot.get('shot_job'))}")
        lines.append(f"- **画面**：{_t(shot.get('one_action'))}")
        geometry = f"{_t(shot.get('scale'))}，{_t(shot.get('angle') or 'eye')}，机高 {_t(shot.get('height') or '—')}，{_t(shot.get('lens'))}"
        lines.append(f"- **几何**：{geometry}")
        move = _t(shot.get("move_type") or "static")
        lines.append(f"- **运动**：{move}" + (f"。{_t(shot.get('move_reason'))}" if _t(shot.get("move_reason")) else "。固定"))
        lines.append(f"- **调度**：左 {_t(shot.get('left')) or '—'} / 右 {_t(shot.get('right')) or '—'}；视线 {_t(shot.get('eyeline')) or '—'}")
        lines.append(f"- **光**：{light['day_night']}，{light['key_light_dir']}，{light['quality']}" + (f"，{light['color_mood']}" if light["color_mood"] else ""))
        dialogue = shot.get("dialogue_ref") or []
        if dialogue:
            spoken = " / ".join(f"{_t(d.get('character'))}：{_t(d.get('line'))}" for d in dialogue)
            lines.append(f"- **对白**：{spoken}（{_t(shot.get('dialogue_delivery')) or 'post'}）")
        if shot.get("key_sfx"):
            lines.append(f"- **声**：{'、'.join(_t(s) for s in shot.get('key_sfx') or [])}")
        for cut in shot.get("internal_cuts") or []:
            if isinstance(cut, dict):
                lines.append(f"- **片内切** @{_t(cut.get('at_sec'))}s：{_t(cut.get('scale'))} — {_t(cut.get('one_action'))}")
        lines.append(f"- **衔接**：{_t(shot.get('in_from'))} → {_t(shot.get('out_to'))}")
        state = normalize_state(shot.get("state"))
        if state is not None:
            changes = [_t(c) for c in (shot.get("state_changes") or []) if _t(c)]
            tail = f"（变：{'、'.join(changes)}）" if changes else ""
            lines.append(f"- **状态**：{state_sentence(state, bible) or '—'}{tail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
