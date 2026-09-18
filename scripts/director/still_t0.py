"""First still = second 0 of the written action.

`one_action` is the motion contract. The first-frame still must show the world
BEFORE that verb has happened. No VLM: regex tables on transform verbs.
"""

from __future__ import annotations

import re
from typing import Any, Optional

STILL_KEYS = ("pose", "holding", "prop_state", "one_paragraph")

# Longest verb first. post/pre are searched on first-still text only.
TRANSFORM_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "pick",
        "verb": "捡",
        "verbs": ("捡起", "拾起", "捡"),
        "pre": ("地上", "脚边", "尚未弯腰", "还在地上", "仍在地上", "仍在脚边", "未捡", "未弯"),
        "post": ("已在手里", "已在右手", "已在左手", "已入手", "入手", "离地", "地上无", "一手拿"),
    },
    {
        "id": "throw",
        "verb": "扔",
        "verbs": ("扔掉", "丢掉", "抛出", "扔到", "扔"),
        "pre": ("手里", "手中", "尚未出手", "还在她手里", "还在手里", "未出手"),
        "post": ("已落地", "落地后", "转完身", "离手落", "停在脚边", "钥匙在地上", "在地上"),
    },
    {
        "id": "open",
        "verb": "开",
        "verbs": ("拉开", "打开", "开柜"),
        "pre": ("虚掩", "未拉开", "未开", "关着", "看不见"),
        "post": ("已打开", "已开", "柜门已开", "柜已开", "露出", "从看不见到"),
    },
    {
        "id": "close",
        "verb": "关",
        "verbs": ("关上", "合上", "关柜"),
        "pre": ("开着", "未关", "仍开"),
        "post": ("已关", "关上了", "合上了"),
    },
    {
        "id": "pocket",
        "verb": "塞进",
        "verbs": ("塞进", "塞入"),
        "pre": ("仍在手里", "还在手里", "未入袋", "未塞", "尚未塞"),
        "post": ("已入袋", "口袋略鼓", "塞完", "不在手里"),
    },
    {
        "id": "take_out",
        "verb": "拿出",
        "verbs": ("拿出", "取出"),
        "pre": ("在袋里", "在柜里", "尚未拿出", "未拿出"),
        "post": ("已拿出", "拿在手里"),
    },
    {
        "id": "wipe",
        "verb": "抹",
        "verbs": ("一抹", "抹掉", "抹去", "抹灰"),
        "pre": ("灰皮", "灰还在", "未抹", "字面未清", "碰到灰", "灰仍在"),
        "post": ("灰掉", "已抹", "抹净", "字面已清", "读清"),
    },
    {
        "id": "pass_through",
        "verb": "穿",
        "verbs": ("穿进", "穿过", "穿出"),
        "pre": ("贴到身前", "尚未穿", "未叠身", "身前", "尚未叠"),
        "post": ("已叠身", "已穿过", "穿出", "肩贴入", "再向画右穿出"),
    },
    {
        "id": "fling",
        "verb": "甩",
        "verbs": ("甩开", "甩"),
        "pre": ("尚未甩", "手里"),
        "post": ("已甩", "甩在地上", "布面铺开"),
    },
)

_NEGATION = re.compile(r"(尚未|还未|还没|没有|未|仍未|并不)")
_GENERIC_PRE = re.compile(r"(尚未|还未|还没|未|仍|还在)")
_COMPLETED = (
    "已在手里",
    "已入手",
    "已落地",
    "已打开",
    "已开",
    "已入袋",
    "已抹",
    "已穿过",
    "已叠身",
    "已甩",
)


def _t(value: Any) -> str:
    return str(value or "").strip()


def normalize_still(raw: Any) -> dict[str, str]:
    block = raw if isinstance(raw, dict) else {}
    return {key: _t(block.get(key)) for key in STILL_KEYS}


def action_span(one_action: str) -> Optional[dict[str, Any]]:
    """Return {verb, pre, post, id} for the first transform verb in one_action."""
    text = _t(one_action)
    if not text:
        return None
    for rule in TRANSFORM_RULES:
        for verb in rule["verbs"]:
            if verb in text:
                return {
                    "id": rule["id"],
                    "verb": rule["verb"],
                    "matched": verb,
                    "pre": tuple(rule["pre"]),
                    "post": tuple(rule["post"]),
                }
    return None


def first_still_text(item: Optional[dict]) -> str:
    """All text that describes the first still (t=0), not the motion."""
    if not item:
        return ""
    start = item.get("still_start") if isinstance(item.get("still_start"), dict) else {}
    subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
    layers = item.get("layers") if isinstance(item.get("layers"), dict) else {}
    parts = [
        _t(start.get("one_paragraph")),
        _t(item.get("one_paragraph")),
        _t(start.get("pose")),
        _t(start.get("holding")) or _t(subject.get("holding")),
        _t(start.get("prop_state")),
        _t(subject.get("hands")),
        _t(subject.get("facing")),
        _t(layers.get("foreground")),
        _t(layers.get("midground")),
        _t(layers.get("background")),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return " ".join(out)


def last_still_text(item: Optional[dict]) -> str:
    if not item:
        return ""
    end = item.get("still_end") if isinstance(item.get("still_end"), dict) else {}
    return _t(item.get("last_paragraph")) or _t(end.get("one_paragraph"))


def keyframe_plan_of(shot: Optional[dict] = None, spec: Optional[dict] = None) -> str:
    """Same first / first_last split as package_gen_mode, reading shot fields."""
    shot = shot or {}
    spec = spec or {}
    plan = _t(shot.get("keyframe_plan") or spec.get("keyframe_plan"))
    if plan in {"first", "first_last"}:
        return plan
    coverage = _t(shot.get("coverage_type") or spec.get("coverage_type"))
    size = _t(spec.get("shot_size") or shot.get("scale"))
    move = _t(spec.get("move_type") or shot.get("move_type") or "static")
    start = _t(spec.get("in_from") or shot.get("in_from"))
    end = _t(spec.get("out_to") or shot.get("out_to"))
    if size == "insert" and move == "static":
        return "first"
    if coverage == "continuous":
        return "first"
    if coverage in {"reaction", "close"}:
        return "first"
    if move not in {"", "static"} and start and end:
        return "first_last"
    return "first"


def needs_last_still(shot: Optional[dict] = None, spec: Optional[dict] = None) -> bool:
    return keyframe_plan_of(shot, spec) == "first_last"


def _find_unnegated(blob: str, token: str) -> bool:
    start = 0
    while True:
        at = blob.find(token, start)
        if at < 0:
            return False
        window = blob[max(0, at - 6) : at]
        if not _NEGATION.search(window):
            return True
        start = at + 1


def start_still_errors(shot: dict, frame_desc: Optional[dict]) -> list[str]:
    """Machine check: transform verb + first-still already shows the result."""
    sid = _t(shot.get("shot_id")) or "?"
    action = _t(shot.get("one_action") or shot.get("action_now") or shot.get("action_ref"))
    span = action_span(action)
    if not span:
        return []
    blob = first_still_text(frame_desc)
    in_from = _t(shot.get("in_from"))
    errors: list[str] = []
    posts = [token for token in span["post"] if token and _find_unnegated(blob, token)]
    for token in _COMPLETED:
        if token not in posts and _find_unnegated(blob, token):
            posts.append(token)
    if posts:
        errors.append(
            f"{sid} first still is mid/result of 「{span['verb']}」 ({'、'.join(posts[:3])}); "
            f"t=0 must be before the verb. in_from={in_from or '—'}"
        )
    pre_hit = any(token and token in blob for token in span["pre"]) or bool(_GENERIC_PRE.search(blob))
    if blob and not pre_hit:
        errors.append(
            f"{sid} first still missing pre-state of 「{span['verb']}」 "
            f"(need one of { ' / '.join(span['pre'][:4]) } or 尚未)"
        )
    if in_from and blob:
        in_has_pre = any(token and token in in_from for token in span["pre"]) or bool(_GENERIC_PRE.search(in_from))
        if in_has_pre and posts:
            errors.append(
                f"{sid} in_from is t=0 (「{in_from}」) but first-still text already asserts the result"
            )
    return errors


def last_still_errors(shot: dict, frame_desc: Optional[dict]) -> list[str]:
    if not needs_last_still(shot):
        return []
    if last_still_text(frame_desc):
        return []
    sid = _t(shot.get("shot_id")) or "?"
    return [f"{sid} first_last missing still_end / last_paragraph"]


def still_t0_errors(shot: dict, frame_desc: Optional[dict]) -> list[str]:
    return start_still_errors(shot, frame_desc) + last_still_errors(shot, frame_desc)


def issues_for_table(shots: list[dict], descriptions_by_id: dict) -> list[str]:
    """All t=0 issues for a shot list. Used as Gate C2 warnings."""
    out: list[str] = []
    for shot in shots or []:
        sid = _t(shot.get("shot_id"))
        if not sid:
            continue
        out.extend(still_t0_errors(shot, descriptions_by_id.get(sid)))
    return out


def forbidden_result_clause(one_action: str) -> str:
    """Negative list for the first-frame brief."""
    span = action_span(one_action)
    if not span:
        return "禁止把 one_action 的结果画进首帧。"
    posts = "、".join(span["post"][:6])
    return f"禁止画进首帧：{posts}。画动作尚未发生的那一格。"
