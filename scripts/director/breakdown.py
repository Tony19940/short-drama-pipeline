"""Scene-rig breakdown. Coverage is evidence, not one-row-one-shot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .defaults import DEFAULT_ASPECT, production_aspect
from .knowledge import load_for
from .prompts import camera_for_move, compose_video_prompt
from .scriptwriter import (
    _people,
    _slug_place,
    align_slug,
    parse_beat_table,
    parse_coverage_table,
    parse_dialogue,
    pick_dialogue,
    visible_action,
    visible_look,
    visible_start,
)

DIRECTING = "scene-rig-v1"
HANDLE = 2
SCALE_FOR_SETUP = {
    "master": "full",
    "close": "close",
    "ots": "med",
    "single": "med",
    "insert": "insert",
}
REST_START = re.compile(
    r"\b(rest pose|standing still|planted|not yet|on marks|hold the start|second-0 stance)\b",
    re.I,
)
MID_START = re.compile(
    r"mid-action|mid-motion|mid-turn|halfway|mid-lift|already turning|already lifting|already halfway|already underway|gesture is already",
    re.I,
)


def action_tokens(action: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", action or "")
    skip = {
        "then", "hold", "still", "does", "not", "with", "from", "into", "onto",
        "that", "this", "they", "them", "have", "been", "after", "before",
        "both", "once", "only", "keep", "keeps", "already", "leave", "motion",
        "unfinished", "play", "visible", "beat",
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


def prompt_has_action(prompt: str, action: str) -> bool:
    tokens = action_tokens(action)
    if len(tokens) < 2:
        return bool(tokens) and tokens[0] in (prompt or "").lower()
    blob = (prompt or "").lower()
    return sum(1 for token in tokens if token in blob) >= 2


def _sec_for(kind: str, setup: str, requested: int, line: str = "") -> int:
    if kind == "reaction":
        return 2
    if kind in {"dialogue", "inner"}:
        n = len((line or "").strip())
        if n <= 8:
            spoken = 2
        elif n <= 16:
            spoken = 3
        elif n <= 24:
            spoken = 4
        else:
            spoken = 5
        return spoken
    if setup == "master":
        return max(4, min(8, requested or 6))
    if setup == "insert":
        return max(2, min(6, requested or 4))
    return max(3, min(6, requested or 5))


def _move_for(setup: str, info: str, rig_used: dict[str, int], kind: str = "") -> str:
    blob = info or ""
    count = rig_used.get(setup, 0)
    if kind == "reaction":
        return "static" if setup == "insert" else "push" if setup == "close" else "pan"
    if setup == "insert":
        return "static"
    if re.search(r"推|更紧|特写|push", blob, re.I):
        return "push"
    if re.search(r"拉|pull|全貌", blob, re.I):
        return "pull"
    if setup == "close":
        return "push"
    if setup == "master":
        return "static" if count == 0 else "track"
    if setup == "ots":
        return "pan"
    return "static"


def _landing(action: str) -> str:
    text = (action or "").strip().rstrip(".")
    return f"Leave on the unfinished beat of: {text}. Cut before rest."


def _case_for(scene: str, info: str) -> str:
    blob = f"{scene} {info}"
    if re.search(r"烧|退路|出逃|吊桥|causeway|gate", blob):
        return "escape"
    if re.search(r"送走|牛车|抬|我不走|铜铃", blob):
        return "send-off"
    if re.search(r"认|揭|换墙|银铃|墙色", blob):
        return "reveal"
    return "standoff"


def _rigs_for(scene: str, rows: list[dict]) -> list[dict]:
    has_insert = any(str(row.get("setup") or "") == "insert" for row in rows)
    blob = " ".join(str(row.get("new_info") or row.get("beat") or "") for row in rows)
    case = _case_for(scene, blob)
    rigs = [
        {"id": f"{scene}:A", "setup": "master", "note": "geography / blocking"},
        {"id": f"{scene}:B", "setup": "close", "note": "decision / object / face"},
    ]
    if case in {"standoff", "reveal", "send-off", "escape"} or any(
        str(row.get("setup") or "") == "ots" for row in rows
    ):
        rigs.append({"id": f"{scene}:C", "setup": "ots", "note": "relationship / over-shoulder"})
    if has_insert or re.search(r"铃|令|拓片|短信|钱|insert", blob, re.I):
        rigs.append({"id": f"{scene}:D", "setup": "insert", "note": "prop insert"})
    return rigs[:4]


def _pick_rig(row: dict, rigs: list[dict], prev_setup: str | None) -> dict:
    wanted = str(row.get("setup") or "").strip()
    if wanted == "reaction":
        wanted = "ots" if prev_setup != "ots" else "close"
    if wanted:
        for rig in rigs:
            if rig["setup"] == wanted:
                return rig
    info = str(row.get("new_info") or row.get("beat") or "")
    if re.search(r"铃|令|拓片|短信|钱", info):
        for rig in rigs:
            if rig["setup"] == "insert":
                return rig
    if re.search(r"特写|脸|眼|抬头|认", info):
        for rig in rigs:
            if rig["setup"] == "close":
                return rig
    if prev_setup == "master":
        for rig in rigs:
            if rig["setup"] in {"close", "ots"}:
                return rig
    return rigs[0]


def _other_rig(rigs: list[dict], current: dict) -> dict:
    setup = current.get("setup")
    for wanted in ("ots", "close", "master"):
        if wanted == setup:
            continue
        for rig in rigs:
            if rig["setup"] == wanted:
                return rig
    for rig in rigs:
        if rig["id"] != current.get("id"):
            return rig
    return current


def _action_for(row: dict) -> str:
    action = visible_action(row)
    info = str(row.get("new_info") or row.get("beat") or "this beat")
    if action.startswith("Start still, perform one visible motion"):
        return f"Play one visible beat for {info}; leave the motion unfinished"
    if "leave the motion unfinished" not in action.lower() and "leave unfinished" not in action.lower():
        return action.rstrip(".") + "; leave the motion unfinished"
    return action


def _mid_action_start(action: str, setup: str, fallback: str) -> str:
    blob = (action or "").strip().rstrip(".")
    if MID_START.search(fallback or "") and not REST_START.search(fallback or ""):
        return fallback
    if not blob:
        return f"Mid-action {setup or 'locked'} frame; the gesture is already halfway through"
    return (
        f"Mid-action {setup or 'locked'} frame: {blob} is already halfway through; "
        "do not reset to a planted rest pose"
    )


def _stamp_handles(shot: dict) -> dict:
    seconds = max(2, int(shot.get("seconds") or 2))
    shot["seconds"] = seconds
    shot["in_at"] = 0
    shot["out_at"] = seconds
    shot["handle"] = HANDLE
    shot["render_seconds"] = seconds + HANDLE
    return shot


def _merge_rows(rows: list[dict]) -> list[dict]:
    return [dict(row) for row in rows]


def _shot_from_row(
    index: int,
    row: dict,
    prev: Optional[dict],
    rig: dict,
    dialogue: Optional[dict],
    prod: Optional[Path],
    rig_used: dict[str, int],
    *,
    kind_override: str | None = None,
    line_override: str | None = None,
    action_override: str | None = None,
    start_override: str | None = None,
    new_info_override: str | None = None,
) -> dict:
    scene = str(row.get("place") or "")
    if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", scene):
        scene = _slug_place(scene, scene or "factory-floor")
    setup = rig["setup"]
    people = [align_slug(name, prod) for name in (row.get("people") or "").replace("/", ",").split(",") if name.strip()]
    if not people:
        people = _people(" ".join([str(row.get("beat") or ""), str(row.get("new_info") or "")]), prod)
    people = [
        name
        for name in people
        if name and re.fullmatch(r"[a-z][a-z0-9-]*", name)
    ][:3]
    if not people:
        people = [
            name
            for name in _people(" ".join([str(row.get("beat") or ""), str(row.get("new_info") or "")]), prod)
            if name and re.fullmatch(r"[a-z][a-z0-9-]*", name)
        ][:3]
    kind = kind_override or (dialogue or {}).get("kind") or "narration"
    if str(row.get("setup") or "") == "reaction" and not kind_override:
        kind = "reaction"
    if kind == "reaction":
        line = line_override if line_override is not None else ""
    else:
        line = line_override if line_override is not None else ((dialogue or {}).get("text") or f"{row.get('new_info') or row.get('beat')}。")
    requested = int(row.get("end") or 0) - int(row.get("start") or 0)
    seconds = _sec_for(kind, setup, requested, str(line))
    note = " ".join(str(row.get(key) or "") for key in ("move", "camera_note", "new_info", "beat"))
    move = _move_for(setup, note, rig_used, kind)
    same_scene = prev is not None and prev.get("scene") == scene
    if not same_scene:
        cut, derived, from_id = "hard", f"{scene}.blocking", None
        axis = "center" if setup == "master" else "left"
    else:
        cut, derived, from_id = "continue", prev["id"], prev["id"]
        axis = "left" if setup != "master" else "center"
    action = action_override or _action_for(row)
    look = visible_look(scene, row)
    planted = visible_start(scene, row, people, setup, prev)
    if start_override:
        start = start_override
    elif setup == "insert":
        start = planted if cut != "continue" else _mid_action_start(action, setup, "")
    elif cut == "continue":
        start = _mid_action_start(action, setup, planted)
    else:
        start = planted
    camera = camera_for_move(move)
    lens = "35mm" if setup == "master" else "85mm" if setup in {"close", "insert"} else "50mm"
    sid = f"SH{index:03d}"
    speaker = ""
    if kind in {"dialogue", "inner"}:
        speaker = (dialogue or {}).get("character") or ""
    shot = {
        "id": sid,
        "seconds": seconds,
        "tier": "h3" if setup == "close" and index <= 3 else "fast",
        "scale": SCALE_FOR_SETUP.get(setup, "med"),
        "setup": setup,
        "rig_id": rig["id"],
        "move": move,
        "cut": cut,
        "from": from_id,
        "derived_from": derived,
        "facing": "scene" if setup == "master" else "camera" if setup == "close" else "scene",
        "expression": "held",
        "blocking": f"{', '.join(people)} on {scene} marks",
        "start": start,
        "scene": scene,
        "characters": people,
        "new_info": new_info_override or row.get("new_info") or row.get("beat") or f"beat {index}",
        "line_kind": kind,
        "speaker": speaker,
        "line": line,
        "caption": str(line)[:32],
        "on_screen": "",
        "frame": f"04-frames/{sid}.jpg",
        "last_frame": f"04-frames/{sid}-last.jpg",
        "end_frame": "",
        "prompt": f"{setup} {SCALE_FOR_SETUP.get(setup, 'med')}. One motion only. [{move}]",
        "lens": lens,
        "axis": axis,
        "camera": camera,
        "action": action,
        "look": look,
        "landing": _landing(action),
        "cut_on": "mid-action, not a rest pose",
        "negatives": (
            "no subtitles, no captions, no watermark, no logo, no extra person, "
            "no clothing change, no face drift, no orbit, no crash zoom, no beauty filter, no lip-sync speech, "
            "no qipao, no Forbidden City, no WeChat wallet, no location change, no restaurant, no street cutaway"
        ),
        "emotion": "held",
        "sfx": "",
        "story_function": str(row.get("new_info") or row.get("beat") or "advance"),
        "end": _landing(action),
        "camera_path": move,
        "camera_speed": {"static": "locked", "push": "slow", "pull": "slow", "pan": "medium", "track": "medium"}.get(move, "slow"),
        "performance": action,
        "sound_intent": kind,
        "shot_job": str(new_info_override or row.get("new_info") or row.get("beat") or action),
        "coverage_type": "otc" if setup == "ots" else ("reaction" if kind == "reaction" else setup),
        "move_needed": "static" if move == "static" else "move",
        "move_reason": "" if move == "static" else camera_for_move(move),
    }
    shot["video_prompt"] = compose_video_prompt(shot)
    if not prompt_has_action(shot["video_prompt"], action):
        shot["video_prompt"] = f"{shot['video_prompt']} {action}"
    return _stamp_handles(shot)


def _reaction_shot(index: int, spoken: dict, row: dict, rigs: list[dict], prod: Optional[Path], used: dict[str, int]) -> dict:
    rig = _other_rig(rigs, {"id": spoken.get("rig_id"), "setup": spoken.get("setup")})
    people = list(spoken.get("characters") or [])
    roman = [name for name in people if name and re.fullmatch(r"[a-z][a-z0-9-]*", name)]
    listener = roman[1] if len(roman) > 1 else (roman[0] if roman else "the listener")
    action = f"{listener} holds the look after {spoken.get('id')}; does not answer yet; leave the motion unfinished"
    start = (
        f"Mid-action {rig['setup']} on {listener}: already turning to take in the last line, "
        "eyes still on the speaker, not a planted rest pose"
    )
    info = f"听完 {spoken.get('id')} 的反应"
    return _shot_from_row(
        index,
        row,
        spoken,
        rig,
        None,
        prod,
        used,
        kind_override="reaction",
        line_override="",
        action_override=action,
        start_override=start,
        new_info_override=info,
    )


def group_rows(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    for row in rows:
        scene = str(row.get("place") or "factory-floor")
        if groups and groups[-1][0] == scene:
            groups[-1][1].append(row)
        else:
            groups.append((scene, [row]))
    return groups


def breakdown_package(prod: Path) -> dict:
    from .production import read_text

    episode = read_text(prod, "01-bible/ep01.md")
    coverage = read_text(prod, "03-storyboard/coverage.md")
    official_beats = read_text(prod, "03-storyboard/beats.md")
    if not episode.strip():
        from .scriptwriter import ScriptError

        raise ScriptError("NO_EPISODE", "还没有 ep01.md，先上传或粘贴剧本")
    rows = parse_coverage_table(coverage, prod)
    source = "coverage.md"
    beat_rows = parse_beat_table(official_beats)
    if beat_rows and rows and len(beat_rows) == len(rows):
        for cov, beat in zip(rows, beat_rows):
            if beat.get("people"):
                cov["people"] = beat["people"]
        source = "coverage.md+beats.md"
    if not rows:
        rows = beat_rows
        source = "beats.md"
    if not rows:
        from .scriptwriter import heuristic_package

        fallback = heuristic_package(prod)
        rows = []
        start = 0
        for shot in fallback["shots"]["shots"]:
            rows.append(
                {
                    "index": len(rows) + 1,
                    "start": start,
                    "end": start + int(shot.get("seconds") or 6),
                    "beat": shot.get("new_info"),
                    "place": shot.get("scene"),
                    "new_info": shot.get("new_info"),
                    "people": ",".join(shot.get("characters") or []),
                    "setup": shot.get("setup"),
                    "move": shot.get("move"),
                    "camera_note": shot.get("camera"),
                }
            )
            start += int(shot.get("seconds") or 6)
        source = fallback.get("beat_source") or "fallback"
    dialogue = parse_dialogue(episode)
    unused = list(dialogue)
    shots: list[dict] = []
    scenes: list[dict] = []
    prev = None
    index = 1
    for scene, scene_rows in group_rows(rows):
        scene_rows = _merge_rows(scene_rows)
        rigs = _rigs_for(scene, scene_rows)
        used: dict[str, int] = {}
        scenes.append(
            {
                "id": scene,
                "axis": "keep the blocking axis",
                "case": _case_for(scene, " ".join(str(r.get("new_info") or "") for r in scene_rows)),
                "rigs": rigs,
            }
        )
        reactions_in_scene = 0
        last_spoken = None
        for row_i, row in enumerate(scene_rows):
            rig = _pick_rig(row, rigs, prev.get("setup") if prev else None)
            if prev and prev.get("scene") == scene and prev.get("setup") == rig["setup"] and rig["setup"] != "insert":
                rig = _other_rig(rigs, rig)
            line = pick_dialogue(row, unused)
            shot = _shot_from_row(index, row, prev, rig, line, prod, used)
            used[rig["setup"]] = used.get(rig["setup"], 0) + 1
            shots.append(shot)
            prev = shot
            index += 1
            if shot.get("line_kind") == "reaction":
                job = str(shot.get("shot_job") or shot.get("action") or "").strip()
                if len(job) < 8:
                    from .scriptwriter import ScriptError
                    raise ScriptError("EMPTY_REACTION", f"{shot.get('id')} 反应镜没有独立任务")
            spoken = shot.get("line_kind") in {"dialogue", "inner"} and shot.get("setup") != "insert"
            if spoken:
                last_spoken = (shot, row)
    h3 = 0
    for shot in shots:
        if shot.get("tier") == "h3":
            h3 += 1
            if h3 > 3:
                shot["tier"] = "fast"
    knowledge = load_for("director")
    return {
        "beat_source": source,
        "knowledge": list(knowledge),
        "shots": {
            "episode": "ep01",
            "kind": "shortdrama",
            "aspect": production_aspect(prod) if prod else DEFAULT_ASPECT,
            "origin": "director-breakdown",
            "directing": DIRECTING,
            "scenes": scenes,
            "shots": shots,
        },
    }
