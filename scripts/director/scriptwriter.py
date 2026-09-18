"""Gate A/C draft writer. Pengcheng script-expert flow, mapped onto productions/.

Writes overview / blueprint / beats / coverage / shots.draft.json only.
Never renders video and never overwrites official shots.json.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from .production import load_json, read_text, save_json, save_shot_draft, write_text
from .reverse import (
    KHMER_DEFAULT_BRIEF,
    _is_placeholder,
    maybe_seed_storyboard_docs,
    seed_asset_folders,
    write_sets_draft,
)

SETUP_CYCLE = ("master", "close", "ots", "single", "close", "insert")
SCALE_FOR_SETUP = {
    "master": "full",
    "close": "close",
    "ots": "med",
    "single": "med",
    "insert": "insert",
}
from .defaults import DEFAULT_ASPECT, production_aspect
from .prompts import camera_for_move, compose_video_prompt, load_template  # noqa: E402

MOVE_WORDS = {
    "static": camera_for_move("static"),
    "push": camera_for_move("push"),
    "pull": camera_for_move("pull"),
    "pan": camera_for_move("pan"),
    "track": camera_for_move("track"),
}
PLACE_HINTS = [
    (re.compile(r"吊桥|城门|causeway|吴哥桥|西参道|木桥|堤桥"), "angkor-causeway"),
    (re.compile(r"回廊|第七面|east-gallery|石廊"), "east-gallery"),
    (re.compile(r"车间|factory|车缝"), "factory-floor"),
    (re.compile(r"走廊|玻璃|办公室|office"), "factory-office"),
    (re.compile(r"黄铁门|厂门|gate"), "factory-gate"),
    (re.compile(r"包间|餐厅|订婚"), "restaurant-private"),
    (re.compile(r"出租|宿舍"), "rental-room"),
    (re.compile(r"borey|豪宅|别墅"), "borey-gate"),
]
NAME_HINTS = [
    (re.compile(r"达拉|dara|守将", re.I), "dara"),
    (re.compile(r"僧人|和尚|monk|老祭司|祭司", re.I), "monk"),
    (re.compile(r"列(?!表)|reat", re.I), "reat"),
    (re.compile(r"蒂雅|teya|妹妹", re.I), "teya"),
    (re.compile(r"索菲娅|sophea|sreymom|女主", re.I), "sophea"),
    (re.compile(r"萨拉|sara|bopha"), "sara"),
    (re.compile(r"皮萨|piseth|heng|主管"), "piseth"),
    (re.compile(r"罗丝|yeay[\s-]*ros|\\bros\\b|kanha|老太太|太祖母", re.I), "ros"),
    (re.compile(r"阿莲|neary"), "neary"),
    (re.compile(r"保镖|guard|bodyguard", re.I), "bodyguard"),
]
SPEAKER_LINE = re.compile(r"^\*?\*?([A-Za-z\u4e00-\u9fff·\.]+)\*?\*?\s*[：:](.+)$")
COVERAGE_HEAD = re.compile(r"^##.*?\b([a-z]+(?:-[a-z0-9]+)+)\b", re.I)
COVERAGE_SHOT = re.compile(
    r"^\|\s*(master|close|ots|insert|single)\s*\|\s*(SH\d+|—|-)?\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|",
    re.I,
)
MOVE_HINTS = [
    (re.compile(r"拉回|拉出|pull", re.I), "pull"),
    (re.compile(r"推|push", re.I), "push"),
    (re.compile(r"摇|pan", re.I), "pan"),
    (re.compile(r"跟|track", re.I), "track"),
]

SYSTEM = """You are the in-house AI video scriptwriter for a Khmer landscape short-drama director desk.
Follow the six-step expert flow, but emit files for THIS pipeline only:

1. Understand: audience is Phnom Penh viewers, default 16:9 landscape, photoreal, no lip-sync.
2. Plan structure: let people land, then conflict, then end hook. Shot count and episode length follow coverage — do not cap at 50-75 seconds or pad to fill a quota. 1-2 real places.
3. Generate shots: one new_info per shot, one camera move, 180-degree axis, coverage master+tighter.
4. Write prompts: English video_prompt using templates/video-prompt-formula.md and templates/camera-moves.md. MiniMax H3 / Grok Imagine only. Not Midjourney, not CogVideoX, not SD --ar.
5. Write copy: Chinese working-track sound. line_kind is intro|dialogue|inner|narration|sms|reaction. speaker is a character slug only for dialogue/inner. Dialogue never enters video_prompt. reaction is a silent 2s listen beat.
6. Self-check: no qipao, no WeChat/RMB plot, no orbit, no burned-in subtitles, no extra people.
If the production already has character folders, reuse those slugs. 罗丝 is ros, never yeay-ros. Prefer coverage.md over inventing a new 6-shot cut.

Return JSON only:
{
  "overview": {"title": "", "seconds": 0, "style": "", "audience": "Phnom Penh 16:9", "platform": "landscape 16:9; duration is the sum of shots"},
  "blueprint_md": "markdown",
  "beats_md": "markdown table 起|止|节拍|新信息|地点|人",
  "coverage_md": "markdown",
  "voiceover_md": "markdown",
  "shots": {
    "episode": "ep01",
    "kind": "shortdrama",
    "aspect": "16:9",
    "shots": [ {director-contract shot objects} ]
  }
}

Each shot MUST include:
id, seconds (4-15), tier (fast|h3, max 3 h3), scale, setup, move, cut, from, derived_from,
facing, expression, blocking, start, scene, characters, new_info, line_kind, speaker, line, caption, on_screen,
frame, last_frame, prompt, lens, axis, camera, action, look, video_prompt, negatives, emotion, sfx,
story_function (hook|advance|climax|end_hook), end (end pose), camera_path, camera_speed, landing, performance, sound_intent.

Rules:
- First shot of a scene: cut=hard, from=null, derived_from="<scene>.blocking"
- Continue in same scene: cut=continue, from=previous id, derived_from=previous id
- Hard cut only when scene changes
- action is start pose -> one motion -> end pose
- start is second-0 stance. Opening/hard-cut may be planted. Continue shots must be mid-action (gesture already underway), English, not an on-marks template, and must differ from the previous start.
- camera matches move; static cannot push/orbit
- video_prompt English, six layers: subject -> action -> scene -> camera move -> light -> style, with start->process->landing. Names setup or scale, names the move, no dialogue text
- names stay Khmer romanization in local track
- line_kind is intro|dialogue|inner|narration|sms|reaction (aliases inner_voice=inner, character_intro=intro). Put one intro in the first 12 seconds. Spoken shots 2-5s from line length. After spoken shots, a 2s silent reaction is allowed.
- speaker is a character slug for dialogue/inner; leave blank for intro/narration/sms.
- Chinese working-track lines stay short; never paste them into video_prompt.
- sound stays in line/caption/sound_intent, never in video_prompt.
"""


class ScriptError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _slug_place(text: str, fallback: str = "factory-floor") -> str:
    blob = text or ""
    for pat, slug in PLACE_HINTS:
        if pat.search(blob):
            return slug
    cleaned = re.sub(r"[^a-z0-9]+", "-", blob.lower()).strip("-")
    return cleaned[:40] or fallback


def _slug_person(text: str, fallback: str = "sophea") -> str:
    blob = text or ""
    for pat, slug in NAME_HINTS:
        if pat.search(blob):
            return slug
    cleaned = re.sub(r"[^a-z0-9]+", "-", blob.lower()).strip("-")
    return cleaned[:32] or fallback


def existing_character_slugs(prod: Path) -> list[str]:
    root = prod / "02-assets" / "characters"
    if not root.exists():
        return []
    return sorted(child.name for child in root.iterdir() if child.is_dir())


def _alias_map(prod: Path) -> dict[str, str]:
    aliases = {slug: slug for _, slug in NAME_HINTS}
    aliases.update(
        {
            "yeay-ros": "ros",
            "yeayros": "ros",
            "yeay": "ros",
            "kanha": "ros",
            "guard": "bodyguard",
            "body-guard": "bodyguard",
        }
    )
    existing = set(existing_character_slugs(prod))
    if "ros" in existing:
        aliases["yeay-ros"] = "ros"
    elif "yeay-ros" in existing:
        aliases["ros"] = "yeay-ros"
    if "bodyguard" in existing:
        aliases["guard"] = "bodyguard"
    return aliases


def align_slug(name: str, prod: Optional[Path] = None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    guessed = _slug_person(raw, raw)
    aliases = _alias_map(prod) if prod else {"yeay-ros": "ros", "guard": "bodyguard"}
    mapped = aliases.get(guessed, guessed)
    if prod:
        existing = existing_character_slugs(prod)
        if mapped in existing:
            return mapped
        if guessed in existing:
            return guessed
    return mapped


def _people(text: str, prod: Optional[Path] = None) -> list[str]:
    found = []
    for pat, slug in NAME_HINTS:
        if pat.search(text or ""):
            mapped = align_slug(slug, prod)
            if mapped and mapped not in found:
                found.append(mapped)
    blob = text or ""
    if prod:
        for slug in existing_character_slugs(prod):
            if re.search(rf"\b{re.escape(slug)}\b", blob, re.I):
                mapped = align_slug(slug, prod)
                if mapped not in found:
                    found.append(mapped)
    if not found:
        found = [align_slug("dara", prod) or "dara"]
    return found


def _guess_move(text: str, setup: str) -> str:
    blob = text or ""
    for pat, move in MOVE_HINTS:
        if pat.search(blob):
            return move
    if setup in {"close", "insert"} and re.search(r"推|更紧|特写", blob):
        return "push"
    return "static"


def parse_coverage_table(markdown: str, prod: Optional[Path] = None) -> list[dict]:
    rows = []
    scene = "factory-floor"
    start = 0
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        head = COVERAGE_HEAD.match(line)
        if head:
            scene = head.group(1).strip().lower()
            continue
        match = COVERAGE_SHOT.match(line)
        if not match:
            continue
        setup, sid, seconds, camera, info = match.groups()
        seconds = max(4, min(15, int(seconds)))
        people_src = " ".join([camera or "", info or ""])
        people = _people(people_src, prod)
        if "阿莲" in (info or "") and "neary" in people and "照片" not in (camera or "") and "闪回" not in (camera or ""):
            people = [p for p in people if p != "neary"]
        rows.append(
            {
                "index": len(rows) + 1,
                "id": sid if sid and sid.startswith("SH") else f"SH{len(rows)+1:03d}",
                "start": start,
                "end": start + seconds,
                "beat": (info or camera or setup).strip(),
                "place": scene,
                "new_info": (info or camera or setup).strip(),
                "people": ",".join(people),
                "setup": setup.lower(),
                "move": _guess_move(camera or "", setup.lower()),
                "camera_note": camera or "",
            }
        )
        start += seconds
    return rows


def parse_beat_table(markdown: str) -> list[dict]:
    rows = []
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if re.search(r"^\|\s*#\s*\|", line) or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        # formats: 起 | 止 | 节拍 | 新信息 | 地点 | 人  OR  # | 秒 | 节拍 | 地点 | 新信息
        if cells[0].isdigit() and len(cells) >= 6 and cells[1].isdigit():
            place = cells[4]
            people = cells[5]
            # 地点应是英文 slug；若第 4 栏才是 slug，说明是旧 5 栏剧本章
            if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", place) and re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", cells[3] or ""):
                start = int(cells[1])
                rows.append(
                    {
                        "index": int(cells[0]),
                        "start": start,
                        "beat": cells[2],
                        "place": cells[3],
                        "new_info": cells[4] if len(cells) > 4 else cells[2],
                        "people": people,
                    }
                )
            else:
                rows.append(
                    {
                        "index": len(rows) + 1,
                        "start": int(cells[0]),
                        "end": int(cells[1]),
                        "beat": cells[2],
                        "new_info": cells[3],
                        "place": place,
                        "people": people,
                    }
                )
        elif cells[0].isdigit() and len(cells) >= 6:
            rows.append(
                {
                    "index": len(rows) + 1,
                    "start": int(cells[0]),
                    "end": int(cells[1]) if cells[1].isdigit() else None,
                    "beat": cells[2],
                    "new_info": cells[3],
                    "place": cells[4],
                    "people": cells[5],
                }
            )
    for i, row in enumerate(rows):
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else row["start"] + 8
        row["end"] = int(row.get("end") or nxt)
        if row["end"] <= row["start"]:
            row["end"] = row["start"] + 6
    return rows


def parse_dialogue(markdown: str) -> list[dict]:
    lines = []
    for raw in (markdown or "").splitlines():
        match = SPEAKER_LINE.match(raw.strip())
        if not match:
            continue
        speaker, spoken = match.group(1).strip(), match.group(2).strip()
        spoken = spoken.strip("* ").strip()
        if speaker in {"旁白", "字幕"}:
            kind = "narration"
        elif "心里" in speaker or speaker.endswith("内心"):
            kind = "inner"
            speaker = speaker.replace("心里", "").replace("内心", "").strip("（）() ")
        elif speaker in {"简介", "出场", "出场简介"}:
            kind = "intro"
            speaker = ""
        else:
            kind = "dialogue"
        pieces = [spoken]
        match = re.search(r"(扣你[^。]*明天不用来了。?)", spoken)
        if match and match.start() > 0:
            head = spoken[: match.start()].strip("，, ")
            tail = match.group(1)
            pieces = [head, tail]
        character = align_slug(speaker)
        for piece in pieces:
            lines.append({"speaker": speaker, "text": piece, "kind": kind, "character": character})
    return lines


def _seconds(start: int, end: int) -> int:
    span = int(end) - int(start)
    if span <= 0:
        return 6
    return max(4, min(12, span))


def _setup_for(index: int, new_info: str, is_first: bool) -> str:
    info = (new_info or "").lower()
    if is_first:
        return "master"
    if any(token in info for token in ("银铃", "铃", "工牌", "短信", "钱", "insert")):
        return "insert"
    if any(token in info for token in ("脸", "眼睛", "特写", "抬头", "认")):
        return "close"
    return SETUP_CYCLE[index % len(SETUP_CYCLE)]


def visible_action(beat: dict) -> str:
    blob = " ".join(
        str(beat.get(key) or "")
        for key in ("camera_note", "new_info", "beat", "place")
    )
    # Map visible objects/verbs from the beat text. Do not bake a production's plot.
    rules = (
        (r"铜铃", "The small copper bell at the waist sounds as the oxcart rolls; leave the motion unfinished"),
        (r"牛车|抬她上车|抬上牛车|送上牛车", "Guards lift her onto the oxcart; the palm-leaf rubbing stays in her arms; leave the motion unfinished"),
        (r"拓片|棕叶|旧誓", "The palm-leaf rubbing turns toward the listener; leave the motion unfinished"),
        (r"蕉叶|王令|两片叶子", "Someone lifts a banana-leaf royal order; the other person does not take it yet; leave the motion unfinished"),
        (r"第三片|未出生|守哪一", "Someone asks which order to keep; the listener starts to answer; leave the motion unfinished"),
        (r"点名列|守墙|砍谁", "Someone points a wall guard into place; the spear-butt starts to slam; leave the motion unfinished"),
        (r"不肯走|妹妹要留下|我不走", "She plants her feet in the doorway, bells still, refusing to leave; leave the motion unfinished"),
        (r"石墙被换过|墙色不对|第七面", "Fingers stop on the paler replacement stone of the seventh wall; leave the motion unfinished"),
        (r"字在肚子里|换不走", "The speaker keeps one palm on the swapped stone while answering; leave the motion unfinished"),
        (r"烧桥|吊桥|退路", "A torch holds to the oil-soaked causeway rope; the first flame takes; leave the motion unfinished"),
        (r"银铃|领口|半枚莲", "Hold on the broken lotus silver bell at the collarbone; the chain shifts once; leave the motion unfinished"),
        (r"侧脸|阿莲|认眼|抬头", "Ros leans toward the right-hand glass; Sophea's head lifts in the lit workshop beyond"),
        (r"路过|廊中|保镖", "Yeay Ros stops mid-corridor and looks through the glass at right; the bodyguard holds a half-step behind"),
        (r"忍泪|不跪|不能等", "Sophea holds her tears, chin lifted, and does not kneel"),
        (r"砸箱|开除|当众罚", "Piseth slams the defect box onto the floor at her feet and jabs her off the line"),
        (r"深处|走来|主管来了", "Piseth walks from the deep aisle with a defect box; Sophea and Sara keep sewing"),
        (r"挽袖|替你|替做", "Sophea rolls her left sleeve once and pulls the unfinished school uniforms onto her table"),
        (r"哭|丢工|校服", "Sara cries at the front sewing machine; Sophea stands still in the aisle beside the uniform pile"),
    )
    for pat, action in rules:
        if re.search(pat, blob):
            return action
    info = str(beat.get("new_info") or beat.get("beat") or "this beat")
    info_en = re.sub(r"[㐀-鿿]+", " ", info)
    info_en = re.sub(r"\s+", " ", info_en).strip(" /") or "this beat"
    return f"Play one visible beat for {info_en}; leave the motion unfinished"


def visible_start(scene: str, beat: dict, people: list[str], setup: str, prev: Optional[dict]) -> str:
    blob = " ".join(str(beat.get(key) or "") for key in ("camera_note", "new_info", "beat"))
    names = ", ".join(people[:3]) or "the on-screen person"
    if scene == "angkor-causeway" or re.search(r"吊桥|城门|causeway", blob):
        if re.search(r"打晕|牛车|拓片", blob):
            return "Dara at the west gate; two guards already lifting Teya onto the oxcart; palm-leaf rubbing still in her arms"
        if re.search(r"不肯走|妹妹|我不走", blob):
            return "Teya in sampot at the west gate, a small copper bell at her waist, palm-leaf rubbing in both arms, facing Dara"
        if re.search(r"点名|守墙|列", blob):
            return "Dara in the gate mouth pointing; Reat among the wall guards, spear grounded"
        if re.search(r"叶子|王令|旧誓|第三片", blob):
            return "Saffron-robed monk in the smoke holding a banana-leaf order and a palm-leaf rubbing; Dara still at the burning timber bridge, torch down"
        return "Dara at the west causeway timber bridge, torch to the planks; civilians already on the south road, no one looking back"
    if scene == "east-gallery" or re.search(r"回廊|第七面|gallery", blob):
        if re.search(r"肚子|换不走", blob):
            return "Monk half a step behind Dara at the seventh wall; Dara's palm still on the paler stone"
        return "Dara alone at the seventh east-gallery wall, palm on the paler replacement stone, night, almost no torch"
    if scene == "angkor-causeway" or re.search(r"吊桥|城门|causeway", blob):
        return (
            "Angkor west causeway at dusk, oil smoke, burning ropes, dry-season dust, "
            "civilians on the south road, Khmer stone lions, no modern skyline"
        )
    if scene == "east-gallery" or re.search(r"回廊|第七面|gallery", blob):
        return (
            "Angkor east gallery at night, carved sandstone, almost no torch, "
            "seventh wall paler than its neighbors, match LOOK.md"
        )
    if scene == "factory-office" or re.search(r"走廊|玻璃|office", blob):
        if re.search(r"银铃|领口|半枚|铃", blob) or setup == "insert":
            return "Broken lotus silver bell at Sophea's collarbone, pale factory blouse, chain still"
        if re.search(r"侧脸|阿莲|认眼|抬头", blob) or (setup == "close" and "ros" in people):
            return "Yeay Ros in three-quarter profile at the corridor glass; Sophea's head is already lifted in the lit workshop beyond"
        return "Yeay Ros stopped mid-corridor looking through the right-hand glass; the bodyguard holds a half-step behind"
    if re.search(r"砸箱|开除|当众罚", blob) and setup == "close":
        return "Supervisor Piseth in close-up, defect box held at chest height, factory machines behind him"
    if re.search(r"深处|走来|主管来了", blob) or (setup == "master" and prev is not None and "piseth" in people):
        return "Sophea and Sara seated at the front sewing machine, already sewing; Piseth is in the deep aisle with a defect box, not yet at their table"
    if re.search(r"挽袖|替你|替做", blob) or (setup == "close" and "sophea" in people and prev is not None):
        return "Sophea seated at the front sewing table, left sleeve rolled, unfinished school uniforms on her table"
    if re.search(r"忍泪|不跪|不能等", blob):
        return "Sophea in close-up at the factory aisle, chin lifted, tears held, not kneeling"
    if re.search(r"哭|丢工|校服", blob) or prev is None:
        return "Sara seated crying at the front sewing machine; Sophea standing in the aisle beside the school-uniform pile"
    if prev and str(prev.get("start") or "").strip():
        return (
            f"{names} held in a {setup or 'locked'} frame at a new second-0 stance from {prev.get('id')}, "
            "same room, sit/stand and hands visible"
        )
    return f"{names} held in a {setup or 'locked'} frame at second 0, sit/stand and hands visible, not an on-marks template"


def visible_look(scene: str, beat: dict) -> str:
    blob = " ".join(str(beat.get(key) or "") for key in ("camera_note", "new_info", "beat"))
    if scene == "factory-office" or re.search(r"走廊|玻璃|office", blob):
        return (
            "Phnom Penh factory-office corridor, glass partition on the right, "
            "sewing-machine light leaking through the glass, same blocking marks, cool night fluorescents"
        )
    if scene == "factory-floor" or re.search(r"车间|factory", blob):
        return (
            "Phnom Penh factory-floor, aisle toward the deep shop, sewing machines on the right, "
            "school-uniform stacks, same blocking marks, warm practical fluorescents"
        )
    return f"Phnom Penh {scene}, match LOOK.md, same marks as blocking, warm practical light"


def stamp_v4_fields(shots: list[dict]) -> list[dict]:
    total = len(shots)
    for i, shot in enumerate(shots):
        if i == 0:
            shot.setdefault("story_function", "hook")
        elif i == total - 1:
            shot["story_function"] = "end_hook"
        elif i == max(1, int(total * 0.7) - 1):
            shot.setdefault("story_function", "climax")
        else:
            shot.setdefault("story_function", "advance")
        move = str(shot.get("move") or "static")
        action = str(shot.get("action") or "")
        shot.setdefault("end", action.split("->")[-1].strip() if "->" in action else "hold")
        shot.setdefault("camera_path", move)
        shot.setdefault("camera_speed", "slow" if move in {"push", "pull", "track"} else "held")
        shot.setdefault("landing", "hold the end pose, no extra beat")
        shot.setdefault("performance", shot.get("expression") or "held")
        shot.setdefault("sound_intent", shot.get("line_kind") or "narration")
    return shots


def heuristic_shot(index: int, beat: dict, dialogue: Optional[dict], prev: Optional[dict], prod: Optional[Path] = None) -> dict:
    raw_place = (beat.get("place") or "").strip()
    scene = raw_place if re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", raw_place) else _slug_place(" ".join([raw_place, beat.get("beat") or ""]))
    setup = beat.get("setup") or _setup_for(index, beat.get("new_info") or "", prev is None or (prev or {}).get("scene") != scene)
    scale = SCALE_FOR_SETUP.get(setup, "med")
    move = beat.get("move") or ("push" if setup == "close" and index % 3 == 1 else "static")
    people = [align_slug(name, prod) for name in re.split(r"[,/、\s]+", beat.get("people") or "") if name]
    people = [p for p in people if p]
    if not people:
        people = _people(" ".join([beat.get("beat") or "", beat.get("camera_note") or "", beat.get("new_info") or ""]), prod)
    if "neary" in people and "闪回" not in (beat.get("camera_note") or "") and "照片" not in (beat.get("new_info") or ""):
        people = [p for p in people if p != "neary"]
    sid = f"SH{index:03d}"
    same_scene = prev is not None and prev.get("scene") == scene
    if not same_scene:
        cut, derived, from_id = "hard", f"{scene}.blocking", None
        axis = "center" if setup == "master" else "left"
    else:
        cut, derived, from_id = "continue", prev["id"], prev["id"]
        axis = "left" if setup != "master" else "center"
        if setup == prev.get("setup") and people == (prev.get("characters") or []):
            setup = "close" if setup != "close" else "ots"
            scale = SCALE_FOR_SETUP[setup]
            axis = "left"
    line = (dialogue or {}).get("text") or f"{beat.get('beat')}。"
    caption = line[:32]
    camera = camera_for_move(move)
    action = visible_action(beat)
    look = visible_look(scene, beat)
    start = visible_start(scene, beat, people, setup, prev)
    lens = "35mm" if setup == "master" else "85mm" if setup in {"close", "insert"} else "50mm"
    video_prompt = compose_video_prompt(
        {
            "setup": setup,
            "scale": scale,
            "move": move,
            "lens": lens,
            "camera": camera,
            "action": action,
            "look": look,
            "new_info": beat.get("new_info") or beat.get("beat"),
            "aspect": beat.get("aspect") or DEFAULT_ASPECT,
        }
    )
    emotion = "held"
    if re.search(r"哭|丢工", str(beat.get("new_info") or "") + str(beat.get("camera_note") or "")):
        emotion = "crying"
    elif re.search(r"砸|罚|开除", str(beat.get("new_info") or "") + str(beat.get("camera_note") or "")):
        emotion = "furious"
    elif re.search(r"忍泪|不跪", str(beat.get("new_info") or "") + str(beat.get("beat") or "")):
        emotion = "holding-tears"
    elif re.search(r"阿莲|认", str(beat.get("new_info") or "")):
        emotion = "startled-recognition"
    info = beat.get("new_info") or beat.get("beat") or f"beat {index}"
    return {
        "id": sid,
        "seconds": _seconds(beat["start"], beat["end"]),
        "tier": "h3" if setup == "close" and index <= 3 else "fast",
        "scale": scale,
        "setup": setup,
        "move": move,
        "cut": cut,
        "from": from_id,
        "derived_from": derived,
        "facing": "scene" if setup == "master" else "camera" if setup == "close" else "scene",
        "expression": emotion,
        "blocking": f"{', '.join(people)} on {scene} marks",
        "start": start,
        "scene": scene,
        "characters": people[:3],
        "new_info": info,
        "line_kind": (dialogue or {}).get("kind") or "narration",
        "speaker": (dialogue or {}).get("character") if (dialogue or {}).get("kind") in {"dialogue", "inner"} else "",
        "line": line,
        "caption": caption,
        "on_screen": "",
        "frame": f"04-frames/{sid}.jpg",
        "last_frame": f"04-frames/{sid}-last.jpg",
        "prompt": f"{setup} {scale}. One motion only. [{move}]",
        "lens": lens,
        "axis": axis,
        "camera": camera,
        "action": action,
        "look": look,
        "video_prompt": video_prompt,
        "negatives": (
            "no subtitles, no captions, no watermark, no logo, no extra person, "
            "no clothing change, no face drift, no orbit, no crash zoom, no beauty filter, no lip-sync speech, "
            "no qipao, no Forbidden City, no WeChat wallet, no location change, no restaurant, no street cutaway"
        ),
        "emotion": emotion,
        "sfx": (
            "Quiet factory corridor, sewing machines muffled through glass, distant motorbikes."
            if "office" in scene or "corridor" in scene
            else "Factory sewing motors, cloth rustle, distant motorbikes outside."
            if "factory" in scene
            else "Quiet room tone, no score."
        ),
        "story_function": "hook" if index == 1 else "advance",
        "end": action.split("->")[-1].strip() if "->" in action else action,
        "camera_path": move,
        "camera_speed": "slow" if move in {"push", "pull", "track"} else "held",
        "landing": "hold the end pose, no extra beat",
        "performance": emotion,
        "sound_intent": (dialogue or {}).get("kind") or "narration",
        "source_start": float(beat["start"]),
        "source_end": float(beat["end"]),
    }


def pick_dialogue(beat: dict, unused_lines: list[dict]) -> Optional[dict]:
    people = [align_slug(name) for name in re.split(r"[,/、\s]+", beat.get("people") or "") if name]
    info = str(beat.get("new_info") or beat.get("beat") or beat.get("camera_note") or "")
    scored = []
    for i, item in enumerate(unused_lines):
        if people and item.get("character") not in people:
            continue
        text = item.get("text") or ""
        score = 0
        if "医院" in text or "替你" in text or "做完" in text:
            score += 3 if any(token in info for token in ("替", "医院", "做")) else -1
        if "扣" in text or "不用来" in text or "工位" in text:
            score += 4 if any(token in info for token in ("罚", "砸", "开除", "扣")) else 0
        if "错在我" in text or "不能等" in text:
            score += 4 if any(token in info for token in ("不跪", "不能等", "认")) else 0
        if "丢" in text or "这份工" in text:
            score += 3 if any(token in info for token in ("丢工", "发烧", "件")) else 0
        if score:
            scored.append((score, i, item))
    if scored:
        scored.sort(reverse=True)
        return unused_lines.pop(scored[0][1])
    for i, item in enumerate(unused_lines):
        if item.get("character") in people:
            return unused_lines.pop(i)
    return None


def heuristic_package(prod: Path) -> dict:
    episode = read_text(prod, "01-bible/ep01.md")
    confirm = read_text(prod, "01-bible/confirm.md")
    coverage = read_text(prod, "03-storyboard/coverage.md")
    official_beats = read_text(prod, "03-storyboard/beats.md")
    if not episode.strip():
        raise ScriptError("NO_EPISODE", "还没有 ep01.md，先上传或粘贴剧本")
    beat_rows = parse_beat_table(official_beats)
    beats = parse_coverage_table(coverage, prod)
    source = "coverage.md"
    if beat_rows and beats and len(beat_rows) == len(beats):
        for cov, beat in zip(beats, beat_rows):
            if beat.get("people"):
                cov["people"] = beat["people"]
            if beat.get("place") and not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", str(cov.get("place") or "")):
                cov["place"] = beat["place"]
        source = "coverage.md+beats.md"
    if not beats:
        beats = beat_rows
        source = "beats.md"
    if not beats:
        beats = parse_beat_table(episode)
        source = "ep01.md"
    if not beats:
        beats = [
            {"index": 1, "start": 0, "end": 6, "beat": "开场冲突", "place": "factory-floor", "new_info": "冲突出现", "people": "sophea"},
            {"index": 2, "start": 6, "end": 14, "beat": "升级", "place": "factory-floor", "new_info": "惩罚升级", "people": "sophea"},
            {"index": 3, "start": 14, "end": 22, "beat": "尾钩", "place": "factory-office", "new_info": "有人认出她", "people": "ros"},
        ]
        source = "fallback"
    dialogue = parse_dialogue(episode)
    for line in dialogue:
        line["character"] = align_slug(line.get("character") or line.get("speaker") or "", prod)
    unused_lines = list(dialogue)
    shots = []
    prev = None
    aspect = production_aspect(prod)
    for index, beat in enumerate(beats, start=1):
        people = [align_slug(name, prod) for name in re.split(r"[,/、\s]+", beat.get("people") or "") if name]
        line = pick_dialogue(beat, unused_lines)
        if line is None and beat.get("setup") != "insert":
            fallback = beat.get("new_info") or beat.get("beat")
            line = {"text": str(fallback).strip("。") + "。", "kind": "narration", "character": (people[0] if people else "sophea")}
        beat = {**beat, "aspect": aspect}
        shot = heuristic_shot(index, beat, line, prev, prod)
        shots.append(shot)
        prev = shot
    stamp_v4_fields(shots)
    h3 = 0
    for shot in shots:
        if shot["tier"] == "h3":
            h3 += 1
            if h3 > 3:
                shot["tier"] = "fast"
    title = next((ln.lstrip("# ").strip() for ln in episode.splitlines() if ln.startswith("#")), prod.name)
    seconds = sum(int(s["seconds"]) for s in shots)
    blueprint = [
        f"# 故事蓝图 · 第 01 集（脚本专家草稿）",
        "",
        "## 一句",
        "",
        title,
        "",
        "## 结构",
        "",
        "| 段 | 秒 | 作用 |",
        "|---|---|---|",
        "| 开头 | 0-3 | 吸引注意：设定 + 冲突 |",
        f"| 中间 | 3-{max(12, seconds-8)} | 核心对抗升级 |",
        f"| 结尾 | {max(12, seconds-8)}-{seconds} | 尾钩，不写广告号召 |",
        "",
        "## 转折",
        "",
        "| 秒 | 转折 |",
        "|---|---|",
    ]
    for beat in beats:
        blueprint.append(f"| {beat['start']} | {beat.get('new_info') or beat.get('beat')} |")
    blueprint += ["", "## 场次", ""]
    seen = []
    for shot in shots:
        if shot["scene"] not in seen:
            seen.append(shot["scene"])
            blueprint.append(f"{len(seen)}. `{shot['scene']}`")
    beats_md = [
        "# 节拍 · 第 01 集（脚本专家草稿）",
        "",
        "- **状态**：draft",
        "- **类型**：shortdrama",
        f"- **目标秒数**：{seconds}",
        "- **开场钩子（必须发生在第几秒）**：0–3 秒内必须出现冲突",
        "",
        "| 起 | 止 | 节拍 | 新信息（只一件） | 地点 | 人 |",
        "|---|---|---|---|---|---|",
    ]
    t = 0
    for shot in shots:
        beats_md.append(
            f"| {t} | {t + int(shot['seconds'])} | {shot['id']} | {shot['new_info']} | {shot['scene']} | {','.join(shot['characters'])} |"
        )
        t += int(shot["seconds"])
    coverage = ["# 覆盖 · 第 01 集（脚本专家草稿）", ""]
    by_scene: dict[str, list] = {}
    for shot in shots:
        by_scene.setdefault(shot["scene"], []).append(shot)
    for scene, items in by_scene.items():
        coverage += [f"## {scene}", "", "| setup | 镜 | 秒 | 机位 | 新信息 |", "|---|---|---|---|---|"]
        for shot in items:
            coverage.append(f"| {shot['setup']} | {shot['id']} | {shot['seconds']} | {shot['camera']} | {shot['new_info']} |")
        coverage.append("")
    voice = ["# 配音文案 · 工作轨", "", "不赌口型。声音后期叠，不写进 video_prompt。", ""]
    labels = {"dialogue": "口述", "inner": "心里", "narration": "旁白", "intro": "出场简介", "sms": "短信"}
    for shot in shots:
        kind = labels.get(shot.get("line_kind"), shot.get("line_kind"))
        who = shot.get("speaker") or "—"
        voice.append(f"- {shot['id']} [{kind}/{who}/{shot.get('emotion')}] {shot['line']}")
        voice.append(f"  字幕：{shot['caption']}")
    overview = {
        "title": title,
        "seconds": seconds,
        "style": "photoreal Phnom Penh short drama",
        "audience": "金边横屏本地观众",
        "platform": "16:9 横幅；单集时长等于分镜秒数之和",
        "confirm": confirm[:400],
        "beat_source": source,
        "characters": sorted({c for s in shots for c in (s.get("characters") or [])}),
    }
    return {
        "overview": overview,
        "blueprint_md": "\n".join(blueprint) + "\n",
        "beats_md": "\n".join(beats_md) + "\n",
        "coverage_md": "\n".join(coverage) + "\n",
        "voiceover_md": "\n".join(voice) + "\n",
        "shots": {
            "episode": "ep01",
            "kind": "shortdrama",
            "aspect": production_aspect(prod),
            "origin": "scriptwriter-heuristic",
            "shots": shots,
        },
        "beat_source": source,
    }


def grok_package(prod: Path, brief: str = "") -> dict:
    from .grok_text import chat_json

    existing = existing_character_slugs(prod)
    user = json.dumps(
        {
            "brief": brief or KHMER_DEFAULT_BRIEF,
            "confirm": read_text(prod, "01-bible/confirm.md"),
            "blueprint": read_text(prod, "01-bible/blueprint.md"),
            "episode": read_text(prod, "01-bible/ep01.md"),
            "beats": read_text(prod, "03-storyboard/beats.md"),
            "coverage": read_text(prod, "03-storyboard/coverage.md"),
            "look": read_text(prod, "02-assets/LOOK.md"),
            "existing_character_slugs": existing,
            "name_lock": "Use existing folders only when present. 罗丝 is ros, not yeay-ros. 保镖 is bodyguard.",
            "camera_moves": load_template("camera-moves.md"),
            "video_prompt_formula": load_template("video-prompt-formula.md"),
            "knowledge": __import__("director.knowledge", fromlist=["prompt_block"]).prompt_block("writer")[:3500],
            "director_knowledge": __import__("director.knowledge", fromlist=["prompt_block"]).prompt_block("director")[:2500],
            "culture_excerpt": (Path(__file__).resolve().parents[2] / "CULTURE.md").read_text(encoding="utf-8")[:3500],
        },
        ensure_ascii=False,
    )
    data = chat_json(SYSTEM, user, timeout=180)
    if not isinstance(data, dict):
        raise ScriptError("GROK_JSON", "脚本专家没有返回对象")
    shots = data.get("shots") or {}
    if isinstance(shots, list):
        shots = {"episode": "ep01", "kind": "shortdrama", "aspect": production_aspect(prod), "shots": shots}
    if not shots.get("shots"):
        raise ScriptError("GROK_JSON", "脚本专家没有返回分镜")
    shots["origin"] = "scriptwriter-grok"
    shots.setdefault("episode", "ep01")
    shots.setdefault("kind", "shortdrama")
    shots.setdefault("aspect", production_aspect(prod))
    for shot in shots.get("shots") or []:
        shot["characters"] = [align_slug(name, prod) for name in (shot.get("characters") or [])]
        shot["characters"] = [c for c in shot["characters"] if c]
        if shot.get("scene"):
            shot["scene"] = _slug_place(str(shot["scene"]), str(shot["scene"]))
    stamp_v4_fields(shots.get("shots") or [])
    data["shots"] = shots
    return data


def lint_draft(shots: list[dict]) -> list[str]:
    import sys

    scripts = Path(__file__).resolve().parents[1]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from check_storyboard import check_director_fields  # noqa: WPS433

    errors = []
    for shot in shots:
        try:
            check_director_fields(shot)
        except SystemExit as exc:
            errors.append(str(exc))
        missing = [
            key
            for key in ("story_function", "end", "camera_path", "camera_speed", "landing", "performance", "sound_intent")
            if not str(shot.get(key) or "").strip()
        ]
        if missing:
            errors.append(f"{shot.get('id')} 新草稿缺 {', '.join(missing)}")
    return errors


def write_package(prod: Path, package: dict) -> dict:
    shots = package.get("shots") or {}
    if not shots.get("shots"):
        raise ScriptError("NO_SHOTS", "没有分镜可写")
    save_json(prod, "01-bible/overview.draft.json", package.get("overview") or {})
    write_text(prod, "01-bible/blueprint.draft.md", package.get("blueprint_md") or "")
    write_text(prod, "03-storyboard/beats.draft.md", package.get("beats_md") or "")
    write_text(prod, "03-storyboard/coverage.draft.md", package.get("coverage_md") or "")
    write_text(prod, "03-storyboard/voiceover.draft.md", package.get("voiceover_md") or "")
    save_shot_draft(prod, shots)
    write_sets_draft(prod, shots)
    seeded_assets = seed_asset_folders(prod, shots, create_missing=False)
    seeded_docs = maybe_seed_storyboard_docs(
        prod, package.get("beats_md") or "", package.get("coverage_md") or ""
    )
    seeded = list((seeded_docs or {}).get("seeded") or [])
    seeded.extend(seeded_assets)
    from .writer_checks import check_episode

    lint = lint_draft(shots.get("shots") or [])
    lint.extend(check_episode(prod, shots.get("shots") or []))
    return {
        "ok": True,
        "origin": shots.get("origin"),
        "shot_count": len(shots.get("shots") or []),
        "lint": lint,
        "seeded": seeded,
        "files": [
            "01-bible/overview.draft.json",
            "01-bible/blueprint.draft.md",
            "03-storyboard/beats.draft.md",
            "03-storyboard/coverage.draft.md",
            "03-storyboard/voiceover.draft.md",
            "03-storyboard/shots.draft.json",
        ],
    }


def draft_script(prod: Path, *, brief: str = "", use_grok: bool = True) -> dict:
    from .breakdown import breakdown_package

    try:
        broken = breakdown_package(prod)
        package = heuristic_package(prod)
        package["shots"] = broken["shots"]
        package["beat_source"] = broken.get("beat_source") or package.get("beat_source")
        package["overview"] = dict(package.get("overview") or {})
        package["overview"]["directing"] = broken["shots"].get("directing")
        package["overview"]["beat_source"] = package["beat_source"]
    except Exception:
        package = heuristic_package(prod)
    grok_error = None
    if use_grok:
        try:
            package = grok_package(prod, brief)
        except Exception as exc:
            grok_error = str(exc)
            package["shots"]["origin"] = package.get("shots", {}).get("origin") or "director-breakdown"
            package["grok_error"] = grok_error
    written = write_package(prod, package)
    written["grok_error"] = grok_error
    written["overview"] = package.get("overview")
    written["updated_at"] = int(time.time())
    save_json(prod, "01-bible/scriptwriter.json", {k: v for k, v in written.items() if k != "overview"} | {"overview": package.get("overview")})
    return written


def snapshot_scriptwriter(prod: Path) -> dict:
    return {
        "status": load_json(prod, "01-bible/scriptwriter.json", {}),
        "overview": load_json(prod, "01-bible/overview.draft.json", {}),
        "blueprint_draft": read_text(prod, "01-bible/blueprint.draft.md"),
        "beats_draft": read_text(prod, "03-storyboard/beats.draft.md"),
        "voiceover_draft": read_text(prod, "03-storyboard/voiceover.draft.md"),
        "shot_draft_count": len(load_json(prod, "03-storyboard/shots.draft.json", {"shots": []}).get("shots") or []),
    }
