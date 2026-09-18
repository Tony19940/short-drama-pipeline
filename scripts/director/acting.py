"""Acting = behavior, not feelings (Hell Grind ACTING SKILL).

A shot row may carry `acting: {角色: {want, hide, business, muscle, change}}`.
`want` / `hide` are the inner line the actor plays against; `business` (手上的事),
`muscle` (肌肉 / 大动作) and `change` (what flips) are what the camera can see.
Emotion adjectives (愤怒 / 冷笑 / 若有所思 …) in the visible fields only warn —
the hint is to rewrite them as 大动作 + 手上的事 + 肌肉.
"""

from __future__ import annotations

import re
from typing import Any, Optional

ACTING_FIELDS = ("want", "hide", "business", "muscle", "change")
# Fields the camera sees. want / hide stay inner and are not scanned.
VISIBLE_FIELDS = ("business", "muscle", "change")
# Longest first so 冷笑 wins over 冷.
EMOTION_ADJECTIVES = (
    "若有所思", "不情愿", "不耐烦", "冷静", "冷笑", "夸张", "平静", "愤怒", "生气", "悲伤", "惊讶",
    "害怕", "恐惧", "紧张", "焦虑", "委屈", "不屑", "不服", "认命", "讥讽", "得意", "无奈", "淡然",
    "发急", "过分", "怕得", "急得", "冷得", "愣住", "怕", "愣", "讥", "横", "冷",
)
_EMOTION_RE = re.compile("|".join(re.escape(w) for w in EMOTION_ADJECTIVES))
# Physical reads: eyes / mouth / jaw / hands / feet / body — what a 2–4s 短剧 shot can show.
PHYSICAL_TOKENS = (
    "眼瞪大", "瞪大", "瞪眼", "瞪着", "眼瞪", "眼散", "眼先到", "抬眼", "低头", "回头", "转头", "头后转",
    "咬牙", "咬唇", "咬住下唇", "嘴扯开", "扯开嘴", "嘴张", "张嘴", "嘴闭", "撇嘴", "嘴角", "下巴",
    "皱眉", "眉", "鼻息", "喘", "眨眼", "呼吸", "脸拧", "脖子", "缩肩", "肩", "手停", "手僵", "僵住",
    "手抖", "甩手", "拍桌", "指着", "举", "伸手", "攥", "握", "跨步", "逼近", "贴近", "贴", "后退",
    "退撞", "挤进", "急步", "急踩", "踏", "站直", "身前倾", "前倾", "转身", "背对", "偏头", "不偏",
    "拉开", "推", "塞", "捡", "扔", "抹", "拖", "甩", "撞", "踩", "弯腰", "蹲", "站着", "回应", "应声",
)
ACTING_HINT = "改写成 大动作 + 手上的事 + 肌肉（拍桌、跨步逼近、手停住、咬牙、鼻息、眼先到头后转）"
HAND_WORDS = ("手", "双手", "一手", "两手", "空手", "右手", "左手", "拇指", "指尖", "手指", "手臂", "手腕", "手掌")
EYE_LIFE = "眼先到位、头后转；有眨眼、有呼吸起伏"
FACE_SCALES = {"medium", "close", "otc"}
FACE_COVERAGE = {"reaction", "close", "otc", "ots"}
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _t(value: Any) -> str:
    return str(value or "").strip()


def normalize_acting(raw: Any) -> dict[str, dict[str, str]]:
    """{角色: {want, hide, business, muscle, change}} with every field a stripped string."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for who, item in raw.items():
        name = _t(who)
        if not name:
            continue
        if isinstance(item, str):
            item = {"muscle": item}
        if not isinstance(item, dict):
            continue
        fields = {key: _t(item.get(key)) for key in ACTING_FIELDS}
        if any(fields.values()):
            out[name] = fields
    return out


def emotion_adjectives_in(text: str) -> list[str]:
    """Emotion words found in a visible-acting string, in order, deduped."""
    found: list[str] = []
    for match in _EMOTION_RE.finditer(_t(text)):
        word = match.group(0)
        if word not in found:
            found.append(word)
    return found


def physical_expression(expr: str) -> str:
    """Keep the visible part of an expression string; drop the feeling words.

    「琳怕得眼瞪大」→「琳眼瞪大」. 「春安横脸讥」→ "" (nothing the camera can do).
    """
    text = _t(expr)
    if not text:
        return ""
    if "无脸" in text or "无人" in text:
        return text
    cleaned = _EMOTION_RE.sub("", text)
    # A feeling word took its particle with it (怕得 / 急得); drop any particle left dangling at a clause end.
    cleaned = re.sub(r"[得地](?=(?:$|[，。；、]))", "", cleaned)
    cleaned = cleaned.strip("，。、 ")
    if not any(token in cleaned for token in PHYSICAL_TOKENS):
        return ""
    return cleaned


def acting_warnings(shots: list[dict]) -> list[str]:
    """`acting_adjective` warnings for expression / business / muscle / change."""
    out: list[str] = []
    for shot in shots or []:
        sid = _t(shot.get("shot_id")) or "?"
        checks: list[tuple[str, str]] = []
        if _t(shot.get("expression")):
            checks.append(("expression", _t(shot.get("expression"))))
        for who, item in normalize_acting(shot.get("acting")).items():
            for key in VISIBLE_FIELDS:
                if item.get(key):
                    checks.append((f"acting.{who}.{key}", item[key]))
        for field, text in checks:
            words = emotion_adjectives_in(text)
            if words:
                out.append(f"{sid} acting_adjective 「{'、'.join(words)}」 in {field}; {ACTING_HINT}")
    return out


def shows_face(shot: dict, spec: Optional[dict] = None) -> bool:
    """Medium / close framing with a person facing the lens enough to read a face."""
    spec = spec or {}
    scale = _t(spec.get("shot_size") or shot.get("scale"))
    coverage = _t(shot.get("coverage_type"))
    facing = _t(spec.get("body_facing") or shot.get("body_facing"))
    if facing in ("无人", "背对镜头"):
        return False
    if scale in FACE_SCALES or coverage in FACE_COVERAGE:
        return True
    return False


def acting_sentence(name: str, item: dict[str, str]) -> str:
    """「琳：想{want}；藏着{hide}；手上{business}；{muscle}；{change}。」 — only the parts given."""
    bits: list[str] = []
    if item.get("want"):
        bits.append(f"想{item['want'].rstrip('。')}")
    if item.get("hide"):
        bits.append(f"藏着{item['hide'].rstrip('。')}")
    if item.get("business"):
        business = item["business"].rstrip("。")
        # 「手上双手握车把」 reads twice; keep the prefix only when the business does not already name the hand.
        bits.append(business if business.startswith(HAND_WORDS) else f"手上{business}")
    if item.get("muscle"):
        bits.append(item["muscle"].rstrip("。"))
    if item.get("change"):
        bits.append(item["change"].rstrip("。"))
    if not bits:
        return ""
    return f"{name}：{'；'.join(bits)}。"


def merge_acting(table_acting: Any, override: Any) -> dict[str, dict[str, str]]:
    """Table row acting with the 7a frame-description acting laid over it, field by field.

    7a is the second descriptive layer under the shot, so a non-empty field there wins;
    empty 7a fields keep what the table said.
    """
    merged = {name: dict(fields) for name, fields in normalize_acting(table_acting).items()}
    for name, fields in normalize_acting(override).items():
        target = merged.setdefault(name, {})
        for key, value in fields.items():
            if value:
                target[key] = value
    return {name: fields for name, fields in merged.items() if any(fields.values())}


def text_acting_warnings(sid: str, fields: dict[str, str]) -> list[str]:
    """`acting_adjective` warnings for free-text frame-description fields (one_paragraph, still_*, micro_expression…)."""
    out: list[str] = []
    for field, text in fields.items():
        words = emotion_adjectives_in(text)
        if words:
            out.append(f"{sid or '?'} acting_adjective 「{'、'.join(words)}」 in {field}; {ACTING_HINT}")
    return out


def compile_acting_zh(
    shot: dict,
    spec: Optional[dict] = None,
    *,
    in_frame: Optional[list[str]] = None,
    speakers: Optional[list[str]] = None,
    override: Any = None,
) -> list[str]:
    """CHARACTER ACTING sentences for the motion prompt.

    - one sentence per character with acting fields (table row, 7a `acting` laid over it);
    - eye-life default when a face is readable and that character has no `muscle`;
    - reaction rule when the shot has a line and a second in-frame character.
    """
    acting = merge_acting(shot.get("acting"), override)
    people = [_t(n) for n in (in_frame or []) if _t(n)]
    talkers = [_t(n) for n in (speakers or []) if _t(n)]
    out: list[str] = []
    face = shows_face(shot, spec)
    for name in list(dict.fromkeys(people + list(acting))):
        item = acting.get(name) or {}
        sentence = acting_sentence(name, item) if item else ""
        if face and not item.get("muscle") and (name in people or not people):
            sentence = (sentence.rstrip("。") + "；" if sentence else f"{name}：") + EYE_LIFE + "。"
        if sentence:
            out.append(sentence)
    if talkers and people:
        listeners = [n for n in people if n not in talkers]
        if listeners:
            who = "、".join(listeners) if len(listeners) <= 2 else "在画的其他人"
            out.append(f"对方话没说完，{who}的脸已经在答。")
    return out
