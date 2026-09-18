"""Director's-statement layer for the shot table.

Three things the continuity contract never carried:

* **scene cards** — per scene: the dramatic question, where it turns, the emotion
  curve, *the* shot, and the order the audience is allowed to see things in;
* **visual grammar** — episode-wide motifs (who is never seen wide first, who is
  always shot low), written as data the machine can check;
* **film-grade checks** — light continuity across a scene, scale rhythm, and a
  real "neighbour shots change one thing" diff.

Everything here is deterministic. The LLM fills the cards; this module checks the
table against them.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .shot_table import SCALES, cast_names, normalize_state

SCENE_CARD_SCHEMA = "scene-cards-v1"

SCALE_RANK: dict[str, Optional[int]] = {"wide": 0, "full": 1, "medium": 2, "otc": 3, "close": 4, "insert": 5, "pov": None}
RANK_LABEL = {0: "W", 1: "F", 2: "M", 3: "O", 4: "C", 5: "I"}
WHEN = ("always", "first_appearance", "first_shot_in_scene")
FLIPS = ("power", "information", "attention", "space", "emotion")
CARD_REQUIRED = (
    "scene_id",
    "dramatic_question",
    "turn",
    "emotion_curve",
    "the_shot",
    "reveal_order",
    "distance_strategy",
    "light_motivation",
    "silence_test",
)
MIRROR = {
    "left": "right",
    "right": "left",
    "front-left": "front-right",
    "front-right": "front-left",
    "back-left": "back-right",
    "back-right": "back-left",
}
KEY_DIR_SYNONYMS = {
    "画左": "left",
    "左侧": "left",
    "左": "left",
    "camera-left": "left",
    "frame-left": "left",
    "画右": "right",
    "右侧": "right",
    "右": "right",
    "camera-right": "right",
    "frame-right": "right",
    "顶光": "top",
    "顶": "top",
    "overhead": "top",
    "top-down": "top",
    "逆光": "back",
    "背光": "back",
    "backlight": "back",
    "正面": "front",
    "frontal": "front",
    "侧": "side",
    "侧光": "side",
}
REVERSE_COVERAGE = {"reverse", "otc", "ots", "reaction"}


def _t(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def rank_of(scale: str) -> Optional[int]:
    return SCALE_RANK.get(_t(scale))


# --- scene cards -----------------------------------------------------------------


def normalize_scene_card(card: Any) -> dict:
    item = dict(card) if isinstance(card, dict) else {}
    turn = item.get("turn") if isinstance(item.get("turn"), dict) else {"at": _t(item.get("turn")), "what_flips": ""}
    curve = item.get("emotion_curve") if isinstance(item.get("emotion_curve"), dict) else {}
    the_shot = item.get("the_shot") if isinstance(item.get("the_shot"), dict) else {"moment": _t(item.get("the_shot")), "scale": "", "why": ""}
    reveal = item.get("reveal_order")
    if isinstance(reveal, str):
        reveal = [r.strip() for r in re.split(r"[→>；;\n]", reveal) if r.strip()]
    return {
        "scene_id": _t(item.get("scene_id")),
        "dramatic_question": _t(item.get("dramatic_question")),
        "turn": {"at": _t(turn.get("at")), "what_flips": _t(turn.get("what_flips"))},
        "emotion_curve": {
            "start": _int(curve.get("start")),
            "peak": _int(curve.get("peak")),
            "end": _int(curve.get("end")),
            "peak_at": _t(curve.get("peak_at")),
        },
        "the_shot": {"moment": _t(the_shot.get("moment")), "scale": _t(the_shot.get("scale")), "why": _t(the_shot.get("why"))},
        "reveal_order": [_t(r) for r in (reveal or []) if _t(r)],
        "pov": _t(item.get("pov")),
        "distance_strategy": _t(item.get("distance_strategy")),
        "light_motivation": _t(item.get("light_motivation")),
        "color_shift": _t(item.get("color_shift")),
        "silence_test": _t(item.get("silence_test")),
        "case_cards": [_t(c) for c in (item.get("case_cards") or []) if _t(c)],
    }


def validate_scene_cards(cards: Any, scene_ids: list[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(cards, list) or not cards:
        return ["scene_cards empty"]
    seen: set[str] = set()
    for raw in cards:
        card = normalize_scene_card(raw)
        sid = card["scene_id"] or "?"
        if sid in seen:
            errors.append(f"scene card {sid} duplicated")
        seen.add(sid)
        for key in CARD_REQUIRED:
            value = card.get(key)
            if isinstance(value, dict):
                if not any(_t(v) for v in value.values()):
                    errors.append(f"scene card {sid} missing {key}")
            elif isinstance(value, list):
                if not value:
                    errors.append(f"scene card {sid} missing {key}")
            elif not _t(value):
                errors.append(f"scene card {sid} missing {key}")
        if not card["turn"]["at"]:
            errors.append(f"scene card {sid} turn.at must quote the line or action where it flips")
        if card["turn"]["what_flips"] and card["turn"]["what_flips"] not in FLIPS:
            errors.append(f"scene card {sid} turn.what_flips must be one of {list(FLIPS)}")
        curve = card["emotion_curve"]
        for key in ("start", "peak", "end"):
            value = curve.get(key)
            if value is None or value < 0 or value > 10:
                errors.append(f"scene card {sid} emotion_curve.{key} must be 0–10")
        if curve.get("peak") is not None and curve.get("start") is not None and curve["peak"] < curve["start"]:
            errors.append(f"scene card {sid} emotion peak below start; a scene must rise somewhere")
        if not card["the_shot"]["moment"]:
            errors.append(f"scene card {sid} the_shot.moment empty")
        if card["the_shot"]["scale"] and card["the_shot"]["scale"] not in SCALES:
            errors.append(f"scene card {sid} the_shot.scale must be one of {list(SCALES)}")
        if len(card["reveal_order"]) < 2:
            errors.append(f"scene card {sid} reveal_order needs at least two steps")
    for sid in scene_ids:
        if sid not in seen:
            errors.append(f"scene card missing for {sid}")
    return errors


def scene_card_for(cards: Any, scene_id: str) -> Optional[dict]:
    for raw in cards or []:
        card = normalize_scene_card(raw)
        if card["scene_id"] == _t(scene_id):
            return card
    return None


# --- visual grammar --------------------------------------------------------------


def normalize_visual_grammar(grammar: Any) -> dict:
    data = dict(grammar) if isinstance(grammar, dict) else {}
    motifs = []
    for raw in data.get("motifs") or []:
        if not isinstance(raw, dict):
            continue
        scenes = raw.get("scenes")
        if isinstance(scenes, str):
            scenes = [scenes]

        def _list(key: str) -> list[str]:
            value = raw.get(key)
            if isinstance(value, str):
                value = [value]
            return [_t(v) for v in (value or []) if _t(v)]

        motifs.append({
            "id": _t(raw.get("id")) or _t(raw.get("subject")),
            "subject": _t(raw.get("subject")),
            "rule": _t(raw.get("rule")),
            "when": _t(raw.get("when")) or "always",
            "scenes": [_t(s) for s in (scenes or []) if _t(s)],
            "until_scene": _t(raw.get("until_scene")),
            "from_scene": _t(raw.get("from_scene")),
            "scale_not": _list("scale_not"),
            "scale_in": _list("scale_in"),
            "angle": _t(raw.get("angle")),
            "height": _t(raw.get("height")),
        })
    hook = data.get("ending_hook") if isinstance(data.get("ending_hook"), dict) else {}
    hook_scales = hook.get("scale")
    if isinstance(hook_scales, str):
        hook_scales = [hook_scales]
    return {
        "motifs": motifs,
        "scale_rhythm": _t(data.get("scale_rhythm")),
        "light_motivation": _t(data.get("light_motivation")),
        "color_arc": _t(data.get("color_arc")),
        "ending_hook": {"scale": [_t(s) for s in (hook_scales or []) if _t(s)], "note": _t(hook.get("note"))},
    }


def validate_visual_grammar(grammar: Any) -> list[str]:
    errors: list[str] = []
    data = normalize_visual_grammar(grammar)
    if not data["motifs"] and not data["scale_rhythm"]:
        errors.append("visual_grammar needs at least one motif or a scale_rhythm sentence")
    for motif in data["motifs"]:
        mid = motif["id"] or "?"
        if not motif["subject"]:
            errors.append(f"motif {mid} missing subject")
        if not motif["rule"]:
            errors.append(f"motif {mid} missing rule sentence")
        if motif["when"] not in WHEN:
            errors.append(f"motif {mid} when must be one of {list(WHEN)}")
        for key in ("scale_not", "scale_in"):
            for scale in motif[key]:
                if scale not in SCALES:
                    errors.append(f"motif {mid} {key} has unknown scale {scale}")
        if motif["angle"] and motif["angle"] not in ("eye", "high", "low"):
            errors.append(f"motif {mid} angle must be eye/high/low")
        if not (motif["scale_not"] or motif["scale_in"] or motif["angle"] or motif["height"]):
            errors.append(f"motif {mid} has no checkable constraint (scale_not / scale_in / angle / height)")
    for scale in data["ending_hook"]["scale"]:
        if scale not in SCALES:
            errors.append(f"ending_hook scale {scale} unknown")
    return errors


def _subject_words(subject: str, names: dict[str, str]) -> set[str]:
    words = {subject}
    if subject in names:
        words.add(names[subject])
    for cid, name in names.items():
        if name == subject:
            words.add(cid)
    return {w for w in words if w}


def _in_frame_count(shot: dict) -> int:
    """How many characters `state.characters[cid].in_frame` keeps in the picture."""
    state = normalize_state(shot.get("state"))
    if not state:
        return 0
    return sum(1 for item in state["characters"].values() if item.get("in_frame"))


def subject_in_shot(shot: dict, subject: str, names: Optional[dict[str, str]] = None) -> bool:
    """A subject is in the shot when its state says in_frame, or its name sits in left/right/one_action."""
    names = names or {}
    words = _subject_words(_t(subject), names)
    state = normalize_state(shot.get("state"))
    if state:
        for cid, item in state["characters"].items():
            if cid in words:
                return bool(item.get("in_frame", True))
    blob = " ".join(_t(shot.get(k)) for k in ("left", "right", "one_action", "shot_job", "eyeline"))
    return any(word in blob for word in words)


def _scene_order(table: dict, writer: Optional[dict]) -> dict[str, int]:
    order: dict[str, int] = {}
    for scene in (writer or {}).get("scenes") or []:
        sid = _t(scene.get("scene_id"))
        if sid and sid not in order:
            order[sid] = len(order)
    for shot in table.get("shots") or []:
        sid = _t(shot.get("scene_id"))
        if sid and sid not in order:
            order[sid] = len(order)
    return order


def grammar_violations(table: dict, grammar: Any, writer: Optional[dict] = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    data = normalize_visual_grammar(grammar)
    shots = list(table.get("shots") or [])
    if not shots or not (data["motifs"] or data["ending_hook"]["scale"]):
        return errors, warnings
    names = cast_names(writer)
    order = _scene_order(table, writer)

    for motif in data["motifs"]:
        mid = motif["id"] or motif["subject"]
        in_scope: list[dict] = []
        for shot in shots:
            sid = _t(shot.get("scene_id"))
            if motif["scenes"] and sid not in motif["scenes"]:
                continue
            if motif["until_scene"] and order.get(sid, 0) > order.get(motif["until_scene"], 10**6):
                continue
            if motif["from_scene"] and order.get(sid, 0) < order.get(motif["from_scene"], -1):
                continue
            if subject_in_shot(shot, motif["subject"], names):
                in_scope.append(shot)
        if not in_scope:
            continue
        targets: list[dict]
        if motif["when"] == "first_appearance":
            targets = in_scope[:1]
        elif motif["when"] == "first_shot_in_scene":
            seen: set[str] = set()
            targets = []
            for shot in in_scope:
                sid = _t(shot.get("scene_id"))
                if sid not in seen:
                    seen.add(sid)
                    targets.append(shot)
        else:
            targets = in_scope
        for shot in targets:
            sid = _t(shot.get("shot_id"))
            scale = _t(shot.get("scale"))
            if motif["scale_not"] and scale in motif["scale_not"]:
                errors.append(f"{sid} breaks motif {mid}: {motif['subject']} shown {scale}, rule says {motif['rule']}")
            if motif["scale_in"] and scale and scale not in motif["scale_in"]:
                errors.append(f"{sid} breaks motif {mid}: {motif['subject']} needs {'/'.join(motif['scale_in'])}, got {scale}")
            if motif["angle"] and _t(shot.get("angle") or "eye") != motif["angle"]:
                warnings.append(f"{sid} breaks motif {mid}: {motif['subject']} must be {motif['angle']} angle")
            if motif["height"] and _t(shot.get("height")) and _t(shot.get("height")) != motif["height"]:
                warnings.append(f"{sid} motif {mid}: camera height {_t(shot.get('height'))} differs from {motif['height']}")

    hook = data["ending_hook"]["scale"]
    if hook:
        last = shots[-1]
        if _t(last.get("scale")) not in hook:
            warnings.append(f"ending hook {_t(last.get('shot_id'))} is {_t(last.get('scale'))}; grammar asks {'/'.join(hook)}")
    return errors, warnings


# --- rhythm ----------------------------------------------------------------------


def scene_rhythm(shots: list[dict]) -> list[Optional[int]]:
    return [rank_of(_t(s.get("scale"))) for s in shots]


def rhythm_string(shots: list[dict]) -> str:
    return " ".join(RANK_LABEL.get(r, "P") if r is not None else "P" for r in scene_rhythm(shots))


def _by_scene(shots: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for shot in shots:
        out.setdefault(_t(shot.get("scene_id")), []).append(shot)
    return out


def rhythm_checks(table: dict, cards: Any = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cards = cards if cards is not None else table.get("scene_cards")
    for scene_id, shots in _by_scene(list(table.get("shots") or [])).items():
        ranks = [(s, rank_of(_t(s.get("scale")))) for s in shots]
        solid = [(s, r) for s, r in ranks if r is not None and _t(s.get("scale")) not in ("insert", "pov")]
        # three in a row at the same scale (coverage may differ; the eye still sees the same size)
        run = 1
        for (prev_shot, prev_rank), (shot, rank) in zip(solid, solid[1:]):
            run = run + 1 if rank == prev_rank else 1
            if run == 3:
                warnings.append(f"scene {scene_id}: three shots in a row at {_t(shot.get('scale'))} ending {_t(shot.get('shot_id'))}; vary the size")
        if len(solid) >= 4:
            values = [r for _, r in solid]
            if max(values) - min(values) <= 1:
                warnings.append(f"scene {scene_id}: scale never moves more than one step across {len(solid)} shots (flat rhythm)")
        max_rank = max((r for _, r in solid), default=None)

        card = scene_card_for(cards, scene_id) if cards else None
        if card and card["the_shot"]["scale"]:
            want = card["the_shot"]["scale"]
            owners = [s for s in shots if _t(s.get("scale")) == want]
            if not owners:
                errors.append(f"scene {scene_id}: scene card says the shot is {want} ({card['the_shot']['moment'][:24]}), no shot at that scale")
            elif max_rank is not None and rank_of(want) is not None and rank_of(want) < max_rank and want not in ("insert",):
                warnings.append(f"scene {scene_id}: the shot ({want}) is not the tightest scale in the scene")
        if card:
            two_shot = _t(card["the_shot"]["moment"]) + " " + _t(card["the_shot"]["why"])
            if re.search(r"同框|和.+同时|背影同框", two_shot):
                want = card["the_shot"]["scale"]
                owners = [s for s in shots if want and _t(s.get("scale")) == want]
                hardest = [s for s in shots if s.get("hardest")]
                target = next((s for s in owners if s.get("hardest")), None) or (owners[0] if owners else None) or (hardest[0] if hardest else None)
                if target is not None:
                    count = _in_frame_count(target)
                    coverage = _t(target.get("coverage_type"))
                    if count < 2 or coverage == "insert":
                        errors.append(
                            f"scene {scene_id}: the_shot says 同框 but {_t(target.get('shot_id'))} "
                            f"has {count} in_frame character(s) ({coverage or 'no coverage'})"
                        )

        levels = [(s, _int(s.get("emotion_level"))) for s in shots]
        levels = [(s, v) for s, v in levels if v is not None]
        if levels:
            peak_shot, peak_val = max(levels, key=lambda item: item[1])
            peak_rank = rank_of(_t(peak_shot.get("scale")))
            if max_rank is not None and peak_rank is not None and peak_rank < max_rank - 1:
                warnings.append(f"scene {scene_id}: emotional peak {_t(peak_shot.get('shot_id'))} (level {peak_val}) sits at {_t(peak_shot.get('scale'))}, tighter shots exist")
            idx = shots.index(peak_shot)
            after = [rank_of(_t(s.get("scale"))) for s in shots[idx + 1:]]
            after = [r for r in after if r is not None]
            if after and min(after) > 2:
                warnings.append(f"scene {scene_id}: after the peak {_t(peak_shot.get('shot_id'))} nothing returns to medium or wider")
            if len(set(v for _, v in levels)) == 1 and len(levels) >= 3:
                warnings.append(f"scene {scene_id}: emotion_level flat at {peak_val} across the scene")
        for shot, value in levels:
            if value < 0 or value > 10:
                errors.append(f"{_t(shot.get('shot_id'))} emotion_level must be 0–10")
    return errors, warnings


# --- light -----------------------------------------------------------------------


def normalize_key_dir(value: Any) -> str:
    raw = _t(value).lower().replace("_", "-").replace(" ", "-")
    if not raw:
        return ""
    if raw in KEY_DIR_SYNONYMS:
        return KEY_DIR_SYNONYMS[raw]
    for word, canon in KEY_DIR_SYNONYMS.items():
        if raw == word.lower():
            return canon
    return raw


def light_checks(table: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    bible = table.get("continuity_bible") if isinstance(table.get("continuity_bible"), dict) else {}
    day_night = bible.get("day_night") if isinstance(bible.get("day_night"), dict) else {}
    for scene_id, shots in _by_scene(list(table.get("shots") or [])).items():
        anchor_dir = ""
        anchor_shot = ""
        anchor_quality = ""
        expected_dn = _t(day_night.get(scene_id)) if isinstance(day_night, dict) else ""
        for shot in shots:
            sid = _t(shot.get("shot_id"))
            light = shot.get("light") if isinstance(shot.get("light"), dict) else {}
            dn = _t(light.get("day_night"))
            if dn and expected_dn and dn != expected_dn:
                errors.append(f"{sid} light.day_night {dn} contradicts continuity_bible {expected_dn} for {scene_id}")
            key = normalize_key_dir(light.get("key_dir") or light.get("key_light_dir"))
            quality = _t(light.get("quality")).lower()
            coverage = _t(shot.get("coverage_type"))
            if key:
                if not anchor_dir:
                    anchor_dir, anchor_shot = key, sid
                elif key != anchor_dir:
                    mirrored = MIRROR.get(anchor_dir) == key
                    if mirrored and coverage in REVERSE_COVERAGE:
                        pass  # reverse / over-the-shoulder / reaction: the same lamp seen from the other side
                    elif {anchor_dir, key} == {"left", "right"}:
                        errors.append(f"{sid} key light jumps from {anchor_dir} ({anchor_shot}) to {key} inside {scene_id}; the lamp did not move")
                    elif mirrored:
                        warnings.append(f"{sid} key light mirrors {anchor_shot} ({anchor_dir}→{key}) but this is not a reverse; check the motivation")
                    else:
                        warnings.append(f"{sid} key light {key} differs from scene anchor {anchor_dir} ({anchor_shot}); write the motivation or match it")
            if quality:
                if not anchor_quality:
                    anchor_quality = quality
                elif quality != anchor_quality and quality != "mixed" and anchor_quality != "mixed":
                    warnings.append(f"{sid} light quality {quality} differs from scene anchor {anchor_quality}")
    return errors, warnings


# --- neighbour diff -----------------------------------------------------------------


def _primary_subject(shot: dict) -> str:
    left = _t(shot.get("left"))
    if left and left not in ("空", "—", "-", "无"):
        return left
    state = normalize_state(shot.get("state"))
    if state:
        for cid, item in state["characters"].items():
            if item.get("in_frame", True):
                return cid
    return ""


def neighbor_changes(prev: dict, shot: dict) -> list[str]:
    changes: list[str] = []
    if rank_of(_t(prev.get("scale"))) != rank_of(_t(shot.get("scale"))):
        changes.append(f"scale {_t(prev.get('scale'))}→{_t(shot.get('scale'))}")
    if _t(prev.get("angle") or "eye") != _t(shot.get("angle") or "eye"):
        changes.append(f"angle {_t(prev.get('angle') or 'eye')}→{_t(shot.get('angle') or 'eye')}")
    if (_t(prev.get("left")), _t(prev.get("right"))) != (_t(shot.get("left")), _t(shot.get("right"))):
        changes.append("sides")
    if _t(prev.get("move_type") or "static") != _t(shot.get("move_type") or "static"):
        changes.append(f"move {_t(prev.get('move_type') or 'static')}→{_t(shot.get('move_type') or 'static')}")
    if _primary_subject(prev) != _primary_subject(shot):
        changes.append("subject")
    return changes


def neighbor_checks(table: dict, max_changes: int = 2) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    prev: Optional[dict] = None
    for shot in list(table.get("shots") or []):
        if prev is not None and _t(prev.get("scene_id")) == _t(shot.get("scene_id")):
            if _t(shot.get("coverage_type")) not in ("insert", "pov", "empty"):
                changes = neighbor_changes(prev, shot)
                if len(changes) > max_changes:
                    warnings.append(
                        f"{_t(shot.get('shot_id'))} changes {len(changes)} things at once ({', '.join(changes)}); neighbours should change one, at most two"
                    )
        prev = shot
    return [], warnings


# --- entry point ------------------------------------------------------------------


def has_direction(table: dict) -> bool:
    return bool(table.get("scene_cards")) or bool(table.get("visual_grammar"))


def film_grade_checks(table: dict, writer: Optional[dict] = None) -> tuple[list[str], list[str]]:
    """Run every director-layer check the table has data for. Safe on tables without cards."""
    errors: list[str] = []
    warnings: list[str] = []
    shots = list(table.get("shots") or [])
    if not shots:
        return errors, warnings
    cards = table.get("scene_cards")
    grammar = table.get("visual_grammar")
    scene_ids: list[str] = []
    for shot in shots:
        sid = _t(shot.get("scene_id"))
        if sid and sid not in scene_ids:
            scene_ids.append(sid)
    if cards:
        card_errors = validate_scene_cards(cards, scene_ids)
        errors.extend(f"scene_cards: {e}" for e in card_errors if not e.startswith("scene card missing for"))
        warnings.extend(f"scene_cards: {e}" for e in card_errors if e.startswith("scene card missing for"))
    if grammar:
        errors.extend(f"visual_grammar: {e}" for e in validate_visual_grammar(grammar))
        g_err, g_warn = grammar_violations(table, grammar, writer)
        errors.extend(g_err)
        warnings.extend(g_warn)
    r_err, r_warn = rhythm_checks(table, cards)
    errors.extend(r_err)
    warnings.extend(r_warn)
    l_err, l_warn = light_checks(table)
    errors.extend(l_err)
    warnings.extend(l_warn)
    _, n_warn = neighbor_checks(table)
    warnings.extend(n_warn)
    return errors, warnings


# --- candidate metrics (deterministic, given to the critic and the compare page) ------


def candidate_metrics(shots: list[dict], card: Optional[dict] = None, warnings: Optional[list[str]] = None) -> dict:
    card = normalize_scene_card(card) if card else None
    total = sum(_int(s.get("duration_sec"), 0) or 0 for s in shots)
    ranks = [r for r in scene_rhythm(shots) if r is not None]
    moves = sum(1 for s in shots if _t(s.get("move_type") or "static") != "static")
    reactions = sum(1 for s in shots if _t(s.get("coverage_type")) == "reaction")
    dialogue_shots = sum(1 for s in shots if s.get("dialogue_ref"))
    reactions_after_dialogue = 0
    for prev, shot in zip(shots, shots[1:]):
        if prev.get("dialogue_ref") and not shot.get("dialogue_ref") and _t(shot.get("coverage_type")) in ("reaction", "close", "single"):
            reactions_after_dialogue += 1
    the_shot_landed = None
    the_shot_tightest = None
    if card and card["the_shot"]["scale"]:
        want = card["the_shot"]["scale"]
        the_shot_landed = any(_t(s.get("scale")) == want for s in shots)
        if the_shot_landed and ranks and rank_of(want) is not None:
            the_shot_tightest = rank_of(want) >= max(ranks)
    minutes = total / 60.0 if total else 0.0
    return {
        "shots": len(shots),
        "total_sec": total,
        "avg_sec": round(total / len(shots), 1) if shots else 0,
        "spm": round(len(shots) / minutes, 2) if minutes else 0,
        "asl": round(total / len(shots), 2) if shots else 0,
        "scale_curve": rhythm_string(shots),
        "scale_span": (max(ranks) - min(ranks)) if ranks else 0,
        "tightest": RANK_LABEL.get(max(ranks), "") if ranks else "",
        "static_ratio": round(1 - moves / len(shots), 2) if shots else 1.0,
        "reactions": reactions,
        "reactions_after_dialogue": reactions_after_dialogue,
        "dialogue_shots": dialogue_shots,
        "visual_turns": sum(1 for s in shots if s.get("visual_turn")),
        "hardest_marked": any(bool(s.get("hardest")) for s in shots),
        "the_shot_landed": the_shot_landed,
        "the_shot_tightest": the_shot_tightest,
        "warnings": len(warnings or []),
    }


# --- rendering -------------------------------------------------------------------


def render_scene_cards_md(cards: Any, grammar: Any = None, title: str = "") -> str:
    lines: list[str] = [f"# 场卡 · {title or '第 01 集'}", ""]
    lines.append("导演阐述层。拆镜前先读这一页；镜头表要能回答每张卡的「那一颗」和揭示顺序。")
    lines.append("")
    data = normalize_visual_grammar(grammar) if grammar else None
    if data and (data["motifs"] or data["scale_rhythm"]):
        lines.append("## 全集视觉语法")
        lines.append("")
        if data["scale_rhythm"]:
            lines.append(f"- **景别节奏**：{data['scale_rhythm']}")
        if data["light_motivation"]:
            lines.append(f"- **光的动机**：{data['light_motivation']}")
        if data["color_arc"]:
            lines.append(f"- **色彩走向**：{data['color_arc']}")
        if data["ending_hook"]["scale"]:
            lines.append(f"- **结尾钩子景别**：{'/'.join(data['ending_hook']['scale'])} {data['ending_hook']['note']}".rstrip())
        if data["motifs"]:
            lines.append("")
            lines.append("| 母题 | 对象 | 何时 | 约束 | 规则 |")
            lines.append("|---|---|---|---|---|")
            for motif in data["motifs"]:
                constraint = []
                if motif["scale_not"]:
                    constraint.append("不许 " + "/".join(motif["scale_not"]))
                if motif["scale_in"]:
                    constraint.append("只许 " + "/".join(motif["scale_in"]))
                if motif["angle"]:
                    constraint.append(motif["angle"])
                if motif["height"]:
                    constraint.append("机高 " + motif["height"])
                scope = motif["when"]
                if motif["scenes"]:
                    scope += " " + ",".join(motif["scenes"])
                if motif["until_scene"]:
                    scope += f" ≤{motif['until_scene']}"
                if motif["from_scene"]:
                    scope += f" ≥{motif['from_scene']}"
                lines.append(f"| {motif['id']} | {motif['subject']} | {scope} | {'；'.join(constraint)} | {motif['rule']} |")
        lines.append("")
    for raw in cards or []:
        card = normalize_scene_card(raw)
        curve = card["emotion_curve"]
        lines.append(f"## {card['scene_id']}")
        lines.append("")
        lines.append(f"- **戏剧问题**：{card['dramatic_question']}")
        lines.append(f"- **翻转点**：{card['turn']['at']}（{card['turn']['what_flips'] or '—'}）")
        lines.append(f"- **情绪曲线**：{curve.get('start')} → **{curve.get('peak')}** → {curve.get('end')}；最高点在 {curve.get('peak_at') or '—'}")
        lines.append(f"- **那一颗**：{card['the_shot']['moment']}（{card['the_shot']['scale'] or '景别未定'}）{('。' + card['the_shot']['why']) if card['the_shot']['why'] else ''}")
        lines.append(f"- **揭示顺序**：{' → '.join(card['reveal_order'])}")
        if card["pov"]:
            lines.append(f"- **视点**：{card['pov']}")
        lines.append(f"- **距离策略**：{card['distance_strategy']}")
        lines.append(f"- **光的动机**：{card['light_motivation']}")
        if card["color_shift"]:
            lines.append(f"- **色彩变化**：{card['color_shift']}")
        lines.append(f"- **静音测试**：{card['silence_test']}")
        if card["case_cards"]:
            lines.append(f"- **参考场型**：{'、'.join(card['case_cards'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
