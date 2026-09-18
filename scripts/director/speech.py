"""Seedance native speech: voice cards, descriptors, the compiled audio block.

Seedance 2.0 on Ark speaks a line when it sits in quotes inside the prompt with
its language and manner (琳用普通话急促地说：“…”). Native speech languages are
zh/en/ja/ko/es/fr/de. Khmer is not native: it needs the multimodal
`reference_audio` mode, which is mutually exclusive with `first_frame`. This
pipeline keeps first_frame, so `km` raises instead of silently muting a shot.

Voice cards and descriptors are written by hand in `01-bible/CHARACTERS.md`
(`- **声音卡**：…` / `- **外形卡**：…` under each `## **slug** · 名` header).
`.pipeline/voice_cards.json` is the machine copy compile writes from that page.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

SPEECH_MODES = ("seedance_native", "post_dub")
DEFAULT_SPEECH_MODE = "seedance_native"
NATIVE_SPEECH_LANGUAGES = ("zh", "en", "ja", "ko", "es", "fr", "de")
DEFAULT_DIALOGUE_LANGUAGE = "zh"
LANGUAGE_ZH = {
    "zh": "普通话",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "es": "西班牙语",
    "fr": "法语",
    "de": "德语",
}
VOICE_CARDS_ARTIFACT = "voice_cards.json"
VOICE_CARDS_SCHEMA = "voice-cards-v1"
CHARACTERS_MD = "01-bible/CHARACTERS.md"
REFERENCE_LOCK = "100% 以参考图为准"
# Manner the audio block uses when the table gives none. 独白 is muttered, 口白 is plain speech.
TRACK_MANNER = (("独白", "低声自语地"), ("口白", ""))
DEFAULT_SOUND_BEDS = (
    ("gate", "厂区晨间底噪，远处车间机器声"),
    ("corridor", "走廊底噪，远处车间机器声"),
    ("storeroom", "闷热杂物间的房间底噪"),
    ("line", "车间缝纫机运转声"),
    ("factory", "车间机器底噪"),
    ("office", "办公室空调底噪"),
    ("river", "河岸水声与晚风"),
)
FALLBACK_SOUND_BED = "本场环境底噪"

_HEADER = re.compile(r"^#{2,3}\s+\*\*([\w-]+)\*\*\s*·\s*([^\s/]+)")
_VOICE = re.compile(r"^\s*-\s+\*\*声音卡\*\*\s*[:：]\s*(.+?)\s*$")
_DESCRIPTOR = re.compile(
    r"^\s*-\s+\*\*外形卡(?:[·（(]\s*([\w-]+)\s*[)）]?)?\*\*(?:[（(][^（）()]*[）)])?\s*[:：]\s*(.*?)\s*$"
)
_SUB_STATE = re.compile(r"^\s{2,}-\s+([\w-]+)\s*[:：]\s*(.+?)\s*$")


class SpeechLanguageError(ValueError):
    """dialogue_language the first-frame path cannot speak natively."""


def _t(value: Any) -> str:
    return str(value or "").strip()


def language_label(language: str) -> str:
    return LANGUAGE_ZH.get(_t(language) or DEFAULT_DIALOGUE_LANGUAGE, _t(language))


def check_dialogue_language(
    language: str,
    *,
    speech_mode: str = DEFAULT_SPEECH_MODE,
    uses_first_frame: bool = True,
    shot_id: str = "",
) -> str:
    """Return the language code the package may carry, or raise a clear error.

    `km` is reserved: Seedance cannot speak Khmer natively and `reference_audio`
    (the only Khmer path) is mutually exclusive with `first_frame`.
    """
    code = _t(language).lower() or DEFAULT_DIALOGUE_LANGUAGE
    mode = _t(speech_mode) or DEFAULT_SPEECH_MODE
    if mode not in SPEECH_MODES:
        raise SpeechLanguageError(f"{shot_id or 'shot'} speech_mode 必须是 {list(SPEECH_MODES)}，不是 {mode!r}")
    if mode == "post_dub":
        return code
    if code in NATIVE_SPEECH_LANGUAGES:
        return code
    where = f"{shot_id} " if shot_id else ""
    if code == "km":
        raise SpeechLanguageError(
            f"{where}dialogue_language=km：Seedance 2.0 不能原生说高棉语。高棉语只能走 reference_audio "
            "多模态参考模式，而该模式与 first_frame 互斥；本管线保留 first_frame，所以不能选 km。"
            "改 speech_mode=post_dub（工作轨后期配），或先用 dialogue_language=zh 出原声中文。"
        )
    raise SpeechLanguageError(
        f"{where}dialogue_language={code!r} 不在 Seedance 原生口播语言 {list(NATIVE_SPEECH_LANGUAGES)} 里；"
        "改 speech_mode=post_dub 或换语言。"
    )


def parse_character_cards(text: str) -> dict[str, dict]:
    """cast id -> {name, voice_card, descriptor, descriptor_by_costume} from CHARACTERS.md."""
    out: dict[str, dict] = {}
    current: Optional[dict] = None
    in_descriptor = False
    for raw in _t(text).splitlines():
        head = _HEADER.match(raw)
        if head:
            cid, name = head.group(1), head.group(2)
            current = out.setdefault(cid, {"name": name, "voice_card": "", "descriptor": "", "descriptor_by_costume": {}})
            in_descriptor = False
            continue
        if current is None:
            continue
        voice = _VOICE.match(raw)
        if voice:
            current["voice_card"] = voice.group(1)
            in_descriptor = False
            continue
        desc = _DESCRIPTOR.match(raw)
        if desc:
            state, body = _t(desc.group(1)), _t(desc.group(2))
            if state:
                current["descriptor_by_costume"][state] = body
            elif body:
                current["descriptor"] = body
            in_descriptor = True
            continue
        if in_descriptor:
            sub = _SUB_STATE.match(raw)
            if sub:
                current["descriptor_by_costume"][sub.group(1)] = sub.group(2)
                continue
        if raw.strip().startswith("-") or not raw.strip():
            in_descriptor = False
    for item in out.values():
        if not item["descriptor"] and item["descriptor_by_costume"]:
            item["descriptor"] = next(iter(item["descriptor_by_costume"].values()))
    return {cid: item for cid, item in out.items() if item["voice_card"] or item["descriptor"]}


def load_character_cards(prod: Path) -> dict[str, dict]:
    """Bible page first (source of truth), machine copy second."""
    from .production import load_json, read_text

    cards = parse_character_cards(read_text(prod, CHARACTERS_MD))
    if cards:
        return cards
    data = load_json(prod, f".pipeline/{VOICE_CARDS_ARTIFACT}", {})
    chars = data.get("characters") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for cid, item in (chars or {}).items():
        if not isinstance(item, dict):
            continue
        out[_t(cid)] = {
            "name": _t(item.get("name")),
            "voice_card": _t(item.get("voice_card")),
            "descriptor": _t(item.get("descriptor")),
            "descriptor_by_costume": {
                _t(k): _t(v) for k, v in (item.get("descriptor_by_costume") or {}).items() if _t(v)
            },
        }
    return out


def voice_cards_payload(cards: dict[str, dict]) -> dict:
    return {
        "schema": VOICE_CARDS_SCHEMA,
        "source": CHARACTERS_MD,
        "characters": {cid: dict(item) for cid, item in (cards or {}).items()},
    }


def write_voice_cards(prod: Path, cards: dict[str, dict]) -> dict:
    """Machine copy next to the other lock artifacts. Bible page stays the source."""
    from .pipeline import write_artifact

    return write_artifact(prod, VOICE_CARDS_ARTIFACT, voice_cards_payload(cards))


def cards_by_name(cards: dict[str, dict], cast: Optional[dict[str, str]] = None) -> dict[str, dict]:
    """Display name -> card, so shot rows keyed by 琳 / 春安 resolve without cast ids."""
    out: dict[str, dict] = {}
    for cid, item in (cards or {}).items():
        out[cid] = item
        name = _t(item.get("name"))
        if name:
            out[name] = item
        alias = _t((cast or {}).get(cid))
        if alias:
            out[alias] = item
    return out


def voice_card_for(name: str, cards: dict[str, dict]) -> str:
    item = (cards or {}).get(_t(name)) or {}
    return _t(item.get("voice_card"))


def descriptor_for(name: str, cards: dict[str, dict], costume_state: str = "") -> str:
    """One observable sentence + the reference lock. Costume-state variant when the card has one."""
    item = (cards or {}).get(_t(name)) or {}
    by_state = item.get("descriptor_by_costume") or {}
    body = _t(by_state.get(_t(costume_state))) if _t(costume_state) else ""
    if not body:
        body = _t(item.get("descriptor"))
    if not body:
        return ""
    label = _t(item.get("name")) or _t(name)
    return f"{label}：{body.rstrip('。；;')}；{REFERENCE_LOCK}。"


def sound_bed_for(location_id: str, sets: Optional[dict] = None) -> str:
    """Per-set `sound_bed_zh` from sets.json, else a word-match default."""
    loc = _t(location_id)
    for entry in (sets or {}).get("sets") or []:
        if isinstance(entry, dict) and _t(entry.get("id")) == loc and _t(entry.get("sound_bed_zh")):
            return _t(entry.get("sound_bed_zh"))
    blob = loc.lower()
    for token, bed in DEFAULT_SOUND_BEDS:
        if token in blob:
            return bed
    return FALLBACK_SOUND_BED


def manner_for(item: dict) -> str:
    explicit = _t(item.get("manner") or item.get("tone"))
    if explicit:
        return explicit
    track = _t(item.get("track"))
    for token, manner in TRACK_MANNER:
        if token in track:
            return manner
    return ""


def _joined(names: list[str]) -> str:
    return "、".join(dict.fromkeys(n for n in names if n))


def compile_audio_block(
    lines: list[dict],
    *,
    cards: Optional[dict[str, dict]] = None,
    in_frame: Optional[list[str]] = None,
    key_sfx: Optional[list[str]] = None,
    sound_bed: str = "",
    language: str = DEFAULT_DIALOGUE_LANGUAGE,
) -> str:
    """The only place speech lives. Hell Grind order: voice → quoted line → who stays silent → ambience.

    lines: [{character, line, manner?, track?}] (max two, spoken in order).
    in_frame: display names visible in this shot.
    """
    lang = language_label(language)
    people = [_t(n) for n in (in_frame or []) if _t(n)]
    sfx = [_t(s) for s in (key_sfx or []) if _t(s)]
    bed = _t(sound_bed) or FALLBACK_SOUND_BED
    ambience = "、".join(dict.fromkeys([bed] + sfx))
    spoken = [item for item in (lines or []) if _t((item or {}).get("line"))]
    if not spoken:
        if people:
            return f"画中所有人不说话，嘴闭着。只有环境声：{ambience}。无音乐，无字幕。"
        return f"画中无人开口。只有环境声：{ambience}。无音乐，无字幕。"
    speakers: list[str] = []
    bits: list[str] = []
    for index, item in enumerate(spoken[:2]):
        who = _t(item.get("character") or item.get("speaker")) or "画外音"
        speakers.append(who)
        card = voice_card_for(who, cards or {})
        manner = manner_for(item)
        line = _t(item.get("line")).strip("“”\"")
        offscreen = people and who not in people
        subject = f"{who}画外音" if offscreen else who
        card_bit = f"（{card.rstrip('。')}）" if card else ""
        order = ""
        if len(spoken) > 1:
            order = "先，" if index == 0 else "接着，"
        bits.append(f"{order}{subject}{card_bit}用{lang}{manner}说：“{line}”。")
    if len(spoken) > 1:
        bits.append("两人各只说自己这一句。")
    else:
        bits.append("只说这一句。")
    silent = [n for n in people if n not in speakers]
    if silent:
        bits.append(f"{_joined(silent)}不说话，嘴闭着。")
    elif not people:
        bits.append("画中其他人不说话，嘴闭着。")
    bits.append(f"环境声只保留{ambience}，无音乐，无字幕。")
    return "".join(bits)


def table_says_post_dub(table: Optional[dict]) -> bool:
    """An undeclared table whose every line-carrying shot says dialogue_delivery=post is a post-dub table."""
    shots = [s for s in ((table or {}).get("shots") or []) if isinstance(s, dict)]
    with_lines = [s for s in shots if s.get("dialogue_ref")]
    return bool(with_lines) and all(_t(s.get("dialogue_delivery")) == "post" for s in with_lines)


def speech_mode_for(table: Optional[dict], profile: Optional[dict]) -> str:
    """Table says; else an all-`post` table is post_dub; else native when the model can lip-sync."""
    declared = _t((table or {}).get("speech_mode"))
    if declared in SPEECH_MODES:
        return declared
    if table_says_post_dub(table):
        return "post_dub"
    if (profile or {}).get("native_dialogue_audio"):
        return DEFAULT_SPEECH_MODE
    return "post_dub"
