"""Character name cards: two lines (name · role) laid over the picture in post, never drawn by a model.

The words live in the dialogue gate: a writer caption `{"kind": "intro", "character": id, "text": "达拉 · 考古系大四学生"}`
becomes a lines row whose Khmer Gemini writes as `name · role`. The placement lives in the storyboard: a shot
carries `name_card: {"character", "side", "x", "y", "start_sec", "hold_sec"}`. Cards are typeset with a real
Khmer font through Core Text (`scripts/khmer_coretext.swift`), previewed on the approved first frame before any
video exists, and overlaid on the cut with ffmpeg at the edit. Image and video models never write the text:
010 showed Codex misspelling Khmer names, and text inside a first frame warps once the video moves.

Place/time cards (「1549 · 吴哥以南」) work the same way: the words are the scene's `place_time` caption in the
dialogue gate (Khmer `time · place`), the placement is `place_card: {"side", "x", "y", "start_sec", "hold_sec"}`
on one shot of that scene (usually its first), and the card is overlaid on the cut. 012 EP01 had the caption
but no slot for it, so the cut had no year on screen.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

SIDES = ("left", "right")
DEFAULT_START_SEC = 0.3
DEFAULT_HOLD_SEC = 2.5
MIN_HOLD_SEC = 1.5
MAX_HOLD_SEC = 4.0
FADE_SEC = 0.25
# Khmer dialogue subtitles sit in the bottom band; a card's top edge stays above it.
MAX_TOP = 0.75
NAME_HEIGHT = 0.062  # name line ≈ 6% of the frame height
ROLE_RATIO = 0.62  # role line height relative to the name line
GOLD = (217, 178, 106, 255)
NAME_COLOR = "FFFFFF"
ROLE_COLOR = "EBDDBF"
NAME_FONT = "KhmerMN-Bold"
ROLE_FONT = "KhmerSangamMN"
SEPARATOR = " · "


def _t(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- data ----------------------------------------------------------------------------------


def card_texts(lines: Optional[dict]) -> dict[str, dict]:
    """character -> {line_id, zh, km, name_km, role_km} from the dialogue gate's intro captions."""
    out: dict[str, dict] = {}
    for row in (lines or {}).get("lines") or []:
        if _t(row.get("kind")) != "caption" or _t(row.get("caption_kind")) != "intro" or row.get("drop"):
            continue
        character = _t(row.get("speaker") or row.get("character"))
        km = _t(row.get("km"))
        name_km, _sep, role_km = km.partition("·")
        out[character] = {
            "line_id": _t(row.get("line_id")),
            "zh": _t(row.get("zh_new") or row.get("zh")),
            "km": km,
            "name_km": name_km.strip(),
            "role_km": role_km.strip(),
        }
    return out


def scene_of_line(line_id: str) -> str:
    """EP01_SC02:c01 -> EP01_SC02."""
    return _t(line_id).split(":", 1)[0]


def place_texts(lines: Optional[dict]) -> dict[str, dict]:
    """scene_id -> {line_id, zh, km, line1_km, line2_km} from the dialogue gate's place_time captions."""
    out: dict[str, dict] = {}
    for row in (lines or {}).get("lines") or []:
        if _t(row.get("kind")) != "caption" or _t(row.get("caption_kind")) != "place_time" or row.get("drop"):
            continue
        km = _t(row.get("km"))
        first, _sep, second = km.partition("·")
        out[scene_of_line(row.get("line_id"))] = {
            "line_id": _t(row.get("line_id")),
            "zh": _t(row.get("zh_new") or row.get("zh")),
            "km": km,
            "line1_km": first.strip(),
            "line2_km": second.strip(),
        }
    return out


def normalize_place_card(card: dict, shot: Optional[dict] = None) -> dict:
    side = _t(card.get("side")) or "left"
    duration = _num((shot or {}).get("duration_sec"), 0.0)
    start = _num(card.get("start_sec"), DEFAULT_START_SEC)
    hold = _num(card.get("hold_sec"), DEFAULT_HOLD_SEC)
    if duration and "hold_sec" not in card:
        hold = max(MIN_HOLD_SEC, min(DEFAULT_HOLD_SEC, duration - start))
    x = _num(card.get("x"), 0.05 if side == "left" else 0.60)
    return {
        "kind": "place",
        "scene_id": _t((shot or {}).get("scene_id")),
        "side": side,
        "x": round(x, 3),
        "y": round(_num(card.get("y"), 0.08), 3),
        "start_sec": round(start, 2),
        "hold_sec": round(hold, 2),
    }


def placed_place_cards(table: Optional[dict]) -> list[tuple[dict, dict]]:
    out = []
    for shot in (table or {}).get("shots") or []:
        card = shot.get("place_card")
        if isinstance(card, dict):
            out.append((shot, normalize_place_card(card, shot)))
    return out


def placed_cards(table: Optional[dict]) -> list[tuple[dict, dict]]:
    """(shot, normalized card) for every shot that carries a name card."""
    out = []
    for shot in (table or {}).get("shots") or []:
        card = shot.get("name_card")
        if isinstance(card, dict) and _t(card.get("character")):
            out.append((shot, normalize_card(card, shot)))
    return out


def normalize_card(card: dict, shot: Optional[dict] = None) -> dict:
    side = _t(card.get("side")) or "right"
    duration = _num((shot or {}).get("duration_sec"), 0.0)
    start = _num(card.get("start_sec"), DEFAULT_START_SEC)
    hold = _num(card.get("hold_sec"), DEFAULT_HOLD_SEC)
    if duration and "hold_sec" not in card:
        hold = max(MIN_HOLD_SEC, min(DEFAULT_HOLD_SEC, duration - start))
    x = _num(card.get("x"), 0.05 if side == "left" else 0.60)
    return {
        "kind": "name",
        "character": _t(card.get("character")),
        "side": side,
        "x": round(x, 3),
        "y": round(_num(card.get("y"), 0.12), 3),
        "start_sec": round(start, 2),
        "hold_sec": round(hold, 2),
    }


def _in_frame(shot: dict) -> set[str]:
    chars = ((shot.get("state") or {}).get("characters") or {}) if isinstance(shot.get("state"), dict) else {}
    return {cid for cid, st in chars.items() if not isinstance(st, dict) or st.get("in_frame", True)}


def validate_name_cards(table: dict, lines: Optional[dict] = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    texts = card_texts(lines)
    seen: dict[str, str] = {}
    for shot, card in placed_cards(table):
        sid = _t(shot.get("shot_id"))
        who = card["character"]
        if card["side"] not in SIDES:
            errors.append(f"{sid} name_card side must be one of {list(SIDES)}")
        if not 0.0 <= card["x"] <= 0.85:
            errors.append(f"{sid} name_card x {card['x']} is off the frame (0–0.85)")
        if not 0.02 <= card["y"] <= MAX_TOP:
            errors.append(f"{sid} name_card y {card['y']} must sit between 0.02 and {MAX_TOP} (subtitles live below)")
        if not MIN_HOLD_SEC <= card["hold_sec"] <= MAX_HOLD_SEC:
            errors.append(f"{sid} name_card holds {card['hold_sec']}s; keep it {MIN_HOLD_SEC}–{MAX_HOLD_SEC}s")
        duration = _num(shot.get("duration_sec"), 0.0)
        if card["start_sec"] < 0 or card["start_sec"] + card["hold_sec"] > duration + 0.05:
            errors.append(f"{sid} name_card runs {card['start_sec']}+{card['hold_sec']}s past the {duration}s shot")
        present = _in_frame(shot)
        if present and who not in present:
            errors.append(f"{sid} name_card for {who}, who is not in frame")
        if who in seen:
            warnings.append(f"{sid} second name card for {who} (first on {seen[who]}); one card per person per episode")
        seen.setdefault(who, sid)
        if lines and lines.get("lines"):
            text = texts.get(who)
            if not text:
                errors.append(f"{sid} name_card for {who} has no intro caption in the dialogue gate")
            elif not text["name_km"] or not text["role_km"]:
                errors.append(f"{sid} name_card for {who}: Khmer must read 'name · role'")
    for who, text in texts.items():
        if who and who not in seen and (table or {}).get("shots"):
            warnings.append(f"{text['line_id']} name card for {who} is not placed on any shot (name_card)")
    place_errors, place_warnings = validate_place_cards(table, lines)
    return errors + place_errors, warnings + place_warnings


def validate_place_cards(table: dict, lines: Optional[dict] = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    texts = place_texts(lines)
    seen: dict[str, str] = {}
    for shot, card in placed_place_cards(table):
        sid = _t(shot.get("shot_id"))
        scene = card["scene_id"]
        if card["side"] not in SIDES:
            errors.append(f"{sid} place_card side must be one of {list(SIDES)}")
        if not 0.0 <= card["x"] <= 0.85:
            errors.append(f"{sid} place_card x {card['x']} is off the frame (0–0.85)")
        if not 0.02 <= card["y"] <= MAX_TOP:
            errors.append(f"{sid} place_card y {card['y']} must sit between 0.02 and {MAX_TOP} (subtitles live below)")
        if not MIN_HOLD_SEC <= card["hold_sec"] <= MAX_HOLD_SEC:
            errors.append(f"{sid} place_card holds {card['hold_sec']}s; keep it {MIN_HOLD_SEC}–{MAX_HOLD_SEC}s")
        duration = _num(shot.get("duration_sec"), 0.0)
        if card["start_sec"] < 0 or card["start_sec"] + card["hold_sec"] > duration + 0.05:
            errors.append(f"{sid} place_card runs {card['start_sec']}+{card['hold_sec']}s past the {duration}s shot")
        if scene in seen:
            errors.append(f"{sid} second place_card for scene {scene} (first on {seen[scene]})")
        seen.setdefault(scene, sid)
        if lines and lines.get("lines"):
            text = texts.get(scene)
            if not text:
                errors.append(f"{sid} place_card but scene {scene} has no place_time caption in the dialogue gate")
            elif not text["line1_km"]:
                errors.append(f"{sid} place_card for {scene}: Khmer caption is empty")
        if card["side"] in SIDES and isinstance(shot.get("name_card"), dict):
            other = normalize_card(shot["name_card"], shot)
            if other["side"] == card["side"] and abs(other["y"] - card["y"]) < 0.2:
                errors.append(f"{sid} place_card and name_card overlap on the {card['side']} side; move one")
    shot_scenes = {_t(s.get("scene_id")) for s in (table or {}).get("shots") or []}
    for scene, text in texts.items():
        if scene in shot_scenes and scene not in seen:
            warnings.append(f"{text['line_id']} place/time card 「{text['zh']}」 is not placed on any shot of {scene} (place_card)")
    return errors, warnings


def space_note_zh(shot: dict) -> str:
    """Keyframe prompt tail: leave clean room on each card's side; draw no text at all."""
    notes: list[str] = []
    for key, normalize, label in (("name_card", normalize_card, "人物名片"), ("place_card", normalize_place_card, "地点时间卡")):
        card = shot.get(key)
        if not isinstance(card, dict) or (key == "name_card" and not _t(card.get("character"))):
            continue
        card = normalize(card, shot)
        side = "左" if card["side"] == "left" else "右"
        band = "上方" if card["y"] < 0.33 else ("中部" if card["y"] < 0.6 else "中下部")
        notes.append(f"画面{side}侧{band}留一块干净的空白（天空、墙面或暗部），后期在那里叠{label}")
    if not notes:
        return ""
    return "；".join(notes) + "；画面里不写任何字。"


# --- typesetting ---------------------------------------------------------------------------


def coretext_binary(source: Path) -> Path:
    """Compile khmer_coretext.swift once per source version (macOS)."""
    digest = hashlib.sha1(Path(source).read_bytes()).hexdigest()[:12]
    target = Path(tempfile.gettempdir()) / f"khmer_coretext-{digest}"
    if not target.exists():
        if not shutil.which("swiftc"):
            raise RuntimeError("swiftc not found; name cards need Core Text on macOS")
        subprocess.run(["swiftc", "-O", "-o", str(target), str(source)], check=True, capture_output=True)
    return target


def _trim(img):
    box = img.getbbox()
    return img.crop(box) if box else img


def render_card(name_km: str, role_km: str, frame_height: int, out: Path, coretext: Path) -> Path:
    """Two-line card (gold bar, name, role) on a transparent PNG sized for a frame of this height."""
    from PIL import Image, ImageDraw, ImageFilter

    with tempfile.TemporaryDirectory() as tmp:
        jobs = [
            {"text": name_km, "font": NAME_FONT, "size": 48, "color": NAME_COLOR, "out": str(Path(tmp) / "name.png")},
            {"text": role_km, "font": ROLE_FONT, "size": 30, "color": ROLE_COLOR, "out": str(Path(tmp) / "role.png")},
        ]
        batch = Path(tmp) / "jobs.json"
        batch.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        subprocess.run([str(coretext), "--batch", str(batch)], check=True, capture_output=True)
        name = _trim(Image.open(Path(tmp) / "name.png").convert("RGBA"))
        role = _trim(Image.open(Path(tmp) / "role.png").convert("RGBA"))
    name_h = max(8, int(frame_height * NAME_HEIGHT))
    role_h = max(6, int(name_h * ROLE_RATIO))
    name = name.resize((max(1, int(name.width * name_h / name.height)), name_h), Image.LANCZOS)
    role = role.resize((max(1, int(role.width * role_h / role.height)), role_h), Image.LANCZOS)
    gap = int(frame_height * 0.012)
    pad = int(frame_height * 0.014)
    bar = max(3, int(frame_height * 0.006))
    margin = 24
    width = bar + pad + max(name.width, role.width)
    height = name.height + gap + role.height
    card = Image.new("RGBA", (width + margin * 2, height + margin * 2), (0, 0, 0, 0))
    ImageDraw.Draw(card).rectangle([margin, margin, margin + bar, margin + height], fill=GOLD)
    card.alpha_composite(name, (margin + bar + pad, margin))
    card.alpha_composite(role, (margin + bar + pad, margin + name.height + gap))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shadow.putalpha(card.split()[-1].point(lambda v: v * 170 // 255).filter(ImageFilter.GaussianBlur(6)))
    out_img = Image.new("RGBA", card.size, (0, 0, 0, 0))
    out_img.alpha_composite(shadow, (2, 3))
    out_img.alpha_composite(card)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(out)
    return out


def card_position(card: dict, width: int, height: int) -> tuple[int, int]:
    """Top-left pixel for the card PNG (its 24px margin already included in the PNG)."""
    return int(width * card["x"]) - 24, int(height * card["y"]) - 24


def preview_on_frame(frame: Path, card_png: Path, card: dict, out: Path) -> Path:
    from PIL import Image

    base = Image.open(frame).convert("RGBA")
    layer = Image.open(card_png).convert("RGBA")
    base.alpha_composite(layer, card_position(card, base.width, base.height))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, quality=90)
    return out


# --- the cut -------------------------------------------------------------------------------


def shot_starts(cut: dict) -> dict[str, float]:
    """shot_id -> start second in the final cut (timeline order, output durations)."""
    clock = 0.0
    out: dict[str, float] = {}
    for item in cut.get("timeline") or cut.get("cuts") or []:
        sid = _t(item.get("shot_id"))
        if sid and sid not in out:
            out[sid] = round(clock, 3)
        duration = item.get("output_duration_sec")
        if duration is None:
            speed = _num(item.get("speed"), 1.0) or 1.0
            duration = (_num(item.get("out_sec"), 0.0) - _num(item.get("in_sec"), 0.0)) / speed
        clock += _num(duration, 0.0)
    return out


def overlay_plan(table: dict, cut: dict) -> list[dict]:
    """Cards placed on shots that survive the cut, with absolute times."""
    starts = shot_starts(cut)
    plan = []
    for shot, card in placed_cards(table) + placed_place_cards(table):
        sid = _t(shot.get("shot_id"))
        if sid not in starts:
            continue
        t0 = round(starts[sid] + card["start_sec"], 3)
        plan.append({**card, "shot_id": sid, "t0": t0, "t1": round(t0 + card["hold_sec"], 3)})
    return sorted(plan, key=lambda c: c["t0"])


def ffmpeg_overlay_args(video: Path, cards: list[dict], pngs: list[Path], out: Path, width: int, height: int) -> list[str]:
    """One ffmpeg call: each PNG fades in and out at its time, positioned in frame pixels."""
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video)]
    for card, png in zip(cards, pngs):
        args += ["-loop", "1", "-t", f"{card['hold_sec']:.3f}", "-i", str(png)]
    chains = []
    last = "[0:v]"
    for index, card in enumerate(cards, start=1):
        hold = card["hold_sec"]
        fade_out = max(0.0, hold - FADE_SEC)
        x, y = card_position(card, width, height)
        chains.append(
            f"[{index}:v]format=rgba,fade=t=in:st=0:d={FADE_SEC}:alpha=1,"
            f"fade=t=out:st={fade_out:.3f}:d={FADE_SEC}:alpha=1,setpts=PTS-STARTPTS+{card['t0']:.3f}/TB[c{index}]"
        )
        label = f"[v{index}]"
        chains.append(f"{last}[c{index}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{card['t0']:.3f},{card['t1']:.3f})'{label}")
        last = label
    args += ["-filter_complex", ";".join(chains), "-map", last, "-map", "0:a?", "-c:a", "copy", "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", str(out)]
    return args


def video_size(video: Path) -> tuple[int, int]:
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(video),
    ])
    stream = json.loads(raw)["streams"][0]
    return int(stream["width"]), int(stream["height"])
