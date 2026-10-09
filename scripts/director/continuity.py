"""Shot-to-shot continuity the viewer feels: where each body is, why things happen, how scenes join.

From the human review of 012 EP01's 480p draft (2026-10-09):

- SH003 ends with Dara crouched at the pit wall; SH004 opens with him standing. SH006/SH008 put him at ground
  level beside the motorbike; SH009 has him at the bottom of the pit. Nobody tracked pose or position, so no
  check could see the jump, and the keyframes drifted.
- The pit wall falls (SH009) and a scout bursts in (SH030) with nothing before them the viewer can read: the
  crack lived in the blurred background of a close-up, the war horn only in the arrival shot itself.
- Modern day cut straight to 1549 (SH010→SH011). The black was written inside SH010's out_to text, where the
  edit never saw it and the video model did.
- 「ARCHAEOLOGY 字样露在火光里」 and 「白线在火光里一闪」 made the model light the shirt and the thread.

So every in-frame person carries `pose` and `spot` (where in the set), and `pose_end` / `spot_end` when the
shot changes them; a sudden event names its `setup`; a scene's last shot carries `transition_out`.
"""

from __future__ import annotations

import re
from typing import Any, Optional

POSES = ("站", "走", "跑", "蹲", "跪", "半跪", "坐", "躺", "趴", "爬", "倒地", "悬空")
# One action word per pose family, used to tell whether a shot shows the change it claims.
POSE_CHANGE_WORDS = ("站起", "起身", "直起", "蹲下", "跪下", "跪倒", "坐下", "坐起", "躺下", "倒下", "倒地", "趴下",
                     "爬起", "爬出", "撑起", "扑倒", "摔倒", "跳下", "跳起", "走", "跑", "爬")
# Something happens to the scene from outside it: the viewer needs the cause first.
EVENT_RE = re.compile(
    r"冲进|冲下|冲来|冲到|跑来|跑进|赶到|闯进|来报|报信|倒塌|塌下|塌了|整面塌|崩塌|崩落|炸开|爆炸|"
    r"电话响|手机响|铃响|震动起来|枪响|撞开|破门|扑进来|射来|飞来"
)
EDIT_WORDS_RE = re.compile(r"切黑|切到|剪辑|淡出|淡入|叠化|黑场|硬切|转场|cut to", re.IGNORECASE)
LIGHT_ON_PROP_RE = re.compile(r"一闪|闪光|发光|发亮|亮起来|在火光里|露在火光|泛着光|闪着光|反着光")
TRANSITIONS = ("cut", "black", "dissolve", "fade")
# A crowd id (「高棉士兵（群演）」) is many people; one soldier kneels while another stands.
CROWD_RE = re.compile(r"群演|群众|众人|们$")
TIGHT = {"close", "insert", "otc", "ots"}


def _t(value: Any) -> str:
    return str(value or "").strip()


def body_states(shot: dict) -> dict[str, dict]:
    """cid -> {pose, pose_end, spot, spot_end, in_frame} for characters in the shot's state."""
    state = shot.get("state") if isinstance(shot.get("state"), dict) else {}
    chars = state.get("characters") if isinstance(state.get("characters"), dict) else {}
    out = {}
    for cid, item in chars.items():
        item = item if isinstance(item, dict) else {}
        pose = _t(item.get("pose"))
        spot = _t(item.get("spot"))
        out[_t(cid)] = {
            "pose": pose,
            "pose_end": _t(item.get("pose_end")) or pose,
            "spot": spot,
            "spot_end": _t(item.get("spot_end")) or spot,
            "in_frame": item.get("in_frame", True) is not False,
        }
    return out


def pose_sentence(shot: dict, names: Optional[dict[str, str]] = None) -> str:
    """「达拉蹲在坑底；维波蹲在坑沿」 for the frame and the video prompt, from pose + spot."""
    names = names or {}
    bits = []
    for cid, body in body_states(shot).items():
        if not body["in_frame"] or not (body["pose"] or body["spot"]):
            continue
        who = names.get(cid, cid)
        pose = body["pose"]
        spot = body["spot"]
        if pose and spot:
            bits.append(f"{who}{pose}在{spot}")
        elif pose:
            bits.append(f"{who}{pose}着")
        else:
            bits.append(f"{who}在{spot}")
    return "；".join(bits)


def _text_of(shot: dict, *keys: str) -> str:
    return " ".join(_t(shot.get(k)) for k in keys)


def shot_findings(shot: dict, sid: str = "") -> tuple[list[str], list[str]]:
    """Single-shot rules: no edit instructions or prop light in the action text; poses from the list."""
    sid = sid or _t(shot.get("shot_id")) or "?"
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("one_action", "in_from", "out_to"):
        text = _t(shot.get(key))
        hit = EDIT_WORDS_RE.search(text)
        if hit:
            errors.append(
                f"{sid} {key} carries an edit instruction 「{hit.group(0)}」; the video model reads it and the edit "
                "never does. Put it in transition_out on the scene's last shot"
            )
        for clause in re.split(r"[，；。,;]", text):
            light = LIGHT_ON_PROP_RE.search(clause)
            if light and "闪电" not in clause and "雷" not in clause:
                warnings.append(
                    f"{sid} {key} 「{clause.strip()}」 hangs light on a thing; the model makes it glow (012 SH017 shirt, "
                    "SH011 thread). Light goes in the light block"
                )
    for cid, body in body_states(shot).items():
        for key in ("pose", "pose_end"):
            if body[key] and body[key] not in POSES:
                errors.append(f"{sid} {cid}.{key} 「{body[key]}」 must be one of {list(POSES)}")
        if body["pose_end"] != body["pose"]:
            text = _text_of(shot, "one_action", "out_to")
            if not any(w in text for w in POSE_CHANGE_WORDS):
                warnings.append(f"{sid} {cid} pose {body['pose']}→{body['pose_end']} but one_action/out_to shows no such move")
    trans = shot.get("transition_out")
    if trans is not None:
        if not isinstance(trans, dict) or _t(trans.get("type")) not in TRANSITIONS:
            errors.append(f"{sid} transition_out needs type in {list(TRANSITIONS)}")
        elif _t(trans.get("type")) in ("black", "dissolve", "fade"):
            try:
                sec = float(trans.get("sec") or 0)
            except (TypeError, ValueError):
                sec = 0
            if not 0.2 <= sec <= 4.0:
                errors.append(f"{sid} transition_out {trans.get('type')} needs sec between 0.2 and 4")
    return errors, warnings


def sequence_findings(shots: list[dict], names: Optional[dict[str, str]] = None) -> tuple[list[str], list[str]]:
    """Across shots: pose and spot carry over, sudden events have a readable setup, scenes say how they end."""
    errors: list[str] = []
    warnings: list[str] = []
    names = names or {}
    uses_pose = any(any(b["pose"] for b in body_states(s).values()) for s in shots)
    index_of = {_t(s.get("shot_id")): i for i, s in enumerate(shots)}
    last_seen: dict[tuple[str, str], tuple[int, dict]] = {}  # (scene, cid) -> (shot index, body)
    for i, shot in enumerate(shots):
        sid = _t(shot.get("shot_id")) or f"#{i + 1}"
        scene = _t(shot.get("scene_id"))
        bodies = body_states(shot)
        for cid, body in bodies.items():
            if not body["in_frame"]:
                continue
            who = names.get(cid, cid)
            if CROWD_RE.search(who):
                continue
            if uses_pose and (not body["pose"] or not body["spot"]):
                errors.append(f"{sid} {who} in frame without pose/spot; the table tracks where every body is")
                continue
            prev = last_seen.get((scene, cid))
            if prev and prev[0] == i - 1 and not shot.get("ellipsis"):
                before = prev[1]
                prev_sid = _t(shots[prev[0]].get("shot_id"))
                if before["pose_end"] and body["pose"] and before["pose_end"] != body["pose"]:
                    errors.append(
                        f"{sid} {who} opens {body['pose']} but {prev_sid} left them {before['pose_end']}; show the move "
                        f"({prev_sid} pose_end, or {sid} opens mid-move), cut away first, or mark ellipsis"
                    )
                if before["spot_end"] and body["spot"] and before["spot_end"] != body["spot"]:
                    errors.append(
                        f"{sid} {who} is at {body['spot']} but {prev_sid} left them at {before['spot_end']}; "
                        "show how they got there, cut away first, or mark ellipsis"
                    )
            last_seen[(scene, cid)] = (i, body)
        # Sudden events need a cause the viewer reads first.
        event = EVENT_RE.search(_text_of(shot, "one_action", "in_from"))
        if event:
            setup = shot.get("setup") if isinstance(shot.get("setup"), dict) else None
            if not setup or not _t(setup.get("how")):
                errors.append(
                    f"{sid} 「{event.group(0)}」 happens with no setup; let the viewer hear or see it coming first "
                    "(setup: {shot, how}: a sound in the shot before, someone looking toward it, or its own shot)"
                )
            else:
                ref = _t(setup.get("shot")) or sid
                if ref not in index_of:
                    errors.append(f"{sid} setup.shot {ref} is not in the table")
                elif index_of[ref] > i:
                    errors.append(f"{sid} setup.shot {ref} comes after the event")
                else:
                    source = shots[index_of[ref]]
                    how = _t(setup.get("how"))
                    carried = _text_of(source, "one_action", "in_from", "out_to") + " " + " ".join(
                        _t(x) for x in source.get("key_sfx") or [])
                    if not any(how[k:k + 2] in carried for k in range(max(1, len(how) - 1))):
                        warnings.append(f"{sid} setup 「{how}」 is not written into {ref}'s action or key_sfx")
                    heard = any(how[k:k + 2] in " ".join(_t(x) for x in source.get("key_sfx") or [])
                                for k in range(max(1, len(how) - 1)))
                    if _t(source.get("scale")) in TIGHT and not heard and ref != sid:
                        warnings.append(
                            f"{sid} setup sits in {ref}, a {_t(source.get('scale'))} shot: a background detail there is "
                            "blurred (012 SH008's crack). Give it a sound or a shot of its own"
                        )
        # Scene ends: say how it joins the next one.
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        if nxt is not None and _t(nxt.get("scene_id")) != scene:
            moves = _t(nxt.get("location_id")) != _t(shot.get("location_id"))
            if moves and not isinstance(shot.get("transition_out"), dict):
                warnings.append(
                    f"{sid} ends scene {scene} and the next scene is elsewhere; write transition_out "
                    "(type cut/black/dissolve, sec, sound bridge)"
                )
    return errors, warnings
