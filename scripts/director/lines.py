"""Dialogue gate (台词关, gate L): Chinese working lines, spoken Khmer, timing and AI-tell lint.

Chinese is the working language the human reviews in; Khmer is what Cambodian viewers hear.
Each line is written in spoken Khmer from what it has to do (speaker -> listener, register),
not word for word from the Chinese, by Gemini through the local `agy` CLI. A literal
back-translation lets a Chinese reader check the meaning. A shot must hold the longer of the
Chinese take (Seedance native speech) and the Khmer dub (a voice clone of that take).

Revisions found at this gate (de-AI a line, add an inner line, drop one) are proposals on the
row (`zh_new` / `add` / `drop` / `kind_new`). The Khmer is written for the proposed text, so
the reviewer sees what will ship. `apply_revisions` writes them back into the writer artifact
(and the shot table when one exists) after the human approves; the gate cannot lock while a
proposal is pending.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from .shot_table import (
    CHARS_PER_SEC,
    KHMER_CONSONANT,
    KM_LETTERS_PER_SEC,
    KM_PAUSE_SEC,
    consecutive_fragments,
    dialogue_seconds,
    needed_seconds,
    sentence_units,
    store_duration,
)

SCHEMA = "lines-v1"
ARTIFACT = "lines.json"
PROMPT_VERSION = "lines-km-v1"
SPOKEN_KINDS = ("dialogue", "inner", "narration", "intro")
CAPTION = "caption"
KIND_ALIASES = {
    "inner_voice": "inner",
    "os": "inner",
    "monologue": "inner",
    "character_intro": "intro",
    "vo": "narration",
}
KIND_ZH = {"dialogue": "对白", "inner": "内心", "narration": "旁白", "intro": "出场", CAPTION: "字幕"}
DEFAULT_KM_MODEL = "gemini-3.8-flash-high"
KM_ENGINE = "agy"
# On-screen Khmer text: letters a viewer reads per second, plus a beat to find the line.
CAPTION_READ_CPS = 12.0
CAPTION_READ_PAD = 0.6
MAX_LINES_PER_CALL = 40
# On camera the mouth moves for the Chinese take; the Khmer dub may run this much longer before it shows.
LIP_TOLERANCE_SEC = 0.6

# --- AI tells in the Chinese working line ------------------------------------------------

NOT_X_BUT_Y = re.compile(
    r"不是[^，。！？；…\n]{1,14}?[，。！？；…]+\s*(?:而)?是(?!不是)|不是[^，。！？；…\n]{1,12}?而是"
)
X_NOT_Y = re.compile(r"是[^，。！？；…\n]{1,12}，\s*(?:而)?不是")
TRIPLE_LIST = re.compile(r"一[一-鿿]{1,5}、一[一-鿿]{1,5}、一[一-鿿]{1,5}")
CALQUES = (
    "你最好是对的",
    "我们需要谈谈",
    "这不是你的错",
    "该死的",
    "见鬼",
    "让我们",
    "我向你保证",
    "你是认真的吗",
    "给我一个理由",
    "我的天哪",
    "干得漂亮",
    "你做到了",
    "听着，",
)
EXPLAIN_WORDS = ("也就是说", "换句话说", "这意味着", "这说明", "这证明", "原来如此")
PREACH_WORDS = ("命运", "人生", "意义", "信念", "救赎")
SPOKEN_NUMBER = re.compile(r"[0-9]{3,}|[〇零一二三四五六七八九]{3,}")
# Length is not a fault. A clause with no pause in it is: nobody says 24 characters in one breath.
# (012 EP01 had the opposite problem: 6 of 16 lines were five characters or fewer and the scene read like telegrams.)
BREATH_LIMIT = {"dialogue": 22, "inner": 26, "narration": 30, "intro": 36}
SHORT_LINE = 6
TELEGRAM_SHARE = 0.5
_PUNCT = re.compile(r"[\s，。！？；：、“”‘’…—（）()!?.,·\-]")

# --- Khmer text the voice clone has to read ----------------------------------------------

KM_DIGIT = re.compile(r"[0-9០-៩]")
HAN = re.compile(r"[一-鿿]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
AGENT_SIGNER = re.compile(r"claude|opus|sonnet|haiku|gemini|gpt|codex|agent|\bai\b|bot|助手|模型", re.I)


def _t(value: Any) -> str:
    return str(value or "").strip()


def human_signer(name: Any) -> bool:
    """A review is signed by a person, never by the model that wrote the lines."""
    text = _t(name)
    return bool(text) and not AGENT_SIGNER.search(text)


def normalize_kind(value: Any) -> str:
    raw = _t(value).lower() or "dialogue"
    raw = KIND_ALIASES.get(raw, raw)
    return raw if raw in SPOKEN_KINDS or raw == CAPTION else "dialogue"


def effective_zh(row: dict) -> str:
    return _t(row.get("zh_new")) or _t(row.get("zh"))


def effective_kind(row: dict) -> str:
    return normalize_kind(row.get("kind_new") or row.get("kind"))


def pending_change(row: dict) -> str:
    """What this row still asks the writer artifact to do: '', 'revise', 'add', 'drop' or 'kind'."""
    if row.get("add"):
        return "add"
    if row.get("drop"):
        return "drop"
    if _t(row.get("zh_new")) and _t(row.get("zh_new")) != _t(row.get("zh")):
        return "revise"
    if _t(row.get("kind_new")) and normalize_kind(row.get("kind_new")) != normalize_kind(row.get("kind")):
        return "kind"
    return ""


# --- timing --------------------------------------------------------------------------------


def khmer_letters(text: Any) -> int:
    return len(KHMER_CONSONANT.findall(_t(text)))


def khmer_seconds(text: Any, kind: str = "dialogue") -> float:
    """Spoken Khmer seconds, calibrated on a real voice-clone dub (see shot_table.KM_LETTERS_PER_SEC)."""
    letters = khmer_letters(text)
    if not letters:
        return 0.0
    rate = KM_LETTERS_PER_SEC.get(normalize_kind(kind), KM_LETTERS_PER_SEC["dialogue"])
    return round(letters / rate + KM_PAUSE_SEC, 1)


def caption_read_seconds(text: Any) -> float:
    letters = khmer_letters(text)
    return round(letters / CAPTION_READ_CPS + CAPTION_READ_PAD, 1) if letters else 0.0


def zh_mouth_seconds(text: Any) -> float:
    """How long the mouth moves for a Chinese take (no breath allowance)."""
    return round(len(_PUNCT.sub("", _t(text))) / CHARS_PER_SEC, 1)


def km_voice_seconds(text: Any, kind: str = "dialogue") -> float:
    """How long the Khmer voice runs (no breath allowance)."""
    letters = khmer_letters(text)
    rate = KM_LETTERS_PER_SEC.get(normalize_kind(kind), KM_LETTERS_PER_SEC["dialogue"])
    return round(letters / rate, 1) if letters else 0.0


# --- lint ----------------------------------------------------------------------------------


def _flag(code: str, msg: str, level: str = "warn") -> dict:
    return {"code": code, "level": level, "msg": msg}


def _spoken_len(text: str) -> int:
    return len(_PUNCT.sub("", text))


def _equation(text: str) -> bool:
    """`A，就是B` said as a maxim. `不是A，就是B` (either/or) and `…，就是这个` (pointing) are ordinary speech."""
    for sentence in re.split(r"[。！？…]+", text):
        head, sep, tail = sentence.partition("，就是")
        tail = tail.strip()
        if not sep or not tail or "不是" in head or _spoken_len(head) < 2:
            continue
        if tail[0] in "这那他她它你我谁":
            continue
        return True
    return False


def lint_zh(text: Any, kind: str = "dialogue") -> list[dict]:
    """Patterns that make a working line read as written by a model, or swell in Khmer."""
    line = _t(text)
    kind = normalize_kind(kind)
    if not line or kind == CAPTION:
        return []
    flags: list[dict] = []
    if NOT_X_BUT_Y.search(line):
        flags.append(_flag("不是X是Y", "“不是 X，是 Y”是 AI 最常用的句式；直接说是什么"))
    elif X_NOT_Y.search(line):
        flags.append(_flag("是X不是Y", "“是 X，不是 Y”同样是 AI 句式；直接说"))
    if _equation(line):
        flags.append(_flag("格言等式", "“A，就是 B”像格言，吵架、下命令没人这么说"))
    if TRIPLE_LIST.search(line):
        flags.append(_flag("三连排比", "三样东西排成一串像写出来的；口语一般只说要紧的"))
    for phrase in CALQUES:
        if phrase in line:
            flags.append(_flag("翻译腔", f"“{phrase.rstrip('，')}”是外语直译的说法"))
            break
    for word in EXPLAIN_WORDS:
        if word in line:
            flags.append(_flag("解释腔", f"“{word}”在给观众讲道理；让画面或下一句去交代"))
            break
    for word in PREACH_WORDS:
        if word in line:
            flags.append(_flag("点题", f"“{word}”容易变成说教，检查是不是在总结主题", "hint"))
            break
    limit = BREATH_LIMIT.get(kind, 22)
    longest = max((_spoken_len(c) for c in re.split(r"[，。！？；…—,!?;]", line)), default=0)
    if longest > limit:
        flags.append(_flag("一口气", f"有一截 {longest} 字中间没有停顿，一口气说不完；加一个停顿或拆成两句（不用砍短）"))
    if SPOKEN_NUMBER.search(line):
        flags.append(_flag("数字", "年份、数字在高棉语里要读全，明显变长；能放字幕就别念", "hint"))
    return flags


def lint_km(text: Any, kind: str = "dialogue") -> list[dict]:
    """Khmer the voice clone reads. Digits and Han characters are misread; Latin needs a check."""
    km = _t(text)
    kind = normalize_kind(kind)
    if not km:
        return [_flag("缺高棉语", "这句还没有高棉语", "error")]
    flags: list[dict] = []
    if HAN.search(km):
        flags.append(_flag("混汉字", "高棉语里混了汉字", "error"))
    if kind != CAPTION and KM_DIGIT.search(km):
        flags.append(_flag("要念的数字", "要念出来的句子里有数字，克隆模型会读错；写成高棉语读法", "error"))
    if LATIN_WORD.search(km):
        flags.append(_flag("拉丁字母", "高棉语里夹拉丁字母，确认配音要这样念"))
    return flags


# --- rows from the writer artifact ---------------------------------------------------------


def writer_rows(writer: Optional[dict]) -> list[dict]:
    """Every line a viewer hears or reads, in script order. Ids match shot_table.writer_dialogue_records."""
    rows: list[dict] = []
    for scene in (writer or {}).get("scenes") or []:
        sid = _t(scene.get("scene_id"))
        for index, item in enumerate(scene.get("dialogue") or [], start=1):
            if not isinstance(item, dict):
                continue
            line = _t(item.get("line"))
            if not line:
                continue
            speaker = _t(item.get("speaker_id") or item.get("character") or item.get("id") or item.get("speaker"))
            rows.append({
                "line_id": _t(item.get("line_id")) or f"{sid}:d{index:02d}",
                "scene_id": sid,
                "kind": normalize_kind(item.get("line_kind")),
                "speaker": speaker,
                "to": _t(item.get("to")),
                "purpose": _t(item.get("purpose")),
                "parenthetical": _t(item.get("parenthetical")),
                "zh": line,
            })
        for index, cap in enumerate(scene.get("captions") or [], start=1):
            text = _t(cap.get("text") if isinstance(cap, dict) else cap)
            if not text:
                continue
            rows.append({
                "line_id": f"{sid}:c{index:02d}",
                "scene_id": sid,
                "kind": CAPTION,
                "caption_kind": _t(cap.get("kind")) if isinstance(cap, dict) else "",
                # A name card (caption kind=intro) names its person; Gemini needs to know who.
                "speaker": _t(cap.get("character")) if isinstance(cap, dict) else "",
                "to": "",
                "purpose": "",
                "parenthetical": "",
                "zh": text,
            })
    return rows


def writer_digest(writer: Optional[dict]) -> str:
    """Fingerprint of what the Khmer was written from: ids, kinds, speakers, listeners, text."""
    payload = [(r["line_id"], r["kind"], r["speaker"], r["to"], r["zh"]) for r in writer_rows(writer)]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def row_units(row: dict) -> list[str]:
    """Chinese pieces the Khmer is aligned to: sentences, or the explicit per-shot split of a revision."""
    split = [_t(piece) for piece in (row.get("zh_new_split") or []) if _t(piece)]
    if split:
        return split
    text = effective_zh(row)
    if effective_kind(row) == CAPTION:
        return [text] if text else []
    return sentence_units(text)


def km_key(row: dict) -> str:
    """Khmer stays valid while what it was written from stays the same."""
    payload = [
        PROMPT_VERSION,
        effective_kind(row),
        _t(row.get("speaker")),
        _t(row.get("to")),
        _t(row.get("parenthetical")),
        row_units(row),
    ]
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def row_km(row: dict) -> str:
    return " ".join(_t(u.get("km")) for u in row.get("units") or [] if _t(u.get("km")))


def row_back(row: dict) -> str:
    return "".join(_t(u.get("back_zh")) for u in row.get("units") or [] if _t(u.get("back_zh")))


def _fresh_units(row: dict, old: Optional[dict]) -> list[dict]:
    """Aligned Chinese units; keep the old Khmer only when nothing it was written from changed."""
    units = [{"zh": piece, "km": "", "back_zh": ""} for piece in row_units(row)]
    row["km_key"] = ""
    row["km_note"] = ""
    if old and _t(old.get("km_key")) and old.get("km_key") == km_key(row):
        old_units = old.get("units") or []
        if len(old_units) == len(units):
            for unit, prev in zip(units, old_units):
                unit["km"] = _t(prev.get("km"))
                unit["back_zh"] = _t(prev.get("back_zh"))
            row["km_key"] = old["km_key"]
            row["km_note"] = _t(old.get("km_note"))
            if old.get("km_tightened"):
                row["km_tightened"] = True
    return units


PROPOSAL_KEYS = ("zh_new", "zh_new_split", "kind_new", "drop", "why", "shot_id", "after", "waive", "zh_follows_km")


def build_lines(
    writer: dict,
    *,
    previous: Optional[dict] = None,
    table: Optional[dict] = None,
    episode_no: int = 1,
) -> dict:
    """Draft (or refresh) the gate artifact. Cached Khmer survives; proposals on unchanged lines survive."""
    prev_rows = {_t(r.get("line_id")): r for r in (previous or {}).get("lines") or [] if isinstance(r, dict)}
    rows: list[dict] = []
    for base in writer_rows(writer):
        row = dict(base)
        old = prev_rows.get(row["line_id"])
        if old and _t(old.get("zh")) == row["zh"] and normalize_kind(old.get("kind")) == row["kind"]:
            for key in PROPOSAL_KEYS:
                if key in old:
                    row[key] = old[key]
            for key in ("to", "purpose"):
                if not row.get(key) and _t(old.get(key)):
                    row[key] = _t(old.get(key))
        row["units"] = _fresh_units(row, old)
        rows.append(row)
    # Lines the gate proposes to add live only here until applied.
    for old in (previous or {}).get("lines") or []:
        if not isinstance(old, dict) or not old.get("add"):
            continue
        row = {key: old[key] for key in old if key not in ("units", "flags", "km_flags")}
        row["kind"] = normalize_kind(old.get("kind"))
        row["zh"] = ""
        row["units"] = _fresh_units(row, old)
        anchor = _t(old.get("after"))
        at = next((i + 1 for i, r in enumerate(rows) if r["line_id"] == anchor), None)
        if at is None:
            at = next((i for i, r in enumerate(rows) if r["scene_id"] == _t(old.get("scene_id"))), len(rows))
        while at < len(rows) and rows[at].get("add") and rows[at].get("after") == anchor:
            at += 1
        rows.insert(at, row)
    data = {
        "schema": SCHEMA,
        "episode_no": int(episode_no or 1),
        "status": "draft",
        "writer_digest": writer_digest(writer),
        "km_engine": _t((previous or {}).get("km_engine")),
        "km_prompt_version": PROMPT_VERSION,
        "timing_source": _t((previous or {}).get("timing_source")) or "estimate",
        "reviewed_by": "",
        "reviewed_at": "",
        "blind_listening": dict((previous or {}).get("blind_listening") or {}),
        "glossary": list((previous or {}).get("glossary") or []),
        "lines": rows,
    }
    refresh(data, table)
    return data


def refresh(data: dict, table: Optional[dict] = None) -> dict:
    """Recompute keys, timing, shot fit and lint. Never touches the Khmer itself."""
    for row in data.get("lines") or []:
        kind = effective_kind(row)
        row["km"] = row_km(row)
        row["km_back"] = row_back(row)
        if row.get("drop"):
            row.update({"zh_sec": 0.0, "km_sec": 0.0, "need_sec": 0.0})
        elif kind == CAPTION:
            row.update({"zh_sec": 0.0, "km_sec": 0.0, "need_sec": caption_read_seconds(row["km"]), "read_sec": caption_read_seconds(row["km"])})
        else:
            zh_sec = dialogue_seconds([effective_zh(row)])
            km_sec = khmer_seconds(row["km"], kind) if row["km"] else 0.0
            for unit in row.get("units") or []:
                unit["zh_sec"] = dialogue_seconds([_t(unit.get("zh"))])
                unit["km_sec"] = khmer_seconds(unit.get("km"), kind) if _t(unit.get("km")) else 0.0
            row.update({"zh_sec": zh_sec, "km_sec": km_sec, "need_sec": round(max(zh_sec, km_sec), 1)})
            row["lip_gap"] = round(km_voice_seconds(row["km"], kind) - zh_mouth_seconds(effective_zh(row)), 1) if row["km"] else 0.0
        row["flags"] = [] if row.get("drop") else lint_zh(effective_zh(row), kind)
        row["km_flags"] = [] if row.get("drop") else lint_km(row["km"], kind)
    data["shots"] = shot_fit(table, data) if table else []
    on_camera = lip_synced_ids(data, table)
    for row in data.get("lines") or []:
        gap = float(row.get("lip_gap") or 0)
        if _t(row.get("line_id")) in on_camera and gap > LIP_TOLERANCE_SEC:
            row["km_flags"].append(_flag("口型", f"对口型：高棉语比中文嘴型长 {gap}s，嘴停了声音还在；先压短高棉语（--tighten），或把这句挪到背影、过肩、听的人脸上"))
    return data


def lip_synced_ids(data: dict, table: Optional[dict] = None) -> set[str]:
    """Lines a viewer will see spoken: on-camera shots after the proposals, or every dialogue line before a storyboard."""
    if not table:
        return {
            _t(r.get("line_id")) for r in data.get("lines") or []
            if not r.get("drop") and effective_kind(r) == "dialogue"
        }
    out: set[str] = set()
    for fit in data.get("shots") or shot_fit(table, data):
        if fit.get("delivery_after") == "on_camera":
            out.update(ref["line_id"] for ref in fit.get("lines") or [] if ref.get("kind") == "dialogue")
    return out


def tighten_targets(data: dict, table: Optional[dict] = None) -> dict[str, float]:
    """line_id -> seconds the Khmer voice should fit in, for on-camera lines that outrun the mouth."""
    on_camera = lip_synced_ids(data, table)
    out: dict[str, float] = {}
    for row in data.get("lines") or []:
        lid = _t(row.get("line_id"))
        if lid in on_camera and float(row.get("lip_gap") or 0) > LIP_TOLERANCE_SEC:
            out[lid] = round(zh_mouth_seconds(effective_zh(row)) + LIP_TOLERANCE_SEC, 1)
    return out


# --- shots ---------------------------------------------------------------------------------


def _dialogue_items(shot: dict) -> list[dict]:
    return [item for item in shot.get("dialogue_ref") or [] if isinstance(item, dict) and _t(item.get("line"))]


def _speaks(row: dict) -> bool:
    return not row.get("add") and effective_kind(row) != CAPTION and bool(_t(row.get("zh")))


def item_owners(table: Optional[dict], data: dict) -> list[tuple[dict, dict, str]]:
    """(shot, dialogue_ref item, line_id) for every line a shot speaks today.

    An item belongs to the writer line it equals or is a consecutive-sentence fragment of
    (the storyboard only splits lines at sentence ends). Same text from two speakers is
    told apart by speaker; an explicit line_id wins.
    """
    rows = [r for r in data.get("lines") or [] if _speaks(r)]
    ids = {_t(r.get("line_id")) for r in rows}
    out: list[tuple[dict, dict, str]] = []
    for shot in (table or {}).get("shots") or []:
        for item in _dialogue_items(shot):
            lid = _t(item.get("line_id"))
            if lid not in ids:
                text = _t(item.get("line"))
                found = [r for r in rows if text == _t(r.get("zh")) or text in consecutive_fragments(_t(r.get("zh")))]
                who = _t(item.get("speaker_id") or item.get("character"))
                if len(found) > 1 and who:
                    found = [r for r in found if _t(r.get("speaker")) == who] or found
                lid = _t(found[0].get("line_id")) if found else ""
            out.append((shot, item, lid))
    return out


def unit_shots(table: Optional[dict], data: dict) -> dict[tuple[str, int], str]:
    """(line_id, unit index) -> shot_id once the gate's proposals are applied."""
    owners = item_owners(table, data)
    out: dict[tuple[str, int], str] = {}
    for row in data.get("lines") or []:
        if row.get("drop") or effective_kind(row) == CAPTION:
            continue
        lid = _t(row.get("line_id"))
        units = row.get("units") or []
        if row.get("add") or _t(row.get("shot_id")):
            for index in range(len(units)):
                out[(lid, index)] = _t(row.get("shot_id"))
            continue
        mine = [(_t(shot.get("shot_id")), _t(item.get("line"))) for shot, item, owner in owners if owner == lid]
        homes = [sid for i, (sid, _text) in enumerate(mine) if sid not in [m[0] for m in mine[:i]]]
        change = pending_change(row)
        if not change or change == "kind":
            for index, unit in enumerate(units):
                piece = _t(unit.get("zh"))
                out[(lid, index)] = next((sid for sid, text in mine if piece and piece in text), homes[0] if homes else "")
        elif row.get("zh_new_split") and len(homes) == len(units):
            for index, sid in enumerate(homes):
                out[(lid, index)] = sid
        else:
            for index in range(len(units)):
                out[(lid, index)] = homes[0] if homes else ""
    return out


def _shot_lines(table: Optional[dict], data: dict) -> dict[str, list[dict]]:
    """shot_id -> what it says after the proposals: line_id, kind, Chinese and Khmer for its units."""
    homes = unit_shots(table, data)
    out: dict[str, list[dict]] = {}
    for row in data.get("lines") or []:
        lid = _t(row.get("line_id"))
        kind = effective_kind(row)
        picked: dict[str, list[dict]] = {}
        for index, unit in enumerate(row.get("units") or []):
            sid = homes.get((lid, index))
            if sid:
                picked.setdefault(sid, []).append(unit)
        for sid, units in picked.items():
            km = " ".join(_t(u.get("km")) for u in units if _t(u.get("km")))
            out.setdefault(sid, []).append({
                "line_id": lid,
                "kind": kind,
                "speaker": _t(row.get("speaker")),
                "line": "".join(_t(u.get("zh")) for u in units),
                "km": km,
                "km_sec": khmer_seconds(km, kind) if km else 0.0,
            })
    return out


def shot_fit(table: Optional[dict], data: dict) -> list[dict]:
    """Per shot with lines: what it says after the proposals, Chinese vs Khmer seconds, whether it holds."""
    spoken = _shot_lines(table, data)
    out: list[dict] = []
    for shot in (table or {}).get("shots") or []:
        sid = _t(shot.get("shot_id"))
        refs = spoken.get(sid) or []
        if not refs and not _dialogue_items(shot):
            continue
        duration = float(shot.get("duration_sec") or 0)
        need = needed_seconds({**shot, "dialogue_ref": [{"line": r["line"], "km_sec": r["km_sec"]} for r in refs]}) if refs else 0.0
        zh_need = needed_seconds({**shot, "dialogue_ref": [{"line": r["line"]} for r in refs]}) if refs else 0.0
        before = _t(shot.get("dialogue_delivery")) or "none"
        after = _delivery(refs, [r["kind"] for r in refs], before)
        fits = need <= duration + 0.05
        out.append({
            "shot_id": sid,
            "duration_sec": duration,
            "delivery": before,
            "delivery_after": after,
            "lines": refs,
            "zh_need_sec": zh_need,
            "need_sec": need,
            "fits": fits,
            "suggest_sec": duration if fits else _half_up(need),
        })
    return out


def _half_up(seconds: float) -> float:
    import math

    return math.ceil(float(seconds) * 2 - 1e-9) / 2


def expected_km_sec(table: dict, data: dict) -> dict[int, float]:
    """id(dialogue_ref item) -> the Khmer seconds the shot table must carry for it."""
    spoken = _shot_lines(table, data)
    out: dict[int, float] = {}
    for shot, item, lid in item_owners(table, data):
        if not lid:
            continue
        refs = [r for r in spoken.get(_t(shot.get("shot_id"))) or [] if r["line_id"] == lid]
        if refs:
            out[id(item)] = refs[0]["km_sec"]
    return out


def stamp_line_timing(table: dict, data: dict) -> list[str]:
    """Write each dialogue_ref's line_id and Khmer seconds into the shot table. Returns shot ids touched."""
    expected = expected_km_sec(table, data)
    touched: list[str] = []
    for shot, item, lid in item_owners(table, data):
        value = expected.get(id(item))
        if value is None:
            continue
        if item.get("km_sec") != value or _t(item.get("line_id")) != lid:
            item["km_sec"] = value
            item["line_id"] = lid
            sid = _t(shot.get("shot_id"))
            if sid not in touched:
                touched.append(sid)
    return touched


def timing_stamp_errors(table: dict, data: Optional[dict]) -> list[str]:
    """Storyboard gate: every line's Khmer seconds must match the dialogue gate."""
    if not data or not data.get("lines"):
        return []
    errors: list[str] = []
    expected = expected_km_sec(table, data)
    for shot, item, lid in item_owners(table, data):
        sid = _t(shot.get("shot_id"))
        want = expected.get(id(item))
        if not lid or want is None:
            errors.append(f"{sid} line not in the dialogue gate: {_t(item.get('line'))[:24]}")
            continue
        have = item.get("km_sec")
        try:
            same = have is not None and abs(float(have) - float(want)) <= 0.05
        except (TypeError, ValueError):
            same = False
        if not same:
            errors.append(f"{sid} Khmer seconds {have} != dialogue gate {want}; run build_lines.py --stamp")
    return errors


# --- validation ----------------------------------------------------------------------------


def validate_lines(data: dict, writer: Optional[dict] = None, table: Optional[dict] = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict) or _t(data.get("schema")) != SCHEMA:
        return [f"lines artifact must be schema {SCHEMA}"], []
    rows = [r for r in data.get("lines") or [] if isinstance(r, dict)]
    if not rows:
        return ["lines artifact has no lines"], []
    ids = [_t(r.get("line_id")) for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append("duplicate line_id: " + ", ".join(dupes))
    if writer is not None:
        if _t(data.get("writer_digest")) != writer_digest(writer):
            errors.append("台词表和剧本对不上（剧本改过）；重跑 build_lines.py")
        known = {r["line_id"] for r in writer_rows(writer)}
        missing = [lid for lid in known if lid not in ids]
        if missing:
            errors.append("剧本里有台词没进台词表：" + ", ".join(missing[:6]))
        stray = [r["line_id"] for r in rows if not r.get("add") and r.get("line_id") not in known]
        if stray:
            errors.append("台词表里有剧本没有的句子：" + ", ".join(stray[:6]))
    pending = [f"{_t(r.get('line_id'))}({pending_change(r)})" for r in rows if pending_change(r)]
    if pending:
        errors.append(f"{len(pending)} 处改稿还没写回剧本：" + "、".join(pending[:8]))
    for row in rows:
        lid = _t(row.get("line_id"))
        if row.get("drop"):
            continue
        if not effective_zh(row):
            errors.append(f"{lid} 中文是空的")
        units = row.get("units") or []
        if not units:
            errors.append(f"{lid} 没有分句")
        if [_t(u.get("zh")) for u in units] != row_units(row):
            errors.append(f"{lid} 分句和中文对不上；重跑 build_lines.py")
        for unit in units:
            if not _t(unit.get("km")):
                errors.append(f"{lid} 缺高棉语")
                break
            if not _t(unit.get("back_zh")):
                errors.append(f"{lid} 缺回译")
                break
        if _t(row.get("km_key")) and _t(row.get("km_key")) != km_key(row):
            errors.append(f"{lid} 高棉语是按旧中文写的；重跑 build_lines.py --khmer")
        waived = {_t(w) for w in row.get("waive") or []}
        for flag in lint_km(row_km(row), effective_kind(row)):
            if flag["code"] == "缺高棉语":
                continue
            if flag["level"] == "error":
                errors.append(f"{lid} {flag['msg']}")
            elif flag["code"] not in waived:
                warnings.append(f"{lid} {flag['msg']}")
        for flag in lint_zh(effective_zh(row), effective_kind(row)):
            if flag["code"] not in waived:
                warnings.append(f"{lid} [{flag['code']}] {flag['msg']}")
        if row.get("add") and table is not None and not _t(row.get("shot_id")):
            errors.append(f"{lid} 新加的台词要写放进哪一镜（shot_id）")
        if effective_kind(row) == CAPTION and _t(row.get("caption_kind")) == "intro":
            if not _t(row.get("speaker")):
                errors.append(f"{lid} 人物名片要写是谁（captions 里写 character）")
            if row_km(row) and "·" not in row_km(row):
                errors.append(f"{lid} 人物名片的高棉语要写成“名字 · 身份”")
    for lid, target in tighten_targets(data, table).items():
        row = next(r for r in rows if _t(r.get("line_id")) == lid)
        warnings.append(f"{lid} 对口型：高棉语比中文嘴型长 {row.get('lip_gap')}s（目标 {target}s 内）；--tighten 压短，或挪到背影 / 过肩 / 听的人脸上")
    if table is not None:
        for fit in shot_fit(table, data):
            if not fit["fits"]:
                warnings.append(
                    f"{fit['shot_id']} 台词要 {fit['need_sec']}s，镜头只有 {fit['duration_sec']}s；分镜加到 {fit['suggest_sec']}s 或把高棉语改短"
                )
    warnings.extend(rhythm_warnings(rows))
    if _t(data.get("timing_source")) != "measured":
        warnings.append("高棉语时长是估算（按实测语速折算），克隆模型可用后实测")
    return errors, warnings


def rhythm_warnings(rows: list[dict]) -> list[str]:
    """A scene whose spoken lines are mostly tiny reads like telegrams; people talk in longs and shorts."""
    out: list[str] = []
    by_scene: dict[str, list[str]] = {}
    for row in rows:
        if row.get("drop") or effective_kind(row) != "dialogue":
            continue
        by_scene.setdefault(_t(row.get("scene_id")) or _t(row.get("line_id")).split(":")[0], []).append(effective_zh(row))
    for scene, texts in by_scene.items():
        if len(texts) < 3:
            continue
        short = [t for t in texts if _spoken_len(t) <= SHORT_LINE]
        if len(short) / len(texts) >= TELEGRAM_SHARE:
            out.append(
                f"{scene} 有 {len(short)}/{len(texts)} 句台词不超过 {SHORT_LINE} 个字，像打电报；正常说话有长有短，"
                "有半句、重复、称呼、语气词和接话，别为了快把话砍成两三个字"
            )
    return out


def review_errors(data: dict) -> list[str]:
    """The human sign-off the gate needs on top of a clean artifact."""
    errors: list[str] = []
    if _t(data.get("status")) != "reviewed":
        errors.append("台词表还没审（status 不是 reviewed）")
    if not human_signer(data.get("reviewed_by")):
        errors.append("台词表要人签字（reviewed_by 写审核人，不能是模型）")
    return errors


# --- Khmer through Gemini (agy) ------------------------------------------------------------


def _card_line(cid: str, card: dict, bible_char: dict) -> str:
    bits = [f"{cid} {_t(card.get('name')) or _t(bible_char.get('name'))}"]
    if _t(card.get("km_name")):
        bits.append(f"高棉名 {_t(card.get('km_name'))}")
    if _t(card.get("identity")):
        bits.append(f"身份：{_t(card.get('identity'))}")
    elif _t(bible_char.get("want")):
        bits.append(f"想要：{_t(bible_char.get('want'))}")
    if _t(card.get("speech_style")):
        bits.append(f"说话方式：{_t(card.get('speech_style'))}")
    return "- " + "；".join(bits)


def khmer_prompt(
    rows: list[dict],
    *,
    writer: dict,
    cards: Optional[dict] = None,
    glossary: Optional[list] = None,
    targets: Optional[dict[str, float]] = None,
) -> str:
    cards = cards or {}
    bible = (writer or {}).get("series_bible") or {}
    bible_chars = {_t(c.get("id")): c for c in bible.get("characters") or [] if isinstance(c, dict)}
    speakers: list[str] = []
    for row in rows:
        for cid in (_t(row.get("speaker")), _t(row.get("to"))):
            if cid and cid not in speakers and (cid in cards or cid in bible_chars):
                speakers.append(cid)
    people = [_card_line(cid, cards.get(cid) or {}, bible_chars.get(cid) or {}) for cid in speakers]
    names = [f"{_t(c.get('name'))} = {_t(c.get('km_name'))}" for c in cards.values() if _t(c.get("km_name")) and _t(c.get("name"))]
    terms = [f"{_t(g.get('zh'))} = {_t(g.get('km'))}" for g in glossary or [] if isinstance(g, dict) and _t(g.get("zh")) and _t(g.get("km"))]
    headings = {_t(s.get("scene_id")): _t(s.get("heading")) for s in (writer or {}).get("scenes") or []}
    by_scene: dict[str, list[dict]] = {}
    for row in rows:
        by_scene.setdefault(_t(row.get("scene_id")), []).append(row)
    body: list[str] = []
    for sid, group in by_scene.items():
        body.append(f"[{sid} {headings.get(sid, '')}]")
        for row in group:
            item = {
                "id": _t(row.get("line_id")),
                "kind": effective_kind(row),
                "speaker": _t(row.get("speaker")),
                "to": _t(row.get("to")),
                "purpose": _t(row.get("purpose")),
                "how": _t(row.get("parenthetical")),
                "units": row_units(row),
            }
            if item["kind"] == CAPTION:
                item["caption_kind"] = _t(row.get("caption_kind"))
            if (targets or {}).get(item["id"]):
                item["current_km"] = [_t(u.get("km")) for u in row.get("units") or []]
                item["target_sec"] = targets[item["id"]]
            body.append(json.dumps({k: v for k, v in item.items() if v}, ensure_ascii=False))
    return "\n".join([
        "不要使用任何工具，不要读写文件，直接在回复里输出一个 JSON 对象，不要代码块。",
        "",
        "你是柬埔寨本土短剧编剧。这部剧拍给柬埔寨观众看，成片说高棉语；中文只是制作组的工作稿。",
        f"一句话故事：{_t(bible.get('logline'))}",
        "",
        "任务：下面每一句，写出这个人此刻真会说出口的高棉语。",
        "1. 先看 purpose（这句要干什么）和 speaker → to（谁对谁说），再写高棉语。可以换句式、可以更短，不要逐字翻译中文。",
        "2. 口语，不要书面语、公文词、翻译腔。称呼和代词按身份、年龄、亲疏来选。对国王说话或讲到国王用王室用语；对僧人用僧侣用语。1549 年的人不用现代词；现代金边的年轻人可以用现代口语。",
        "3. 要念出来的句子（kind 不是 caption）里不许有阿拉伯数字或高棉数字：年份、数字都写成高棉语读法，例如 1549 写成 មួយពាន់ប្រាំរយសែសិបប្រាំបួន。caption 是屏幕上的字，可以用高棉数字，要简短。",
        "4. kind=inner 是心里话，第一人称，短；narration、intro 是讲故事的人在说。how 是这句怎么说（比如电话里、喊）。caption_kind=intro 是人物名片（人物第一次出场叠在画面上的两行字）：写成“名字 · 身份”，中间用“ · ”隔开；名字用给定写法；身份一眼读完、不超过六个词，古代人物用古代叫法。",
        "5. units 是这句的中文分段。你的 units 要一一对应：一样多、一样的顺序。每段给 km（高棉语）和 back_zh（把你的高棉语逐字回译成中文，保留高棉语语序，不要润色）。",
        "6. note_zh 只在这几种情况写一句中文，否则留空：中文工作稿里有高棉语不这么说的东西（成语、称呼、文化不对）；你改了意思；这句中文本身像翻译腔或 AI 腔。",
        "7. 带 target_sec 的句子是对口型的镜头：画面里嘴只动 target_sec 秒。在 current_km 的基础上改短，念出来不超过 target_sec 秒：换更短的说法，去掉可有可无的语气词、重复的称呼；意思、身份感和这句的力度不能丢。实在改不短就原样返回。",
        "",
        "人名、地名、专有名词一律用这些写法：",
        *(f"- {n}" for n in names + terms),
        "",
        "人物：",
        *people,
        "",
        "台词（每行一个 JSON）：",
        *body,
        "",
        '输出：{"lines":[{"id":"…","units":[{"km":"…","back_zh":"…"}],"note_zh":""}]}',
    ])


def run_agy(prompt: str, *, model: str = DEFAULT_KM_MODEL, timeout: int = 600) -> str:
    """One headless Gemini turn through the local `agy` CLI, from an empty folder so it cannot touch the repo."""
    with tempfile.TemporaryDirectory(prefix="lines-agy-") as folder:
        proc = subprocess.run(
            ["agy", "-p", prompt, "--model", model, "--print-timeout", f"{int(timeout)}s", "--disable-slash-commands"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=int(timeout) + 60,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"agy failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-600:]}")
    return proc.stdout


def parse_json_reply(text: str) -> dict:
    raw = _t(text)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini reply has no JSON object")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Gemini reply is not a JSON object")
    return data


def needs_khmer(row: dict) -> bool:
    if row.get("drop"):
        return False
    units = row.get("units") or []
    return not units or any(not _t(u.get("km")) or not _t(u.get("back_zh")) for u in units)


def tighten_khmer(
    data: dict,
    targets: dict[str, float],
    *,
    writer: dict,
    cards: Optional[dict] = None,
    model: str = DEFAULT_KM_MODEL,
    runner: Optional[Callable[[str], str]] = None,
) -> dict[str, tuple[float, float]]:
    """Ask Gemini to shorten on-camera Khmer toward the Chinese mouth. Keeps a rewrite only if it is shorter.

    Returns line_id -> (voice seconds before, after).
    """
    runner = runner or (lambda prompt: run_agy(prompt, model=model))
    rows = [r for r in data.get("lines") or [] if _t(r.get("line_id")) in targets and not needs_khmer(r)]
    out: dict[str, tuple[float, float]] = {}
    for start in range(0, len(rows), MAX_LINES_PER_CALL):
        chunk = rows[start : start + MAX_LINES_PER_CALL]
        prompt = khmer_prompt(chunk, writer=writer, cards=cards, glossary=data.get("glossary"), targets=targets)
        answers = {_t(a.get("id")): a for a in parse_json_reply(runner(prompt)).get("lines") or [] if isinstance(a, dict)}
        for row in chunk:
            lid = _t(row.get("line_id"))
            units = (answers.get(lid) or {}).get("units") or []
            kind = effective_kind(row)
            before = km_voice_seconds(row_km(row), kind)
            if len(units) != len(row.get("units") or []) or any(not _t((u or {}).get("km")) or not _t((u or {}).get("back_zh")) for u in units):
                out[lid] = (before, before)
                continue
            candidate = " ".join(_t(u.get("km")) for u in units)
            after = km_voice_seconds(candidate, kind)
            if after < before:
                for unit, got in zip(row["units"], units):
                    unit["km"] = _t(got.get("km"))
                    unit["back_zh"] = _t(got.get("back_zh"))
                note = _t(answers[lid].get("note_zh"))
                row["km_note"] = note or _t(row.get("km_note"))
                row["km_tightened"] = True
                row["km_key"] = km_key(row)
            out[lid] = (before, min(before, after))
    return out


def sync_prompt(rows: list[dict], *, writer: dict, cards: Optional[dict] = None) -> str:
    """Ask for a Chinese working line that says what the Khmer says, as long as the Khmer runs."""
    names = {cid: _t(c.get("name")) for cid, c in (cards or {}).items()}
    body = []
    for row in rows:
        kind = effective_kind(row)
        units = []
        for unit in row.get("units") or []:
            seconds = km_voice_seconds(unit.get("km"), kind)
            units.append({
                "km": _t(unit.get("km")),
                "back_zh": _t(unit.get("back_zh")),
                "zh_now": _t(unit.get("zh")),
                "zh_chars": max(2, round(seconds * CHARS_PER_SEC)),
            })
        body.append(json.dumps({
            "id": _t(row.get("line_id")),
            "speaker": names.get(_t(row.get("speaker")), _t(row.get("speaker"))),
            "to": names.get(_t(row.get("to")), _t(row.get("to"))),
            "purpose": _t(row.get("purpose")),
            "units": units,
        }, ensure_ascii=False))
    return "\n".join([
        "不要使用任何工具，不要读写文件，直接在回复里输出一个 JSON 对象，不要代码块。",
        "",
        "这是一部柬埔寨短剧。下面每句的高棉语（km）已经定稿，是对口型的镜头：画面里的人先用中文演一遍，再换成高棉语配音。",
        "中文说得太短，嘴停了高棉语还在响。请给每段写一句中文工作稿 zh：",
        "1. 意思和这句高棉语一样（back_zh 是逐字回译，zh_now 是现在的中文，供参考）。",
        "2. 是中国人会说的自然口语，不是逐字翻译，没有翻译腔，不用“不是……是……”这种句式。",
        "3. 字数（不算标点）接近 zh_chars，这样中文念出来和高棉语一样长。可以加称呼、语气词、把话说完整，但不能加新信息。",
        "4. 每段一句，句末带标点；段数和输入一样。",
        "",
        *body,
        "",
        '输出：{"lines":[{"id":"…","units":[{"zh":"…"}]}]}',
    ])


def sync_chinese(
    data: dict,
    ids: list[str],
    *,
    writer: dict,
    cards: Optional[dict] = None,
    model: str = DEFAULT_KM_MODEL,
    runner: Optional[Callable[[str], str]] = None,
) -> dict[str, str]:
    """Rewrite the Chinese working line to the Khmer's length; the Khmer stays. Returns line_id -> new Chinese.

    The new Chinese becomes a proposal (`zh_new_split`) re-keyed to the existing Khmer, so the
    next build keeps the Khmer instead of rewriting it from the longer Chinese.
    """
    runner = runner or (lambda prompt: run_agy(prompt, model=model))
    rows = [r for r in data.get("lines") or [] if _t(r.get("line_id")) in set(ids) and not needs_khmer(r)]
    out: dict[str, str] = {}
    if not rows:
        return out
    answers = {_t(a.get("id")): a for a in parse_json_reply(runner(sync_prompt(rows, writer=writer, cards=cards))).get("lines") or [] if isinstance(a, dict)}
    for row in rows:
        lid = _t(row.get("line_id"))
        got = [_t((u or {}).get("zh")) for u in (answers.get(lid) or {}).get("units") or []]
        units = row.get("units") or []
        if len(got) != len(units) or not all(got):
            continue
        if any(sentence_units(piece) != [piece] for piece in got):
            continue
        before = effective_zh(row)
        row["zh_new"] = "".join(got)
        row["zh_new_split"] = got
        for unit, piece in zip(units, got):
            unit["zh"] = piece
        if row["zh_new"] == _t(row.get("zh")):
            row.pop("zh_new", None)
            row.pop("zh_new_split", None)
        reason = "中文工作稿照高棉语的长度和说法写：对口型时中文嘴型和高棉语配音一样长"
        row["why"] = (_t(row.get("why")) + "；" + reason) if _t(row.get("why")) and reason not in _t(row.get("why")) else (_t(row.get("why")) or reason)
        row["zh_follows_km"] = True
        row["km_key"] = km_key(row)
        out[lid] = f"{before} → {effective_zh(row)}"
    return out


def fill_khmer(
    data: dict,
    *,
    writer: dict,
    cards: Optional[dict] = None,
    model: str = DEFAULT_KM_MODEL,
    runner: Optional[Callable[[str], str]] = None,
    force: bool = False,
) -> list[str]:
    """Ask Gemini for every row without Khmer. Returns ids still missing after one retry."""
    runner = runner or (lambda prompt: run_agy(prompt, model=model))
    for row in data.get("lines") or []:
        if not row.get("units") and not row.get("drop"):
            row["units"] = [{"zh": piece, "km": "", "back_zh": ""} for piece in row_units(row)]
    todo = [r for r in data.get("lines") or [] if force and not r.get("drop") or needs_khmer(r)]
    missing: list[str] = []
    for attempt in range(2):
        if not todo:
            break
        for start in range(0, len(todo), MAX_LINES_PER_CALL):
            chunk = todo[start : start + MAX_LINES_PER_CALL]
            reply = parse_json_reply(runner(khmer_prompt(chunk, writer=writer, cards=cards, glossary=data.get("glossary"))))
            answers = {_t(item.get("id")): item for item in reply.get("lines") or [] if isinstance(item, dict)}
            for row in chunk:
                answer = answers.get(_t(row.get("line_id")))
                units = (answer or {}).get("units") or []
                if not answer or len(units) != len(row.get("units") or []):
                    continue
                for unit, got in zip(row["units"], units):
                    unit["km"] = _t((got or {}).get("km"))
                    unit["back_zh"] = _t((got or {}).get("back_zh"))
                row["km_note"] = _t(answer.get("note_zh"))
                row["km_key"] = km_key(row) if not needs_khmer(row) else ""
        todo = [r for r in todo if needs_khmer(r)]
        force = False
    missing = [_t(r.get("line_id")) for r in todo]
    data["km_engine"] = f"{KM_ENGINE}:{model}"
    data["km_prompt_version"] = PROMPT_VERSION
    return missing


# --- applying approved proposals -----------------------------------------------------------


def _freeze_ids(scene: dict) -> None:
    """Pin positional ids before inserting, so a new line never renumbers its neighbours."""
    sid = _t(scene.get("scene_id"))
    for index, item in enumerate(scene.get("dialogue") or [], start=1):
        if isinstance(item, dict) and _t(item.get("line")) and not _t(item.get("line_id")):
            item["line_id"] = f"{sid}:d{index:02d}"


def _delivery(refs: list[dict], kinds: list[str], before: str) -> str:
    """Every line is voiced in the generation; the storyboard's off-screen choices (phone, off_camera) stand."""
    if not refs:
        return "none"
    if before in ("off_camera", "phone", "inner", "narration"):
        return before
    if kinds and all(k == "inner" for k in kinds):
        return "inner"
    if kinds and all(k == "narration" for k in kinds):
        return "narration"
    # legacy `post` meant "mouth not shown": still voiced, from off screen
    return "off_camera" if before == "post" else "on_camera"


def apply_revisions(writer: dict, data: dict, table: Optional[dict] = None) -> list[str]:
    """Write approved proposals into the writer artifact (and the shot table). Returns a change log.

    The Khmer on each row was written for the proposed text, so it stays; the row drops its
    proposal keys and becomes an ordinary line. Listener and purpose notes are copied into
    the writer so the next Khmer pass has them. Shot durations are left to `retime_shots`.
    """
    log: list[str] = []
    scenes = {_t(s.get("scene_id")): s for s in writer.get("scenes") or []}
    for scene in scenes.values():
        _freeze_ids(scene)
    shots = list((table or {}).get("shots") or [])
    owned: dict[str, list[tuple[dict, dict]]] = {}
    for shot, item, lid in item_owners(table, data) if table else []:
        if lid:
            owned.setdefault(lid, []).append((shot, item))
    homes = unit_shots(table, data) if table else {}
    keep: list[dict] = []
    for row in data.get("lines") or []:
        change = pending_change(row)
        lid = _t(row.get("line_id"))
        if not change:
            keep.append(row)
            continue
        scene = scenes.get(_t(row.get("scene_id")))
        if scene is None:
            raise ValueError(f"{lid}: scene {row.get('scene_id')} not in writer")
        if normalize_kind(row.get("kind")) == CAPTION or effective_kind(row) == CAPTION:
            if change != "revise":
                raise ValueError(f"{lid}: captions can only be reworded here; add or drop them in the writer")
            index = int(lid.rsplit(":c", 1)[-1]) - 1
            text = effective_zh(row)
            caption = (scene.get("captions") or [])[index]
            if isinstance(caption, dict):
                caption["text"] = text
            else:
                scene["captions"][index] = text
            log.append(f"{lid} 字幕：{_t(row.get('zh'))} → {text}")
            for key in ("zh_new", "zh_new_split", "kind_new"):
                row.pop(key, None)
            row["zh"] = text
            keep.append(row)
            continue
        dialogue = scene.setdefault("dialogue", [])
        old_text = _t(row.get("zh"))
        mine = owned.get(lid) or []
        if change == "drop":
            scene["dialogue"] = [item for item in dialogue if not (isinstance(item, dict) and _t(item.get("line_id")) == lid)]
            for shot, item in mine:
                shot["dialogue_ref"] = [ref for ref in shot.get("dialogue_ref") or [] if ref is not item]
                log.append(f"{shot.get('shot_id')} 不再说 {lid}")
            log.append(f"{lid} 删除：{old_text}")
            continue
        new_text = effective_zh(row)
        kind = effective_kind(row)
        if change == "add":
            entry = {"line_id": lid, "character": _t(row.get("speaker")), "speaker": _t(row.get("speaker")), "line": new_text, "line_kind": kind}
            for key in ("to", "purpose", "parenthetical"):
                if _t(row.get(key)):
                    entry[key] = _t(row.get(key))
            anchor = _t(row.get("after"))
            at = 0
            if anchor:
                at = next((i + 1 for i, item in enumerate(dialogue) if isinstance(item, dict) and _t(item.get("line_id")) == anchor), len(dialogue))
            dialogue.insert(at, entry)
            log.append(f"{lid} 新增（{KIND_ZH.get(kind, kind)}）：{new_text}")
        else:
            item = next((x for x in dialogue if isinstance(x, dict) and _t(x.get("line_id")) == lid), None)
            if item is None:
                raise ValueError(f"{lid}: not in writer scene {row.get('scene_id')}")
            item["line"] = new_text
            item["line_kind"] = kind
            if change == "kind":
                log.append(f"{lid} 改为{KIND_ZH.get(kind, kind)}：{new_text}")
            else:
                log.append(f"{lid} 改稿：{old_text} → {new_text}")
        if shots:
            placed: dict[str, list[str]] = {}
            for index, unit in enumerate(row.get("units") or []):
                sid = homes.get((lid, index))
                if sid:
                    placed.setdefault(sid, []).append(_t(unit.get("zh")))
            by_shot: dict[str, list[dict]] = {}
            for shot, item in mine:
                by_shot.setdefault(_t(shot.get("shot_id")), []).append(item)
            for shot in shots:
                sid = _t(shot.get("shot_id"))
                old_refs = by_shot.get(sid) or []
                pieces = placed.get(sid)
                if old_refs and not pieces:
                    shot["dialogue_ref"] = [ref for ref in shot.get("dialogue_ref") or [] if all(ref is not o for o in old_refs)]
                    log.append(f"{sid} 不再说 {lid}")
                elif pieces:
                    text = "".join(pieces)
                    if old_refs:
                        first = old_refs[0]
                        first["line"] = text
                        first["line_id"] = lid
                        first.pop("km_sec", None)
                        shot["dialogue_ref"] = [ref for ref in shot.get("dialogue_ref") or [] if all(ref is not o for o in old_refs[1:])]
                    else:
                        shot.setdefault("dialogue_ref", []).append({"character": _t(row.get("speaker")), "line": text, "line_id": lid})
                    if not old_refs or text != old_text:
                        log.append(f"{sid} 台词 → {text}")
        for key in ("zh_new", "zh_new_split", "kind_new", "add", "after", "shot_id"):
            row.pop(key, None)
        row["zh"] = new_text
        row["kind"] = kind
        keep.append(row)
    data["lines"] = keep
    # Listener and purpose travel with the script from now on.
    for row in keep:
        scene = scenes.get(_t(row.get("scene_id")))
        item = next((x for x in (scene or {}).get("dialogue") or [] if isinstance(x, dict) and _t(x.get("line_id")) == _t(row.get("line_id"))), None)
        if item is None:
            continue
        for key in ("to", "purpose"):
            if _t(row.get(key)) and not _t(item.get(key)):
                item[key] = _t(row.get(key))
    kinds_by_id = {_t(r.get("line_id")): effective_kind(r) for r in keep}
    owner_of = {id(item): lid for _shot, item, lid in item_owners(table, data)} if table else {}
    for shot in shots:
        refs = _dialogue_items(shot)
        kinds = [kinds_by_id.get(_t(item.get("line_id")) or owner_of.get(id(item), ""), "dialogue") for item in refs]
        before = _t(shot.get("dialogue_delivery"))
        after = _delivery(refs, kinds, before)
        if before != after:
            shot["dialogue_delivery"] = after
            log.append(f"{shot.get('shot_id')} 口型 {before or 'none'} → {after}")
    data["writer_digest"] = writer_digest(writer)
    data["status"] = "draft"
    data["reviewed_by"] = ""
    data["reviewed_at"] = ""
    refresh(data, table)
    if table is not None:
        stamp_line_timing(table, data)
    return log


def retime_shots(table: dict, data: dict) -> list[str]:
    """Lengthen shots that cannot hold their lines (Khmer included). Never shortens. Returns a log."""
    log: list[str] = []
    fit = {row["shot_id"]: row for row in shot_fit(table, data)}
    for shot in table.get("shots") or []:
        row = fit.get(_t(shot.get("shot_id")))
        if row and not row["fits"]:
            shot["duration_sec"] = store_duration(row["suggest_sec"], 0)
            log.append(f"{shot.get('shot_id')} → {shot['duration_sec']}s")
    if log:
        table["total_sec"] = store_duration(sum(float(s.get("duration_sec") or 0) for s in table.get("shots") or []), 0)
    return log


# --- disk ----------------------------------------------------------------------------------


def lines_artifact_name(episode: Any = 1) -> str:
    from .pipeline import episode_artifact_name

    return episode_artifact_name(ARTIFACT, episode)


def read_lines(prod: Path, episode: Any = 1) -> dict:
    from .pipeline import read_artifact

    return read_artifact(prod, lines_artifact_name(episode))


def load_glossary(prod: Path) -> list[dict]:
    path = Path(prod) / "01-bible" / "khmer-glossary.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = data.get("terms") if isinstance(data, dict) else data
    return [t for t in terms or [] if isinstance(t, dict)]


def gate_ready(prod: Path, episode: Any = 1) -> tuple[bool, str]:
    from .pipeline import episode_artifact_name, read_artifact

    data = read_lines(prod, episode)
    if not data:
        return False, "还没有台词表（build_lines.py）"
    writer = read_artifact(prod, episode_artifact_name("writer.json", episode))
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode)) or None
    errors, _warnings = validate_lines(data, writer, table)
    if errors:
        return False, errors[0]
    signoff = review_errors(data)
    if signoff:
        return False, signoff[0]
    spoken = [r for r in data.get("lines") or [] if effective_kind(r) != CAPTION]
    return True, f"台词表 {len(spoken)} 句已审（{_t(data.get('reviewed_by'))}）"
