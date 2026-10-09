"""What a video model will do with a shot's action text.

Seedance acts out every verb it reads, in order, and fills spare seconds with the most natural next step.
012 EP01's 480p draft showed both failure modes:

- SH022 「果萨端起递来的竹筒要喝」: 「要喝」 is an intention the camera cannot see. He drank from 1.0s, and the
  next three shots (「别喝！」, the tube held short of his lips, the water poured out) stopped making sense.
- SH005 out_to 「维波笑着站起」: a second action hidden in the landing. The static over-the-shoulder frame was
  composed for a crouch; he stood at 3.3s and finished his line with his head out of frame.

So a shot's action text says only what the camera sees and where it stops. An action the next shot interrupts
is marked `held_action` and compiled as a visible stop point held to the end of the shot.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Intention or near-miss markers: the model completes whatever follows them.
# 要/想 skip common compounds (需要, 重要, 想法, 想起...) that are not intentions.
INTENT_RE = re.compile(
    r"(?:正要|将要|快要|想要|准备|打算|试图|企图|意图|差点|险些"
    r"|(?<![需重主只首紧必不还])要(?![求么是紧不])"
    r"|(?<![思回理感梦设])想(?![法象像起到]))"
    r"(?=[一-鿿])"
)
# Big body-height changes: a static medium/close frame composed for the start pose loses the head.
# Each family is one movement; a landing that finishes the action already in one_action is not "added".
POSTURE_FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # family: (verbs that change height a lot, words in one_action that already do it)
    "stand": (("站起", "起身", "爬起"), ("站", "起身", "爬起", "直起")),
    "sit": (("坐下", "坐起"), ("坐",)),
    "low": (("蹲下", "跪下", "跪倒"), ("蹲", "跪")),
    "fall": (("躺下", "倒下", "倒地", "趴下", "摔倒", "瘫倒"), ("躺", "倒", "趴", "摔", "瘫")),
    "jump": (("跳起", "跳下"), ("跳",)),
}
POSTURE_VERBS = tuple(v for verbs, _roots in POSTURE_FAMILIES.values() for v in verbs)
# Smaller changes (straightening from a lean): warned, never an error.
SMALL_POSTURE_VERBS = ("直起身", "直起腰", "站直")
# Travel: the body leaves its mark and may leave the frame. 离开 alone is skipped: hands leave cups too.
TRAVEL_VERBS = (
    "走出", "走开", "走向", "走进", "走到", "走过", "走近", "跑", "冲向", "冲出", "冲进",
    "扑向", "扑上", "扑过", "退后", "后退", "追", "逃",
)
# 未起身 / 无人走近 / 没有站起: the landing says it does not happen.
# 切蹲下 / 切到起身: a (legacy) cut instruction naming the next shot, not this shot's action.
NEGATION_RE = re.compile(r"(?:未|没|没有|尚未|仍未|还没|无人|不|别|并未|不再|切|切到)$")
VOCAL_ACT_RE = re.compile(r"喊|叫|哭|张嘴喘|大口喘|嚎|呻吟|吼")
EXIT_RE = re.compile(r"出画|走出画|出了画|离开画面|走出镜头")
# Framings where a standing body outgrows a frame composed for a crouch or a seat.
TIGHT_FRAMES = {"medium", "close", "otc", "ots", "insert", "pov"}
ADDED_ACTION_SEC = 0.8
ADDED_ACTION_CAP_SEC = 1.6
# Cue words that finish a held action. The unfinished verb itself always counts.
COMPLETION_CUES: dict[str, tuple[str, ...]] = {
    "喝": ("喝", "吞", "咽", "喉结", "仰头", "灌"),
    "吃": ("吃", "咬", "嚼", "吞", "咽"),
    "砍": ("砍", "劈", "刀落", "落刀"),
    "刺": ("刺", "捅", "扎进"),
    "开枪": ("开枪", "扣扳机", "枪响", "开火"),
    "射": ("射", "放箭", "松弦"),
    "打开": ("打开", "推开", "拉开", "掀开", "揭开"),
    "开门": ("打开", "推开", "拉开"),
    "亲": ("亲", "吻"),
    "扔": ("扔", "掷", "抛出", "甩出"),
    "签": ("签", "落笔", "写下"),
    "按": ("按下", "摁下"),
    "推": ("推倒", "推下"),
    "跳": ("跳",),
}


def _t(value: Any) -> str:
    return str(value or "").strip()


QUOTED_RE = re.compile(r"「[^」]*」|“[^”]*”|\"[^\"]*\"")
# Reported speech: what follows 说/喊/问… in a clause is a line, not an action (「琳开口说他要当老板」).
SPEECH_VERB_RE = re.compile(r"说|喊|问|骂|念|唱|答|吼|嘀咕|宣布")
CLAUSE_RE = re.compile(r"[，；。！？,;!?]")


def intent_hits(text: str) -> list[str]:
    """Intention phrases like 要喝 / 准备开 / 差点摔 (marker + next two characters).

    Quoted text and reported speech are lines, not actions, and are skipped.
    """
    raw = QUOTED_RE.sub("", _t(text))
    hits = []
    for clause in CLAUSE_RE.split(raw):
        speech = SPEECH_VERB_RE.search(clause)
        acted = clause[: speech.start()] if speech else clause
        for match in INTENT_RE.finditer(acted):
            hits.append(acted[match.start(): match.end() + 2])
    return hits


def is_exit(text: str) -> bool:
    return bool(EXIT_RE.search(_t(text)))


def _happens(text: str, verb: str) -> bool:
    """True when `verb` occurs in `text` at least once without a negation right before it."""
    start = 0
    while True:
        at = text.find(verb, start)
        if at < 0:
            return False
        if not NEGATION_RE.search(text[max(0, at - 3): at]):
            return True
        start = at + len(verb)


def added_actions(base: str, text: str) -> tuple[list[str], list[str]]:
    """(posture, travel) verbs that `text` does and `base` (one_action) does not already do.

    Small straightening moves (直起身 / 站直) come back in the posture list only when the base has no
    standing at all; callers treat them as warnings.
    """
    base = _t(base)
    text = QUOTED_RE.sub("", _t(text))  # a quoted line is speech, not movement
    posture: list[str] = []
    for verbs, roots in POSTURE_FAMILIES.values():
        if any(r in base for r in roots):
            continue
        posture.extend(v for v in verbs if _happens(text, v))
    small = [v for v in SMALL_POSTURE_VERBS if _happens(text, v) and not any(r in base for r in POSTURE_FAMILIES["stand"][1])]
    posture.extend(small)
    # 直起身 contains 起身: report the longer word once
    posture = [v for v in dict.fromkeys(posture) if not any(v != w and v in w for w in posture)]
    travel = [v for v in TRAVEL_VERBS if _happens(text, v) and v not in base]
    travel = [v for v in travel if not any(v != w and v in w for w in travel)]
    return posture, travel


def held_action(shot: dict) -> Optional[dict]:
    """`held_action: {stop_at, unfinished, keep}`: the action the next shot interrupts, stopped short."""
    raw = shot.get("held_action")
    if not isinstance(raw, dict):
        return None
    return {"stop_at": _t(raw.get("stop_at")), "unfinished": _t(raw.get("unfinished")), "keep": _t(raw.get("keep"))}


def completion_cues(unfinished: str) -> list[str]:
    text = _t(unfinished)
    cues: list[str] = []
    for verb, words in COMPLETION_CUES.items():
        if verb in text:
            cues.extend((verb, *words))
    if not cues and text:
        cues.append(text)
    return list(dict.fromkeys(cues))


def strip_cues(text: str, cues: list[str]) -> str:
    """Drop clauses (split on ；，。) that would finish a held action."""
    if not cues:
        return _t(text)
    parts = re.split(r"(?<=[；，。])", _t(text))
    kept = [p for p in parts if p and not any(c in p for c in cues)]
    out = "".join(kept).strip()
    return re.sub(r"[；，]+$", "。", out) if out else ""


def added_action_seconds(shot: dict) -> float:
    """Extra seconds for posture / travel the landing adds after the main action (exits excluded)."""
    out_to = _t(shot.get("out_to"))
    if is_exit(out_to):
        return 0.0
    posture, travel = added_actions(_t(shot.get("one_action") or shot.get("action_ref")), out_to)
    return min(ADDED_ACTION_CAP_SEC, ADDED_ACTION_SEC * (len(posture) + len(travel)))


def action_findings(shot: dict, sid: str = "") -> tuple[list[str], list[str]]:
    """Errors and warnings for one shot's one_action / in_from / out_to / held_action."""
    sid = sid or _t(shot.get("shot_id")) or "?"
    errors: list[str] = []
    warnings: list[str] = []
    action = _t(shot.get("one_action"))
    for key in ("one_action", "in_from", "out_to"):
        for hit in intent_hits(shot.get(key)):
            errors.append(
                f"{sid} {key} says 「{hit}」, an intention the camera cannot see; the video model finishes it. "
                "Write the visible stop point (e.g. 竹筒抬到离嘴唇一指远停住); if the next shot interrupts it, add held_action"
            )
    held = held_action(shot)
    if shot.get("held_action") is not None and held is None:
        errors.append(f"{sid} held_action must be an object {{stop_at, unfinished, keep}}")
    if held:
        if not held["stop_at"]:
            errors.append(f"{sid} held_action needs stop_at: where the hand / body / prop stops, as the camera sees it")
        if not held["unfinished"]:
            errors.append(f"{sid} held_action needs unfinished: the action that must not complete in this shot")
        cues = completion_cues(held["unfinished"])
        for key in ("one_action", "in_from", "out_to"):
            text = _t(shot.get(key))
            hit = next((c for c in cues if c in text), "")
            if hit:
                errors.append(f"{sid} {key} still says 「{hit}」 though held_action stops short of {held['unfinished']}")
        if held["stop_at"] and held["stop_at"] not in _t(shot.get("out_to")):
            warnings.append(f"{sid} held_action stop_at should be the out_to landing: 「{held['stop_at']}」")
    out_to = _t(shot.get("out_to"))
    if out_to and not is_exit(out_to):
        posture, travel = added_actions(action, out_to)
        move = _t(shot.get("move_type")) or "static"
        scale = _t(shot.get("scale"))
        first_last = _t(shot.get("keyframe_plan")) == "first_last"
        big = [v for v in posture if v not in SMALL_POSTURE_VERBS]
        if posture:
            words = "、".join(posture)
            if big and move == "static" and scale in TIGHT_FRAMES and not first_last:
                words = "、".join(big)
                errors.append(
                    f"{sid} out_to adds 「{words}」 that one_action does not do; a static {scale} frame composed for the "
                    "start pose loses the head or body when the pose changes. Drop it, follow it with the camera "
                    "(move_type), design the end frame (keyframe_plan=first_last), or split the shot"
                )
            else:
                warnings.append(f"{sid} out_to adds 「{words}」 that one_action does not do; one action per shot, the landing is its result")
        if travel:
            warnings.append(
                f"{sid} out_to adds 「{'、'.join(travel)}」 that one_action does not do; write 出画 if the person leaves on purpose"
            )
    return errors, warnings


def acting_findings(shot: dict, acting: dict, sid: str = "") -> tuple[list[str], list[str]]:
    """7a acting (business / muscle / change) must stay inside the shot's action and its landing."""
    sid = sid or _t(shot.get("shot_id")) or "?"
    errors: list[str] = []
    warnings: list[str] = []
    base = _t(shot.get("one_action")) + " " + _t(shot.get("out_to"))
    held = held_action(shot)
    cues = completion_cues(held["unfinished"]) if held else []
    move = _t(shot.get("move_type")) or "static"
    tight_static = move == "static" and _t(shot.get("scale")) in TIGHT_FRAMES and _t(shot.get("keyframe_plan")) != "first_last"
    exit_shot = is_exit(shot.get("out_to"))
    off_voice = _t(shot.get("dialogue_delivery")) in ("off_camera", "phone", "inner", "narration")
    for who, item in (acting or {}).items():
        if not isinstance(item, dict):
            continue
        for key in ("business", "muscle", "change"):
            text = _t(item.get(key))
            if not text:
                continue
            hit = next((c for c in cues if c in text), "")
            if hit:
                errors.append(
                    f"{sid} acting.{who}.{key} 「{text}」 finishes the held action ({held['unfinished']}) with 「{hit}」; "
                    "act the stop instead (hand and prop held where stop_at says)"
                )
            if off_voice and VOCAL_ACT_RE.search(text):
                errors.append(
                    f"{sid} acting.{who}.{key} 「{text}」 makes the person in frame vocalise over an off-screen line; "
                    "one voice per shot (012 probe SH012: his gasping drowned the soldier's shout)"
                )
            for phrase in intent_hits(text):
                warnings.append(f"{sid} acting.{who}.{key} says 「{phrase}」; the video model plays intentions out as actions")
            if exit_shot:
                continue
            posture, travel = added_actions(base, text)
            big = [v for v in posture if v not in SMALL_POSTURE_VERBS]
            if big and tight_static:
                errors.append(
                    f"{sid} acting.{who}.{key} adds 「{'、'.join(big)}」 that the shot's action and landing do not have; "
                    "the static frame cannot hold the new pose"
                )
            elif posture or travel:
                warnings.append(
                    f"{sid} acting.{who}.{key} adds 「{'、'.join(posture + travel)}」 beyond one_action / out_to"
                )
    return errors, warnings
