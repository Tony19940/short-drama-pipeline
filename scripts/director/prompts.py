"""Compile locked shot fields into still/video model instructions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import re

from .defaults import DEFAULT_ASPECT, frame_label, production_aspect

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "templates"
MOVE_CAMERA = {
    "static": "locked-off static camera, faint handheld breath only, no orbit",
    "push": "slow push in on one subject, faint handheld, no orbit, no crash zoom",
    "pull": "slow pull out to restore room geography, faint handheld, no orbit",
    "pan": "one small pan along the 180 line, then hold; no whip pan",
    "track": "short lateral track, keep background continuous, optional foreground wipe",
}
SETUP_WORDS = {
    "master": "master establishing",
    "close": "close-up",
    "ots": "over-the-shoulder",
    "single": "clean single",
    "insert": "insert",
}

SPACE_LOCK = (
    "Stay inside the same room for the whole clip. Do not cut, dissolve, or morph to another location."
)
DEFAULT_NEGATIVES = (
    "no subtitles, no captions, no watermark, no logo, no extra person, "
    "no clothing change, no face drift, no orbit, no crash zoom, no beauty filter, no lip-sync speech, "
    "no qipao, no Forbidden City, no WeChat wallet, no location change"
)
SCALE_WORDS = {
    "wide": "wide shot",
    "full": "full shot",
    "med": "medium shot",
    "close": "close-up",
    "insert": "insert detail shot",
}


CHARACTER_REF_ORDER = ("sheet.jpg", "face.jpg", "front.jpg", "master.jpg")
SCENE_REF_ORDER = ("master.jpg", "door.jpg", "table.jpg")


def _exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def shot_characters(shot: dict) -> list[str]:
    return [str(item) for item in (shot.get("characters") or []) if item]


def missing_sheets(prod: Path, shot: dict) -> list[str]:
    missing = []
    for slug in shot_characters(shot):
        if not _exists(prod / "02-assets" / "characters" / slug / "sheet.jpg"):
            missing.append(slug)
    return missing


def still_refs(prod: Path, shot: dict) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def add(rel: str) -> None:
        if rel in seen:
            return
        if _exists(prod / rel):
            refs.append(rel)
            seen.add(rel)

    look_root = str(shot.get("asset_root") or "02-assets").strip() or "02-assets"
    for slug in shot_characters(shot):
        folder = prod / look_root / "characters" / slug
        for name in CHARACTER_REF_ORDER:
            if _exists(folder / name):
                add(str((folder / name).relative_to(prod)))
                break
        if _exists(folder / "sheet.jpg"):
            add(str((folder / "sheet.jpg").relative_to(prod)))
        if _exists(folder / "face.jpg"):
            add(str((folder / "face.jpg").relative_to(prod)))
    scene = str(shot.get("scene") or "")
    if scene:
        folder = prod / look_root / "scenes" / scene
        for name in SCENE_REF_ORDER:
            add(str((folder / name).relative_to(prod)))
        add(str((folder / "blocking.jpg").relative_to(prod)))
    return refs[:6]



def load_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def camera_for_move(move: str) -> str:
    return MOVE_CAMERA.get(str(move or "static"), MOVE_CAMERA["static"])


def body_beat_action(info: str) -> str:
    beat = str(info or "one body beat").strip().rstrip("。.")
    return f"start still, perform one body beat ({beat}), hold the end pose"


def compose_video_prompt(shot: dict) -> str:
    setup = str(shot.get("setup") or "single")
    scale = str(shot.get("scale") or "med")
    camera = str(shot.get("camera") or camera_for_move(shot.get("move") or "static"))
    action = str(shot.get("action") or body_beat_action(shot.get("new_info") or shot.get("beat") or ""))
    look = str(shot.get("look") or "match LOOK.md and the blocking marks")
    lens = str(shot.get("lens") or "")
    lens_bit = f"{lens} " if lens else ""
    seconds = int(shot.get("seconds") or 6)
    move = str(shot.get("move") or "static")
    speed = {
        "static": "Camera contract: locked-off for the full shot.",
        "push": f"Camera contract: slow push in over the full {seconds}s, no orbit.",
        "pull": f"Camera contract: slow pull out over the full {seconds}s, no orbit.",
        "pan": f"Camera contract: one small pan along the 180 line in {seconds}s, then hold.",
        "track": f"Camera contract: short lateral track in {seconds}s, keep the background continuous.",
    }.get(move, "Camera contract: locked-off for the full shot.")
    aspect = production_aspect(explicit=str(shot.get("aspect") or "") or None)
    if aspect not in ("16:9", "9:16"):
        aspect = DEFAULT_ASPECT
    frame = frame_label(aspect)
    return (
        f"{frame} photoreal Khmer {lens_bit}{SETUP_WORDS.get(setup, setup)} {SCALE_WORDS.get(scale, scale)}. "
        f"{speed} {camera}. {action}. {look}. Keep the same wardrobe, faces and room geography. "
        f"{space_lock_for(shot)} No subtitle, no watermark, no lip-sync speech."
    )


def character_sheet_prompt(slug: str, slot: str, extra: str = "") -> str:
    base = (
        "Photoreal adult Khmer, visible pores, natural skin texture, no beauty filter. "
        "Match the locked master exactly: same face, hair, age, wardrobe. Neutral even light, clean backdrop. "
        "Portrait reference card, not an episode frame."
    )
    slot = str(slot or "master")
    if slot == "sheet":
        body = (
            "Technical character reference sheet edited from the locked master. "
            "Top row: four full-body A-pose views left to right, front, left profile facing left, right profile facing right, back. "
            "Bottom row: three aligned portrait close-ups, front, left profile, right profile. "
            "Same identity, proportions, head height, light direction and softness in every panel. No new face."
        )
    elif slot == "front":
        body = "Full-body front A-pose, same locked face and wardrobe as master."
    elif slot == "side":
        body = "Full-body left profile A-pose facing left, same locked face and wardrobe as master."
    elif slot == "back":
        body = "Full-body back view A-pose, same hair and wardrobe as master, no new identity."
    elif slot == "face":
        body = "Face lock close-up from the locked master. Keep pores and natural skin. No makeup filter."
    elif slot == "master":
        body = "Full-body master still of this character in the locked costume. One new generate only."
    else:
        body = f"{slot} still of this character, match locked master."
    extra = str(extra or "").strip()
    chunks = [base, body, f"Character slug: {slug}."]
    if extra:
        chunks.append(extra)
    chunks.append("No subtitle, no watermark, no qipao, no porcelain K-pop skin.")
    return " ".join(chunks)



def space_lock_for(shot: dict) -> str:
    scene = str(shot.get("scene") or "").lower()
    look = str(shot.get("look") or "").lower()
    blob = f"{scene} {look}"
    if "office" in blob or "corridor" in blob:
        place = "this factory office corridor"
        forbidden = "No restaurant, street, temple, palace, outdoor night city, or sewing-floor cutaway."
    elif "factory" in blob:
        place = "this garment factory floor"
        forbidden = "No restaurant, street, temple, palace, or outdoor night city."
    elif "restaurant" in blob or "private-room" in blob or "tungsten" in blob:
        place = "this private dining room"
        forbidden = "No street, temple, palace, factory, or outdoor night city."
    else:
        place = "this locked set"
        forbidden = "No jump to a different building or outdoor night city."
    return (
        f"{SPACE_LOCK} Remain in {place} from first frame to last frame. {forbidden}"
    )


def default_negatives_for(shot: dict) -> str:
    scene = str(shot.get("scene") or "").lower()
    look = str(shot.get("look") or "").lower()
    extra = "no restaurant, no street cutaway" if "factory" in f"{scene} {look}" or "corridor" in f"{scene} {look}" else "no location jump"
    return f"{DEFAULT_NEGATIVES}, {extra}"

def shot_seconds(shot: dict) -> float:
    try:
        value = float(shot.get("seconds") or shot.get("duration_sec") or 4)
    except (TypeError, ValueError):
        value = 4.0
    return max(4.0, min(value, 15.0))


def designed_end_rel(shot: dict) -> str:
    rel = str(shot.get("end_frame") or "").strip()
    if rel and not Path(rel).name.lower().endswith("-last.jpg"):
        return rel
    return ""


def h3_alignment(shot: dict) -> str:
    duration = f"{shot_seconds(shot):.2f}"
    if designed_end_rel(shot):
        return (
            "How the reference pictures align with the target video — "
            "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
            f"Picture 2 (from Shot 1) aligns with the {duration}-second mark of the target video."
        )
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced."
    )


def h3_retention(shot: dict, refs: Optional[list[str]] = None) -> str:
    bits = [
        "Picture 1 is the locked first frame: composition, blocking, room geography, wardrobe, "
        "and the second-0 pose. Keep those from Picture 1. Do not generate a new poster."
    ]
    if identity_refs(refs):
        bits.append(
            "Character sheet and face references lock identity only. "
            "They do not replace Picture 1 as the 0.00-second frame."
        )
    if designed_end_rel(shot):
        bits.append(
            "Picture 2 is the designed end pose, not a generated last-frame extract. "
            "Interpolate observable motion from Picture 1 toward Picture 2 in one continuous take. Do not hard-cut."
        )
    return " ".join(bits)


def h3_timeline(shot: dict) -> str:
    parts = ["[Shot 1]"]
    start = str(shot.get("start") or "").strip()
    if start:
        parts.append(f"At 0.00 seconds hold the Picture 1 pose: {start.rstrip('.')}. Do not begin the action yet.")
    else:
        parts.append("At 0.00 seconds hold the Picture 1 pose. Do not begin the action yet.")
    header = ", ".join(item for item in (shot.get("lens"), shot.get("setup"), shot.get("move")) if item)
    if header:
        parts.append(header + ".")
    camera = str(shot.get("camera") or "").strip()
    if camera:
        parts.append(camera.rstrip(".") + ".")
    action = str(shot.get("action") or "").strip()
    if action:
        parts.append("Then one body beat only: " + action.rstrip(".") + ". Hold the end pose.")
    else:
        parts.append("Then one body beat only. Hold the end pose.")
    look = str(shot.get("look") or "").strip()
    if look:
        parts.append(look.rstrip(".") + ".")
    return " ".join(parts)


def compile_video_prompt(shot: dict, *, silent: bool = True, refs: Optional[list[str]] = None) -> str:
    body = str(shot.get("video_prompt") or shot.get("prompt") or "").strip()
    if not body:
        raise PermissionError(f"{shot.get('id', 'shot')} 没有 video_prompt")
    return format_h3_prompt(compile_h3_fields(shot, silent=silent, refs=refs))


def _looks_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


SIZE_ZH = {
    "wide": "全景",
    "full": "全身",
    "medium": "中景",
    "med": "中景",
    "close": "近景",
    "insert": "细节特写",
    "otc": "过肩",
    "ots": "过肩",
    "reaction": "反应近景",
    "single": "单人",
}
DAY_ZH = {"storm-day": "暴雨白天", "dusk": "黄昏", "night": "夜", "day": "白天"}
ANGLE_ZH = {"high": "俯角", "eye": "平视", "low": "仰角"}
MOVE_ZH = {
    "static": "机位固定，只有呼吸感微晃，禁止环绕和急推",
    "push": "缓推近，禁止急推和环绕",
    "pull": "缓拉远，禁止环绕",
    "pan": "沿轴线小幅横摇后停住，禁止甩镜",
    "tilt": "小幅俯仰后停住",
    "track": "短距横移跟随，背景保持连续",
    "follow": "跟住主体，不抢戏、不环绕",
    "handheld": "手持跟随，晃动克制",
    "crane": "小幅升降，禁止航拍盘旋",
}


def _spec_text(spec: dict, *keys: str) -> str:
    for key in keys:
        value = str((spec or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def state_note_of(spec: dict, shot: Optional[dict] = None) -> str:
    """The designer's one-line continuity note for this shot (costume, binding, what is and is not there)."""
    from .shot_table import normalize_state, state_sentence

    state = normalize_state((spec or {}).get("state") or (shot or {}).get("state"))
    return state_sentence(state) if state else ""


def compile_keyframe_prompt_zh(
    spec: dict,
    shot: Optional[dict] = None,
    frame_desc: Optional[dict] = None,
    *,
    slot: str = "first",
) -> str:
    """Still prompt for 6.1. First slot is t=0 (in_from / still_start), never the finished one_action.

    `one_action` is mentioned only as motion that happens AFTER this frame.
    Last slot uses out_to / still_end.
    """
    shot = shot or {}
    from .frame_desc import description_sentence, normalize_item
    from .still_t0 import first_still_text, forbidden_result_clause, last_still_text

    item = normalize_item(frame_desc) if frame_desc else {}
    picture = description_sentence(item) if item else ""
    size = SIZE_ZH.get(_spec_text(spec, "shot_size") or str(shot.get("scale") or ""), _spec_text(spec, "shot_size") or "中景")
    angle = ANGLE_ZH.get(_spec_text(spec, "angle") or str(shot.get("angle") or ""), "平视")
    lens = _spec_text(spec, "focal_length") or str(shot.get("lens") or "50mm")
    start = _spec_text(spec, "in_from") or str(shot.get("in_from") or shot.get("start") or "")
    end = _spec_text(spec, "out_to") or str(shot.get("out_to") or "")
    action = _spec_text(spec, "action_now", "content") or str(shot.get("one_action") or "")
    still_subject = _spec_text(spec, "subject")
    if still_subject and still_subject in {action, _spec_text(spec, "action_now", "content")}:
        still_subject = ""
    left = _spec_text(spec, "left")
    right = _spec_text(spec, "right")
    eyeline = _spec_text(spec, "eyeline")
    day_raw = _spec_text(spec, "day_night") or str((shot.get("light") or {}).get("day_night") or "")
    day = DAY_ZH.get(day_raw, day_raw)
    mood = _spec_text(spec, "color_mood") or str((shot.get("light") or {}).get("color") or "")
    light = _spec_text(spec, "key_light_dir") or str((shot.get("light") or {}).get("key_dir") or "")
    quality = _spec_text(spec, "quality") or str((shot.get("light") or {}).get("quality") or "")
    note = state_note_of(spec, shot)
    light_line = "，".join(part for part in (day, mood, ("主光" + light) if light else "", quality) if part).rstrip("，") + "。"
    if slot == "last":
        still = last_still_text(item) or end
        bits = [
            "数字电影 CG 静帧，16:9，禁止真人、photoreal、real person。",
            f"{size}，{lens}，{angle}。",
            f"落幅定住：{end.rstrip('。')}。" if end else "",
            f"尾帧画面：{still.rstrip('。')}。" if still else "",
            f"左：{left.rstrip('。')}。右：{right.rstrip('。')}。" if left or right else "",
            f"视线：{eyeline.rstrip('。')}。" if eyeline else "",
            f"连戏必须照做：{note.rstrip('。')}。" if note else "",
            light_line,
            "画动作已经完成的那一格，对得上 out_to。",
            "数字电影感绘画静帧，有体积和绘画颗粒，不是照片，不是动漫。皮肤有纹理，不要磨皮塑料脸。",
            "不要字幕、水印、国旗、现代天际线、吴哥塔、环绕构图。",
        ]
        return "".join(bit for bit in bits if bit)
    still = first_still_text(item) if item else ""
    still_para = str((item.get("still_start") or {}).get("one_paragraph") or item.get("one_paragraph") or still or "").strip()
    holding = str((item.get("still_start") or {}).get("holding") or (item.get("subject") or {}).get("holding") or "").strip()
    bits = [
        "数字电影 CG 静帧，16:9，禁止真人、photoreal、real person。",
        f"{size}，{lens}，{angle}。",
        "画动作尚未发生的那一格。",
        f"起幅定住：{start.rstrip('。')}。" if start else "",
        f"首帧（第0秒）：{still_para.rstrip('。')}。" if still_para else "",
        f"起幅拿着：{holding.rstrip('。')}。" if holding else "",
        f"画面：{still_subject.rstrip('。')}。" if still_subject else "",
        f"画面描述：{picture}" if picture else "",
        f"左：{left.rstrip('。')}。右：{right.rstrip('。')}。" if left or right else "",
        f"视线：{eyeline.rstrip('。')}。" if eyeline else "",
        f"连戏必须照做：{note.rstrip('。')}。首帧只守服装、在场、绑法；note 里的动作结果不要画进这一格。" if note else "",
        light_line,
        f"本镜之后才会发生，不要画成已完成：{action.rstrip('。')}。" if action else "",
        forbidden_result_clause(action),
        "动作尚未发生，不要画出落幅。禁止把 one_action 的结果画进首帧。",
        "数字电影感绘画静帧，有体积和绘画颗粒，不是照片，不是动漫。皮肤有纹理，不要磨皮塑料脸。",
        "不要字幕、水印、国旗、现代天际线、吴哥塔、环绕构图。",
    ]
    return "".join(bit for bit in bits if bit)


REFERENCE_ROLE_MARK = re.compile(r"\[图\s*\d+\]|@(?:图)?\s*\d+")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_ASSET_ID_NOISE = re.compile(r"^(?:CHAR|LOC|PROP)_|_V\d+$", re.I)


def has_reference_roles(text: str) -> bool:
    """True when the prompt already names its reference images ([图1] / @图1 / @1：), so nothing is injected twice."""
    return bool(REFERENCE_ROLE_MARK.search(str(text or "")))


def _ref_kind(ref: str, item: dict) -> str:
    rid = str(ref or "").lower()
    file = str(item.get("file") or "").replace("\\", "/").lower()
    kind = str(item.get("type") or "").lower()
    if file.endswith("sheet.jpg") or "sheet" in rid:
        return "sheet"
    if file.endswith("face.jpg") or "face" in rid:
        return "face"
    if kind == "location" or rid.startswith("loc_"):
        return "location"
    if kind in {"character", "costume_state"} or rid.startswith("char_"):
        return "character"
    if kind == "prop" or rid.startswith("prop_"):
        return "prop"
    return "other"


def compile_reference_roles_zh(refs: list[str], assets: dict, *, parent_first: bool = True) -> str:
    """One job per reference image, numbered [图1]…[图N] in asset_refs order.

    Plate → camera / space / light; face or passport → face and wardrobe only; sheet → the panel
    matching this shot's camera; prop → shape and state only. With `parent_first` a leading plate is
    the parent image (本场空镜) the frame is edited from. Non-image assets (LOOK.md) take no number.
    """
    by_id = {str(item.get("asset_id")): item for item in (assets or {}).get("assets") or [] if item.get("asset_id")}
    bits: list[str] = []
    for ref in refs or []:
        item = by_id.get(str(ref)) or {}
        file = str(item.get("file") or "")
        if item and (str(item.get("type") or "") == "style" or (file and not file.lower().endswith(_IMAGE_SUFFIXES))):
            continue
        kind = _ref_kind(ref, item)
        name = str(item.get("name") or item.get("binds_to") or _ASSET_ID_NOISE.sub("", str(ref)).lower().replace("_", "-"))
        base = Path(file).name if file else ""
        n = len(bits) + 1
        if kind == "location":
            if parent_first and n == 1:
                bits.append(f"[图1] 是父图（本场空镜 {name}）：机位、空间、光位、画幅以此为准，只改一件事。")
            else:
                bits.append(f"[图{n}] 是本场空镜 {name}：机位、空间、光位以此为准，不当画布。")
        elif kind == "sheet":
            bits.append(f"[图{n}] 是 {name} 的 {base or 'sheet.jpg'}：取与本镜机位一致的面板，不当首帧。")
        elif kind in {"face", "character"}:
            what = f"{name} 的 {base}" if base else (f"{name} 的 face.jpg" if kind == "face" else f"{name} 的护照")
            bits.append(f"[图{n}] 是 {what}：只锁脸和衣服，不参考构图姿势。")
        elif kind == "prop":
            bits.append(f"[图{n}] 是道具 {name}：只认这件道具的形状和状态。")
        else:
            bits.append(f"[图{n}] 是 {name}：只作参考，不当画布。")
    if not bits:
        return ""
    bits.append("各图身份边界不混，不把别的图的人物画进来。")
    return "".join(bits)


KHMERLESS_TAIL = "底板无高棉文、无汉字；厂牌拉丁文可留；不要让模型在招牌或工牌上新写高棉文。"


def strip_reference_roles_zh(text: str) -> tuple[str, str]:
    """Split a still prompt into (body without [图N] block, preserved khmerless tail)."""
    raw = str(text or "")
    tail = ""
    if KHMERLESS_TAIL in raw:
        raw = raw.replace(KHMERLESS_TAIL, "")
        tail = KHMERLESS_TAIL
    idx = raw.find("[图")
    if idx >= 0:
        raw = raw[:idx]
    return raw.rstrip(), tail


def compile_reference_roles_from_files(files: list[str], assets: dict) -> str:
    """Number [图N] by the actual Codex still list, not the untruncated Seedance 9-cap ids."""
    slash = chr(92)
    by_file = {}
    for item in (assets or {}).get("assets") or []:
        rel = str(item.get("file") or "").replace(slash, "/")
        if rel:
            by_file[rel] = item
    bits: list[str] = []
    for i, raw in enumerate(files or [], 1):
        rel = str(raw or "").replace(slash, "/").lstrip("./")
        if not rel:
            continue
        item = by_file.get(rel) or {}
        if not item and rel.endswith("face.jpg"):
            item = by_file.get(rel[: -len("face.jpg")] + "master.jpg") or {}
        name = str(item.get("name") or item.get("binds_to") or Path(rel).parent.name)
        base = Path(rel).name
        if i == 1:
            if rel.startswith("04-frames/"):
                bits.append("[图1] 是父图（上一镜过闸首帧）：机位、空间、光位、画幅以此为准，只改一件事。")
            else:
                loc_name = name if item.get("type") == "location" else Path(rel).parent.name
                bits.append(f"[图1] 是父图（本场空镜 {loc_name}）：机位、空间、光位、画幅以此为准，只改一件事。")
            continue
        kind = _ref_kind(item.get("asset_id") or "", item)
        if rel.endswith("face.jpg"):
            kind = "face"
        if kind == "location":
            bits.append(f"[图{i}] 是本场空镜 {name}：机位、空间、光位以此为准，不当画布。")
        elif kind == "sheet":
            bits.append(f"[图{i}] 是 {name} 的 {base}：取与本镜机位一致的面板，不当首帧。")
        elif kind in {"face", "character"} or item.get("type") in {"character", "costume_state"}:
            what = f"{name} 的 {base}" if base else f"{name} 的护照"
            bits.append(f"[图{i}] 是 {what}：只锁脸和衣服，不参考构图姿势。")
        elif kind == "prop" or item.get("type") == "prop":
            bits.append(f"[图{i}] 是道具 {name}：只认这件道具的形状和状态。")
        else:
            bits.append(f"[图{i}] 是 {name}：只作参考，不当画布。")
    if not bits:
        return ""
    bits.append("各图身份边界不混，不把别的图的人物画进来。")
    return "".join(bits)


def rewrite_still_prompt(prompt: str, files: list[str], assets: dict) -> str:
    """Drop leftover 9-cap [图N] numbering and rewrite from the files actually sent."""
    body, tail = strip_reference_roles_zh(prompt)
    roles = compile_reference_roles_from_files(files, assets)
    return "".join(part for part in (body, roles, tail) if part)


_EDIT_CUT = re.compile(r"立刻切|片内切|硬切|转切|cut\s+to|切到", re.I)
_COMPOSITION_CUT = re.compile(r"切(?:在|小腿|脚|腰|画)")
_CLAUSE_SPLIT = re.compile(r"[，,；;]")
_NEXT_SETUP = re.compile(r"下一镜")


def sanitize_camera_state(text: str) -> str:
    """Keep this camera's start/end state. Drop edit-cut / next-setup language.

    Composition cuts stay: 画面下缘切在小腿. Edit cuts go: 立刻切她的怕 / 切到门口.
    """
    raw = str(text or "").strip().rstrip("。.")
    if not raw:
        return ""
    kept: list[str] = []
    for clause in _CLAUSE_SPLIT.split(raw):
        bit = clause.strip().rstrip("。.")
        if not bit:
            continue
        if _NEXT_SETUP.search(bit) or _EDIT_CUT.search(bit):
            continue
        if "切" in bit and not _COMPOSITION_CUT.search(bit):
            continue
        kept.append(bit)
    return "，".join(kept)


def compile_seedance_motion_from_spec(
    spec: dict,
    shot: Optional[dict] = None,
    profile: Optional[dict] = None,
) -> str:
    """Motion-only Chinese prompt for Seedance. How it moves, not a new costume description.

    Default is one shot, one camera setup. `internal_cuts` only compile when the
    profile opts in (`max_internal_cuts > 0` and multi-setup allowed).
    """
    shot = shot or {}
    action = _spec_text(spec, "action_now", "content") or str(shot.get("one_action") or "")
    start = sanitize_camera_state(_spec_text(spec, "in_from") or str(shot.get("in_from") or ""))
    end = sanitize_camera_state(_spec_text(spec, "out_to") or str(shot.get("out_to") or ""))
    move = _spec_text(spec, "move_type") or str(shot.get("move_type") or "static")
    move_line = MOVE_ZH.get(move, MOVE_ZH["static"])
    try:
        duration = int(float(spec.get("duration_sec") or shot.get("duration_sec") or 4))
    except (TypeError, ValueError):
        duration = 4
    parts = [f"时长约{duration}秒。"]
    if start:
        parts.append(f"从起幅开始：{start.rstrip('。')}。")
    if action:
        parts.append(f"本镜只做一件事：{action.rstrip('。')}。")
    parts.append("运镜：" + move_line + "。")
    from .video_profiles import allows_internal_cuts

    if allows_internal_cuts(profile):
        for cut in spec.get("internal_cuts") or shot.get("internal_cuts") or []:
            at = cut.get("at_sec")
            scale = SIZE_ZH.get(str(cut.get("scale") or ""), str(cut.get("scale") or ""))
            beat = str(cut.get("one_action") or "").rstrip("。")
            if beat:
                parts.append(f"{at}秒时片内切到{scale}：{beat}。")
    if end:
        parts.append(f"落幅停在：{end.rstrip('。')}。")
    parts.append("整段停在本机位，不要换地点、不要换机位。不要字幕、水印，不要把对白烧进画面。保持同一张脸、同一套衣服。")
    note = state_note_of(spec, shot)
    if note:
        parts.append(f"连戏不变：{note.rstrip('。')}。")
    delivery = _spec_text(spec, "dialogue_delivery") or str(shot.get("dialogue_delivery") or "")
    lines = [str(item).strip() for item in (spec.get("dialogue_lines") or []) if str(item).strip()]
    if not lines:
        line = _spec_text(spec, "dialogue_line")
        if line:
            lines = [line]
        for item in shot.get("dialogue_ref") or []:
            text = str((item or {}).get("line") or "").strip()
            if text and text not in lines:
                lines.append(text)
    if lines and delivery == "on_camera":
        quoted = " / ".join("「" + line + "」" for line in lines[:2])
        parts.append("人物用中文原句口型说话：" + quoted + "。")
    elif lines:
        parts.append("对白不进画面，后期另叠。")
    return " ".join(parts)


def compile_seedance_prompt(shot: dict, spec: Optional[dict] = None) -> str:
    """Chinese image-to-video prompt. Do not wrap H3 English three-field syntax."""
    spec = spec or {}
    parts = []
    action = str(spec.get("action_now") or spec.get("content") or shot.get("action") or "").strip()
    move = str(spec.get("move_detail") or shot.get("camera") or "").strip()
    look = str(spec.get("color_mood") or shot.get("look") or "").strip()
    size = str(spec.get("shot_size") or shot.get("setup") or "").strip()
    body = str(shot.get("video_prompt") or shot.get("prompt") or "").strip()
    if _looks_chinese(body):
        parts.append(body)
    else:
        if size:
            parts.append("景别：" + size)
        if action:
            parts.append(action.rstrip("。") + "。")
        if move:
            parts.append("镜头：" + move.rstrip("。") + "。")
        if look:
            parts.append(look.rstrip("。") + "。")
        if not parts and body:
            parts.append(body)
    if not parts:
        raise PermissionError(f"{shot.get('id', 'shot')} 没有可给 Seedance 的画面句子")
    parts.append("不要字幕，不要水印，不要口型对白烧进画面。保持同一房间、同一张脸、同一套衣服。")
    line = str(spec.get("dialogue_line") or shot.get("line") or "").strip()
    if line:
        parts.append("对白不进画面，后期另叠：" + line)
    return " ".join(parts)


def default_soundscape(shot: dict) -> str:
    explicit = str(shot.get("sfx") or "").strip()
    if explicit:
        return explicit.rstrip(".") + "."
    scene = str(shot.get("scene") or "")
    if "office" in scene or "corridor" in scene:
        return "Quiet factory corridor, sewing machines muffled through glass, distant motorbikes."
    if "factory" in scene:
        return "Factory sewing motors, cloth rustle, distant motorbikes outside."
    return "Quiet room tone, no score."


def compile_h3_fields(shot: dict, *, silent: bool = True, refs: Optional[list[str]] = None) -> dict:
    body = str(shot.get("video_prompt") or shot.get("prompt") or "").strip()
    if not body:
        raise PermissionError(f"{shot.get('id', 'shot')} 没有 video_prompt")
    chunks = []
    if silent:
        chunks.append("No spoken dialogue. No lip-sync. Burned-in captions are forbidden.")
    chunks.append(h3_timeline(shot))
    chunks.append(body)
    chunks.append(h3_retention(shot, refs))
    negatives = str(shot.get("negatives") or "").strip() or default_negatives_for(shot)
    chunks.append(space_lock_for(shot))
    chunks.append("Avoid: " + negatives)
    description = " ".join(chunks)
    return {
        "alignment": h3_alignment(shot),
        "integrated_multimodal_description": description,
        "overall_soundscape": default_soundscape(shot),
        "non_diegetic_music": "N/A",
    }


def format_h3_prompt(fields: dict) -> str:
    alignment = str(fields.get("alignment") or "").strip()
    body = (
        "integrated_multimodal_description: "
        + str(fields.get("integrated_multimodal_description") or "").strip()
        + "\noverall_soundscape: "
        + str(fields.get("overall_soundscape") or "").strip()
        + "\nnon_diegetic_music: "
        + str(fields.get("non_diegetic_music") or "N/A").strip()
    )
    if alignment:
        return alignment + "\n\n" + body
    return body


def one_change(shot: dict) -> str:
    setup = str(shot.get("setup") or "").strip()
    move = str(shot.get("move") or "").strip()
    cut = str(shot.get("cut") or "").strip()
    derived = str(shot.get("derived_from") or "").strip()
    if cut == "hard" or derived.endswith(".blocking"):
        return f"From the set blocking still, keep the room. Frame a {setup or 'locked'} start pose only."
    return (
        f"Edit the parent still. Keep the same room, faces and wardrobe. "
        f"Change only this: reframe to {setup or 'this setup'}"
        + (f" with a {move} already underway" if move and move != "static" else "")
        + ". Second 0 is already mid-action. Do not reset to a planted rest pose. Do not complete the action."
    )


def compile_still_prompt(shot: dict) -> str:
    start = str(shot.get("start") or "").strip()
    if not start:
        raise PermissionError(f"{shot.get('id', 'shot')} 没有 start，不能出静帧")
    change = one_change(shot)
    look = str(shot.get("look") or "").strip()
    lens = str(shot.get("lens") or "").strip()
    setup = str(shot.get("setup") or "").strip()
    cut = str(shot.get("cut") or "").strip()
    derived = str(shot.get("derived_from") or "").strip()
    planted = cut == "hard" or derived.endswith(".blocking")
    if planted:
        timing = "Second 0 only. Hold the start pose. Do not show walking-in, box-slamming, sleeve-rolling, or camera moves as already finished."
    else:
        timing = "Second 0 is already mid-action. Draw the gesture halfway through. Do not plant a rest pose. Do not complete the action."
    chunks = [
        "Still frame only, not a video. Widescreen 16:9 photoreal cinematic still.",
        "Edit the parent image. Do not generate a new poster.",
        timing,
        "One change only from the parent still.",
        change,
        f"Start pose: {start.rstrip('.')}.",
    ]
    if lens or setup:
        chunks.append(" ".join(item for item in (lens, setup, "hold" if planted else "mid-action") if item) + ".")
    if look:
        chunks.append(look.rstrip(".") + ".")
    chunks.append("Keep the same wardrobe, faces and room geography. No subtitle, no watermark, no lip-sync speech.")
    chunks.append(space_lock_for(shot))
    return " ".join(chunks)


def identity_refs(refs: Optional[list[str]] = None) -> list[str]:
    out = []
    for item in refs or []:
        name = str(item).replace("\\", "/").lower()
        if name.endswith(("sheet.jpg", "face.jpg")):
            out.append(str(item))
    return out


def video_mode(shot: dict, source_kind: str, refs: Optional[list[str]] = None) -> str:
    """Primary H3 path is always first-frame FL2VA.

    Designed `end_frame` upgrades that to first+last. Identity refs hang outside
    the first frame and never replace it. Generated `{id}-last.jpg` is not a
    designed end frame. Label `r2v` only when there is no designed end frame;
    the GPU adapter still hangs refs on FL2VA/FLF either way.
    """
    rel = str(shot.get("end_frame") or "").strip()
    if rel and not Path(rel).name.lower().endswith("-last.jpg"):
        return "flf"
    # Dedicated Ref2VA UNet is optional. Until it is installed, keep the
    # first-frame FL2VA path instead of hanging refs onto ReferenceToVideo.
    return "i2v"


def require_sheet_for_new_frame(prod: Path, dest_rel: str) -> None:
    dest = str(dest_rel)
    if not dest.startswith("04-frames/"):
        return
    from .gates import require_fresh_gate

    require_fresh_gate(prod, "C")
    shot_id = Path(dest).stem
    path = prod / "03-storyboard" / "shots.json"
    shots = json.loads(path.read_text(encoding="utf-8")).get("shots") if path.exists() else []
    shots = shots or []
    shot = next((item for item in shots if item.get("id") == shot_id), None)
    if not shot:
        return
    missing = missing_sheets(prod, shot)
    if missing:
        raise PermissionError("新首帧必须挂联络板，缺 sheet.jpg：" + ", ".join(missing))
