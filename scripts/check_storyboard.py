#!/usr/bin/env python3
"""Gate S+C2: stage + coverage + shot contract. No video until this passes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import re

REQUIRED = (
    "id",
    "seconds",
    "tier",
    "characters",
    "scene",
    "frame",
    "prompt",
    "new_info",
    "from",
    "cut",
    "scale",
)
SHORTDRAMA_EXTRA = (
    "facing",
    "expression",
    "blocking",
    "line",
    "line_kind",
    "caption",
    "setup",
    "move",
    "derived_from",
    "lens",
    "axis",
    "camera",
    "action",
    "look",
    "start",
    "video_prompt",
    "negatives",
)
LINE_KIND_LABELS = {
    "dialogue": "口述台词",
    "inner": "心里台词",
    "narration": "旁白",
    "intro": "出场简介",
    "sms": "短信/字卡",
    "reaction": "无台词反应",
}
LINE_KINDS = set(LINE_KIND_LABELS)
LINE_KIND_ALIASES = {
    "inner_voice": "inner",
    "character_intro": "intro",
}
OPTIONAL_DIRECTOR_FIELDS = (
    "story_function",
    "end",
    "camera_path",
    "camera_speed",
    "landing",
    "performance",
    "sound_intent",
)
INTRO_WINDOW = 12
MAX_LINE_CHARS = {
    "dialogue": 36,
    "inner": 28,
    "narration": 32,
    "intro": 22,
    "sms": 24,
    "reaction": 16,
}
SCALES = {"wide", "full", "med", "close", "insert"}
CUTS = {"continue", "hard"}
FACINGS = {"camera", "down", "left", "right", "away", "scene"}
SETUPS = {"master", "close", "ots", "insert", "single"}
MOVES = {"static", "push", "pull", "pan", "track"}
AXES = {"left", "right", "center"}
LENS_RE = re.compile(r"^\d{2,3}mm$")
HAN = re.compile(r"[\u3400-\u9fff]")
TEMPLATE_ACTION = re.compile(r"one body beat", re.I)
MARKS_TEMPLATE = re.compile(r"\bon\s+\S+\s+marks\b", re.I)
MOVE_TERMS = {
    "static": (
        "static",
        "locked off",
        "locked-off",
        "locked camera",
        "hold still",
        "fixed",
        "no camera move",
        "handheld breath",
        "faint handheld",
    ),
    "push": ("push in", "push-in", "slow push", "dolly in"),
    "pull": ("pull out", "pull-out", "slow pull", "dolly out"),
    "pan": ("pan left", "pan right", "pan "),
    "track": ("track", "tracking", "lateral dolly"),
}
SETUP_TERMS = {
    "master": ("master", "establishing", "room geography", "full of the room"),
    "close": ("close-up", "close up", "closeup", "tight on"),
    "ots": ("over-the-shoulder", "over the shoulder", "ots"),
    "insert": ("insert", "detail shot"),
    "single": ("single", "clean single"),
}
SCALE_TERMS = {
    "wide": ("wide shot", "wideshot", "wide "),
    "full": ("full shot", "full-body", "full body"),
    "med": ("medium", "med shot", "waist-up", "waist up"),
    "close": ("close-up", "close up", "closeup", "tight on"),
    "insert": ("insert", "insert shot", "detail"),
}
ORBIT_TERMS = (
    "orbit",
    "circle around",
    "around the subject",
    "crosses the 180",
    "crossing the 180",
    "break the 180",
    "crash zoom",
    "whip pan",
)
STATIC_FORBIDDEN = ORBIT_TERMS + ("fast push", "rapid push", "quick push", "fast pan")


def normalize_line_kind(value: str) -> str:
    raw = str(value or "").strip()
    return LINE_KIND_ALIASES.get(raw, raw)


def fail(msg: str) -> None:
    raise SystemExit("Gate C2 blocked: " + msg)


def _norm(text: str) -> str:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    drop = {chr(c) for c in (34, 39, 96, 46, 44, 33, 63, 59, 58, 40, 41, 91, 93, 123, 125)}
    return "".join(ch for ch in cleaned if ch not in drop).lower()

def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    blob = text.lower()
    return any(term in blob for term in terms)


def _has_forbidden(text: str, terms: tuple[str, ...]) -> bool:
    blob = " " + text.lower() + " "
    for term in terms:
        start = 0
        while True:
            idx = blob.find(term, start)
            if idx < 0:
                break
            prefix = blob[max(0, idx - 8):idx]
            if not re.search(r"\bno\s+$|\bnot\s+$|\bwithout\s+$", prefix):
                return True
            start = idx + len(term)
    return False


def check_director_fields(shot: dict) -> None:
    sid = shot.get("id", "?")
    lens = str(shot.get("lens") or "").strip()
    if not LENS_RE.match(lens):
        fail(f"{sid} lens must look like 35mm / 50mm / 85mm")
    axis = shot.get("axis")
    if axis not in AXES:
        fail(f"{sid} axis must be {sorted(AXES)}")
    camera = str(shot.get("camera") or "").strip()
    action = str(shot.get("action") or "").strip()
    look = str(shot.get("look") or "").strip()
    video_prompt = str(shot.get("video_prompt") or "").strip()
    negatives = str(shot.get("negatives") or "").strip()
    if len(camera) < 8:
        fail(f"{sid} camera must describe one move")
    if len(action) < 8:
        fail(f"{sid} action must be the one body beat in these seconds")
    if len(look) < 8:
        fail(f"{sid} look must lock light, background, and marks")
    if len(video_prompt) < 80:
        fail(f"{sid} video_prompt is too thin to direct a video model")
    if len(negatives) < 8:
        fail(f"{sid} negatives empty")
    new_info = str(shot.get("new_info") or "").strip()
    prompt = str(shot.get("prompt") or "").strip()
    if action.lower() == new_info.lower():
        fail(f"{sid} action and new_info are the same sentence")
    if action.lower() == prompt.lower() or video_prompt.lower() == prompt.lower():
        fail(f"{sid} video_prompt/action must not copy the short prompt")
    start = str(shot.get("start") or "").strip()
    for field, value in (("camera", camera), ("action", action), ("look", look), ("video_prompt", video_prompt), ("start", start)):
        if HAN.search(value):
            fail(f"{sid} {field} must be English; Chinese stays in line/caption/new_info")
    if TEMPLATE_ACTION.search(action):
        fail(f"{sid} action is still a one-body-beat template")
    if len(start) < 12:
        fail(f"{sid} start must say who is where at second 0")
    if MARKS_TEMPLATE.search(start):
        fail(f"{sid} start is still an on-marks template")
    if _norm(start) == _norm(action):
        fail(f"{sid} start must not copy action; start is second 0, action is the motion")
    if _norm(start) == _norm(new_info):
        fail(f"{sid} start must not copy new_info")
    loc_neg = ("location change", "restaurant", "street cutaway")
    if any(term in negatives.lower() for term in loc_neg) or "stay inside the same room" in video_prompt.lower():
        if "stay inside the same room" not in video_prompt.lower() and "same room" not in video_prompt.lower():
            fail(f"{sid} video_prompt must lock the same room for the whole clip")
        if not any(term in negatives.lower() for term in loc_neg):
            fail(f"{sid} negatives must forbid location change")
    line = str(shot.get("line") or "").strip()
    caption = str(shot.get("caption") or "").strip()
    prompt_norm = _norm(video_prompt)
    for label, text in (("line", line), ("caption", caption)):
        if len(_norm(text)) >= 6 and _norm(text) in prompt_norm:
            fail(f"{sid} {label} leaked into video_prompt; dialogue stays in line/caption")
    move = shot.get("move")
    setup = shot.get("setup")
    scale = shot.get("scale")
    camera_blob = f"{camera}\n{video_prompt}"
    if _has_forbidden(camera_blob, ORBIT_TERMS):
        fail(f"{sid} camera/video_prompt crosses the line or orbits")
    if move == "static" and _has_forbidden(camera_blob, STATIC_FORBIDDEN):
        fail(f"{sid} static camera cannot push/pan/orbit")
    if move in MOVE_TERMS and not _has_any(camera_blob, MOVE_TERMS[move]):
        fail(f"{sid} camera/video_prompt missing {move} language")
    setup_ok = _has_any(video_prompt, SETUP_TERMS.get(setup, ()))
    scale_ok = _has_any(video_prompt, SCALE_TERMS.get(scale, ()))
    if not (setup_ok or scale_ok):
        fail(f"{sid} video_prompt must name the setup or scale")


def check_end_frame(prod: Path, shot: dict) -> None:
    rel = str(shot.get("end_frame") or "").strip()
    if not rel:
        return
    sid = shot.get("id", "?")
    name = Path(rel).name.lower()
    frame_rel = str(shot.get("frame") or f"04-frames/{sid}.jpg")
    if name.endswith("-last.jpg"):
        fail(f"{sid} end_frame cannot be a generated last.jpg; design a still such as 04-frames/{sid}-end.jpg")
    if Path(rel).as_posix() == Path(frame_rel).as_posix():
        fail(f"{sid} end_frame cannot equal this shot's first frame")
    path = prod / rel
    if not path.exists() or path.stat().st_size <= 0:
        fail(f"{sid} end_frame missing: {rel}")


def check_start_sequence(shot: dict, prev: dict | None, hard: bool = False) -> None:
    if not prev:
        return
    same_scene = (shot.get("scene") or "") == (prev.get("scene") or "")
    if shot.get("cut") == "continue" and same_scene:
        start = str(shot.get("start") or "").strip()
        prev_start = str(prev.get("start") or "").strip()
        if prev_start and _norm(start) == _norm(prev_start):
            fail(
                f"{shot.get('id', '?')} continue start must move on from {prev.get('id')}; "
                "do not reuse the previous stance"
            )
        if hard and not (
            "already" in start.lower()
            or "mid-action" in start.lower()
            or "halfway" in start.lower()
            or "lifting" in start.lower()
            or "turning" in start.lower()
        ):
            fail(f"{shot.get('id', '?')} start is a rest pose; draw mid-action")


def _action_tokens(action: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", action or "")
    skip = {
        "then", "hold", "still", "does", "not", "with", "from", "into", "onto",
        "that", "this", "they", "them", "have", "been", "after", "before",
        "both", "once", "only", "keep", "keeps", "already", "start", "perform",
    }
    out = []
    for word in words:
        low = word.lower()
        if low in skip or low in out:
            continue
        out.append(low)
        if len(out) >= 4:
            break
    return out


def prompt_matches_action(shot: dict) -> bool:
    tokens = _action_tokens(str(shot.get("action") or ""))
    blob = str(shot.get("video_prompt") or "").lower()
    if len(tokens) < 2:
        return bool(tokens) and tokens[0] in blob
    return sum(1 for token in tokens if token in blob) >= 2


def check_scene_rig(data: dict, shots: list[dict], hard: bool) -> list[str]:
    warnings: list[str] = []

    def emit(message: str) -> None:
        if hard:
            fail(message)
        warnings.append(message)

    people = [s for s in shots if s.get("setup") != "insert"]
    static = [s for s in people if s.get("move") == "static"]
    if people and len(static) * 2 > len(people):
        emit(f"people shots are mostly static ({len(static)}/{len(people)}); keep static under half")
    by_scene: dict[str, list[dict]] = {}
    for shot in shots:
        by_scene.setdefault(str(shot.get("scene") or ""), []).append(shot)
    for scene, group in by_scene.items():
        rigs = {str(s.get("rig_id") or s.get("setup")) for s in group if s.get("setup") != "insert"}
        if len(group) >= 4 and len(rigs) > 3:
            emit(f"{scene}: {len(rigs)} rigs for {len(group)} shots; keep 2-3 cameras")
        if data.get("directing") == "scene-rig-v1":
            missing = [s.get("id") for s in group if not s.get("rig_id")]
            if missing:
                emit(f"{scene}: shots missing rig_id: {', '.join(str(x) for x in missing)}")
    spoken = [s for s in shots if s.get("line_kind") in {"dialogue", "inner"}]
    if spoken:
        secs = [int(s.get("seconds") or 0) for s in spoken]
        if secs and len(set(secs)) == 1 and secs[0] >= 5:
            emit("spoken shots are all the same length; vary 2-5s from line length")
        speeds = {str(s.get("camera_speed") or "") for s in shots if s.get("move") != "static"}
        if speeds == {"slow"}:
            emit("moving shots are all slow; vary camera_speed")
        if not any(str(s.get("line_kind") or "") == "reaction" for s in shots):
            emit("no silent reaction shot after spoken lines")
    for shot in shots:
        sid = shot.get("id", "?")
        if not prompt_matches_action(shot):
            emit(f"{sid} video_prompt must contain this shot's action")
        kind = str(shot.get("line_kind") or "")
        sec = int(shot.get("seconds") or 0)
        if kind in {"dialogue", "inner"} and sec > 5:
            emit(f"{sid} {kind} is {sec}s; keep spoken/inner shots at 2-5s")
        if kind == "reaction" and sec != 2:
            emit(f"{sid} reaction must be 2s")
    return warnings


def load_sets(prod: Path) -> dict[str, dict]:
    path = prod / "03-storyboard" / "sets.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {s["id"]: s for s in (data.get("sets") or []) if s.get("id")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    args = p.parse_args()
    prod = Path(args.prod).resolve()
    path = prod / "03-storyboard" / "shots.json"
    beats = prod / "03-storyboard" / "beats.md"
    blueprint = prod / "01-bible" / "blueprint.md"
    confirm = prod / "01-bible" / "confirm.md"
    coverage = prod / "03-storyboard" / "coverage.md"
    if not path.exists():
        fail(f"missing {path}")
    if not beats.exists():
        fail("missing 03-storyboard/beats.md (Gate C1). Write the beat clock before shots.")

    data = json.loads(path.read_text())
    shots = data.get("shots") or []
    kind = data.get("kind") or "shortdrama"
    if not shots:
        fail("no shots")
    if kind == "shortdrama" and not blueprint.exists():
        fail("missing 01-bible/blueprint.md")
    if kind == "shortdrama" and not confirm.exists():
        fail("missing 01-bible/confirm.md (style / aspect / narration before images)")
    if kind == "shortdrama" and not coverage.exists():
        fail("missing 03-storyboard/coverage.md (coverage before shot list)")

    sets = load_sets(prod)
    if kind == "shortdrama":
        if not sets:
            fail("missing 03-storyboard/sets.json (Gate S). Stage before shots.")
        for sid, st in sets.items():
            blocking = prod / st.get("blocking", f"02-assets/scenes/{sid}/blocking.jpg")
            master = prod / st.get("master", f"02-assets/scenes/{sid}/master.jpg")
            if not master.exists():
                fail(f"set {sid}: missing scene master {master}")
            if not blocking.exists():
                fail(f"set {sid}: missing blocking.jpg — run scripts/render_blocking.py")
            if not st.get("marks"):
                fail(f"set {sid}: marks empty")

    ids: list[str] = []
    infos: list[str] = []
    total = 0
    h3 = 0
    setups_by_scene: dict[str, set[str]] = {}
    first_of_scene: dict[str, str] = {}
    warnings: list[str] = []
    hard = str(data.get("directing") or "") == "scene-rig-v1"
    for i, s in enumerate(shots):
        missing = [k for k in REQUIRED if k not in s]
        if kind == "shortdrama":
            missing += [k for k in SHORTDRAMA_EXTRA if k not in s]
        if missing:
            fail(f"{s.get('id', i)} missing fields: {', '.join(missing)}")
        sid = s["id"]
        ids.append(sid)
        sec = int(s["seconds"])
        total += sec
        if s.get("tier") == "h3":
            h3 += 1
        min_sec = 2
        if sec < min_sec or sec > 15:
            fail(f"{sid} duration {sec} not in {min_sec}–15")
        if s["cut"] not in CUTS:
            fail(f"{sid} cut must be continue|hard")
        if s["scale"] not in SCALES:
            fail(f"{sid} scale must be {sorted(SCALES)}")
        info = str(s["new_info"]).strip().lower()
        if not info:
            fail(f"{sid} new_info empty")
        if info in infos:
            fail(f"{sid} new_info repeats an earlier shot")
        infos.append(info)

        scene = s.get("scene") or ""
        prev = shots[i - 1] if i else None
        if kind == "shortdrama":
            if scene not in sets:
                fail(f"{sid} scene {scene!r} not in sets.json")
            if s.get("setup") not in SETUPS:
                fail(f"{sid} setup must be {sorted(SETUPS)}")
            if s.get("move") not in MOVES:
                fail(f"{sid} move must be {sorted(MOVES)}")
            if s.get("facing") not in FACINGS:
                fail(f"{sid} facing must be {sorted(FACINGS)}")
            if not str(s.get("expression") or "").strip():
                fail(f"{sid} expression empty")
            if not str(s.get("blocking") or "").strip():
                fail(f"{sid} blocking empty")
            line_kind = normalize_line_kind(s.get("line_kind"))
            if line_kind not in LINE_KINDS:
                fail(f"{sid} line_kind must be {sorted(LINE_KINDS)}")
            if line_kind != "reaction" and not str(s.get("line") or "").strip():
                fail(f"{sid} line empty")
            if line_kind != "reaction" and not str(s.get("caption") or "").strip():
                fail(f"{sid} caption empty")
            speaker = str(s.get("speaker") or "").strip()
            line = str(s.get("line") or "").strip()
            if line_kind in {"narration", "intro", "sms", "reaction"} and speaker:
                fail(f"{sid} {line_kind} should not name an on-screen speaker")
            if line_kind in {"dialogue", "inner"} and speaker:
                people = [str(x) for x in (s.get("characters") or [])]
                if people and speaker not in people and speaker not in {"vo", "offscreen"}:
                    fail(f"{sid} speaker {speaker!r} is not on this shot")
            limit = MAX_LINE_CHARS.get(line_kind, 24)
            if len(line) > limit:
                fail(f"{sid} line too long for {line_kind} (>{limit} chars); split across shots")
            if line_kind == "intro":
                start = sum(int(x.get("seconds") or 0) for x in shots[:i])
                if start >= INTRO_WINDOW:
                    fail(f"{sid} intro must land in the first {INTRO_WINDOW}s")
                if i > 0 and any(normalize_line_kind(x.get("line_kind")) == "intro" for x in shots[:i]):
                    fail(f"{sid} only one intro per episode")
            missing_optional = [k for k in OPTIONAL_DIRECTOR_FIELDS if not str(s.get(k) or "").strip()]
            if missing_optional:
                warnings.append(f"{sid} missing optional {', '.join(missing_optional)}")
            check_director_fields(s)
            check_start_sequence(s, prev, hard=hard)
            check_end_frame(prod, s)
            setups_by_scene.setdefault(scene, set()).add(s["setup"])
            if scene not in first_of_scene:
                first_of_scene[scene] = sid
                want = f"{scene}.blocking"
                if s.get("derived_from") != want:
                    fail(f"{sid} first shot of {scene} derived_from must be {want}")
            else:
                if s["cut"] == "continue" and s.get("derived_from") != s.get("from"):
                    fail(f"{sid} continue derived_from must equal from ({s.get('from')})")

        if i == 0:
            if s["from"] not in (None, "", "null"):
                fail(f"{sid} opening shot from must be null")
        elif s["cut"] == "continue":
            skip = shots[i - 2]["id"] if i >= 2 and prev.get("scale") == "insert" else None
            allowed_from = [prev["id"]] + ([skip] if skip else [])
            if s["from"] not in allowed_from:
                fail(f"{sid} continue.from must be {' or '.join(allowed_from)}")
            anchor = prev if s["from"] == prev["id"] else shots[i - 2]
            same_place = (s.get("scene") or "") == (anchor.get("scene") or "")
            same_people = list(s.get("characters") or []) == list(anchor.get("characters") or [])
            if same_place and same_people and s["scale"] == anchor["scale"]:
                fail(f"{sid} repeats {anchor['id']}: same scene, people, scale")
        elif s["cut"] == "hard":
            if not (s.get("scene") and prev.get("scene") and s["scene"] != prev["scene"]):
                fail(f"{sid} hard cut only when scene changes")

        if prev and kind == "shortdrama":
            overlap = set(s.get("characters") or []) & set(prev.get("characters") or [])
            if overlap and s["scale"] == prev["scale"] and s.get("facing") == prev.get("facing"):
                fail(
                    f"{sid} same scale+facing as {prev['id']} with {sorted(overlap)}"
                )
            same_scene = (s.get("scene") or "") == (prev.get("scene") or "")
            overlap = set(s.get("characters") or []) & set(prev.get("characters") or [])
            if same_scene and s.get("cut") == "continue" and overlap:
                prev_axis = prev.get("axis")
                axis = s.get("axis")
                if prev_axis in AXES and axis in AXES and {prev_axis, axis} == {"left", "right"}:
                    fail(
                        f"{sid} jumps the 180 axis from {prev['id']} "
                        f"({prev_axis} -> {axis}) while {sorted(overlap)} stay in frame"
                    )

        frame = prod / s["frame"]
        if not frame.exists():
            print(f"warn {sid}: frame not generated yet {frame}", file=sys.stderr)

    if h3 > 3:
        fail(f"{h3} h3 shots, cap 3")
    if kind == "shortdrama" and int(shots[0]["seconds"]) >= 6 and shots[0]["characters"] == []:
        fail("shortdrama cannot open on an empty establishing shot of 6s+")
    if kind == "shortdrama" and shots[0].get("facing") == "camera" and shots[0]["scale"] in ("full", "wide"):
        fail("shortdrama cannot open on a full-body posed portrait facing camera")
    if kind == "shortdrama":
        for scene, setups in setups_by_scene.items():
            if setups <= {"single"} and len([x for x in shots if x.get("scene") == scene]) >= 3:
                fail(f"{scene}: {len(setups)} setups are all single — write coverage (master/close)")
            people_shots = [x for x in shots if x.get("scene") == scene and x.get("setup") != "insert"]
            if len(people_shots) >= 3 and "master" not in setups:
                fail(f"{scene}: 3+ people shots but no master setup")
        warnings.extend(check_scene_rig(data, shots, hard=hard))

    for warning in warnings:
        print(f"Gate C2 warning: {warning}", file=sys.stderr)
    print(f"Gate C2 ok: {len(shots)} shots, {total}s, h3={h3}, kind={kind}, sets={len(sets)}")


if __name__ == "__main__":
    main()
