"""Frame descriptions: the second descriptive layer under each shot.

`one_action` says what happens (video / motion). A frame description says what
the *first still* is at t=0: three depth layers, light, hands, composition.
`still_end` / `last_paragraph` is the last still when the plan is first_last.

Artifact: `.pipeline/frame_descriptions.json` (schema `frame-desc-v1`).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .acting import normalize_acting, text_acting_warnings
from .shot_table import OTC_COVERAGE, _t as _shot_t, facing_class, turn_is_written
from .still_t0 import normalize_still, still_t0_errors

SCHEMA = "frame-desc-v1"
GENERIC_WORDS = ("电影感", "氛围拉满", "高级感", "大片感", "质感拉满", "史诗", "震撼", "cinematic vibe", "epic")
REALISM_WORDS = ("真人", "photoreal", "real person", "live-action", "实拍照片")
LAYER_KEYS = ("foreground", "midground", "background")
LIGHT_KEYS = ("key", "fill", "practical", "quality")
SUBJECT_KEYS = ("facing", "hands", "holding", "micro_expression")
COMPOSITION_KEYS = ("weight", "negative_space", "headroom")
MAX_PARAGRAPH = 220


def _t(value: Any) -> str:
    return str(value or "").strip()


def normalize_item(item: Any) -> dict:
    raw = dict(item) if isinstance(item, dict) else {}
    layers = raw.get("layers") if isinstance(raw.get("layers"), dict) else {}
    light = raw.get("light") if isinstance(raw.get("light"), dict) else {}
    subject = raw.get("subject") if isinstance(raw.get("subject"), dict) else {}
    composition = raw.get("composition") if isinstance(raw.get("composition"), dict) else {}
    forbidden = raw.get("forbidden")
    if isinstance(forbidden, str):
        forbidden = [f.strip() for f in re.split(r"[、,，;；\n]", forbidden) if f.strip()]
    still_start = normalize_still(raw.get("still_start"))
    still_end = normalize_still(raw.get("still_end"))
    one_paragraph = _t(raw.get("one_paragraph") or still_start.get("one_paragraph"))
    last_paragraph = _t(raw.get("last_paragraph") or still_end.get("one_paragraph"))
    if not still_start.get("one_paragraph") and one_paragraph:
        still_start["one_paragraph"] = one_paragraph
    if not still_end.get("one_paragraph") and last_paragraph:
        still_end["one_paragraph"] = last_paragraph
    holding = _t(subject.get("holding") or still_start.get("holding"))
    return {
        "shot_id": _t(raw.get("shot_id")),
        "layers": {key: _t(layers.get(key)) for key in LAYER_KEYS},
        "light": {key: _t(light.get(key)) for key in LIGHT_KEYS},
        "subject": {**{key: _t(subject.get(key)) for key in SUBJECT_KEYS}, "holding": holding},
        "composition": {key: _t(composition.get(key)) for key in COMPOSITION_KEYS},
        "height_meaning": _t(raw.get("height_meaning")),
        "forbidden": [_t(f) for f in (forbidden or []) if _t(f)],
        "one_paragraph": one_paragraph,
        "last_paragraph": last_paragraph,
        "still_start": still_start,
        "still_end": still_end,
        # 7a may write acting for the people in frame; it lays over the table row field by field.
        "acting": normalize_acting(raw.get("acting")),
    }


def acting_text_fields(item: dict) -> dict[str, str]:
    """The free-text fields of one normalized item that must not carry emotion adjectives."""
    fields: dict[str, str] = {
        "one_paragraph": item.get("one_paragraph", ""),
        "last_paragraph": item.get("last_paragraph", ""),
        "subject.micro_expression": (item.get("subject") or {}).get("micro_expression", ""),
    }
    for slot in ("still_start", "still_end"):
        for key, value in (item.get(slot) or {}).items():
            if value:
                fields[f"{slot}.{key}"] = value
    for who, acting in (item.get("acting") or {}).items():
        for key in ("business", "muscle", "change"):
            if acting.get(key):
                fields[f"acting.{who}.{key}"] = acting[key]
    # normalize_item mirrors one_paragraph into still_start; the same text should warn once.
    seen: set[str] = set()
    out: dict[str, str] = {}
    for key, value in fields.items():
        if value and value not in seen:
            seen.add(value)
            out[key] = value
    return out


def frame_description_warnings(data: dict) -> list[str]:
    """`acting_adjective` warnings across every 7a item. Warning, not error: the still is not bricked."""
    out: list[str] = []
    items = (data or {}).get("items")
    for raw in items if isinstance(items, list) else []:
        item = normalize_item(raw)
        out.extend(text_acting_warnings(item["shot_id"], acting_text_fields(item)))
    return out


def validate_frame_descriptions(
    data: dict,
    shot_ids: Optional[list[str]] = None,
    shots: Optional[list[dict]] = None,
    *,
    still_t0: str = "error",
) -> list[str]:
    errors: list[str] = []
    if _t(data.get("schema")) != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["frame_descriptions empty"]
    by_shot = {_shot_t(s.get("shot_id")): s for s in (shots or []) if _shot_t(s.get("shot_id"))}
    seen: set[str] = set()
    prev_item: Optional[dict] = None
    prev_shot: Optional[dict] = None
    for raw in items:
        item = normalize_item(raw)
        sid = item["shot_id"] or "?"
        if sid in seen:
            errors.append(f"{sid} described twice")
        seen.add(sid)
        if shot_ids and sid not in shot_ids:
            errors.append(f"{sid} is not a shot in the table")
        for key in ("foreground", "midground", "background"):
            if not item["layers"][key]:
                errors.append(f"{sid} layers.{key} empty (write 无 if truly nothing)")
        if not item["light"]["key"]:
            errors.append(f"{sid} light.key must say where the key light comes from")
        if not item["subject"]["hands"] and not item["subject"]["facing"]:
            errors.append(f"{sid} subject needs facing or hands (write 无人 for empty frames)")
        if not item["composition"]["weight"]:
            errors.append(f"{sid} composition.weight empty")
        paragraph = item["one_paragraph"]
        if not paragraph:
            errors.append(f"{sid} one_paragraph empty")
        elif len(paragraph) > MAX_PARAGRAPH:
            errors.append(f"{sid} one_paragraph is {len(paragraph)} chars; keep it under {MAX_PARAGRAPH}")
        last_para = item["last_paragraph"]
        if last_para and len(last_para) > MAX_PARAGRAPH:
            errors.append(f"{sid} last_paragraph is {len(last_para)} chars; keep it under {MAX_PARAGRAPH}")
        blob = " ".join([
            paragraph, last_para, *item["layers"].values(), *item["light"].values(),
            *item["subject"].values(), *item["composition"].values(), item["height_meaning"],
            *item["still_start"].values(), *item["still_end"].values(),
        ]).lower()
        for word in GENERIC_WORDS:
            if word.lower() in blob:
                errors.append(f"{sid} uses empty adjective 「{word}」; describe what is in frame instead")
                break
        for word in REALISM_WORDS:
            if word.lower() in blob:
                errors.append(f"{sid} says 「{word}」; the look is digital-film CG, do not ask for a real person")
                break
        shot = by_shot.get(sid)
        facing = item["subject"]["facing"]
        if shot and _shot_t(shot.get("coverage_type")) in OTC_COVERAGE:
            if facing_class({"body_facing": facing, "left": item["layers"]["foreground"]}) == "back" or "背对镜头" in facing or "后脑" in facing:
                errors.append(f"{sid} otc frame_desc facing is 背对镜头/后脑; over-shoulder is not a back view")
        if shot and still_t0 == "error":
            errors.extend(still_t0_errors(shot, item))
        if prev_item and shot and prev_shot and _shot_t(prev_shot.get("scene_id")) == _shot_t(shot.get("scene_id")):
            prev_face = facing_class({"body_facing": prev_item["subject"]["facing"]})
            this_face = facing_class({"body_facing": facing})
            if prev_face and this_face and prev_face != this_face:
                if not (turn_is_written(prev_shot) or turn_is_written(shot)):
                    errors.append(
                        f"{sid} frame_desc facing flips {prev_face}→{this_face} from {prev_item['shot_id']} "
                        f"with no 转身/回头 on the table"
                    )
        prev_item = item
        prev_shot = shot
    for sid in shot_ids or []:
        if sid not in seen:
            errors.append(f"{sid} has no frame description")
    return errors


def index_by_shot(data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for raw in (data or {}).get("items") or []:
        item = normalize_item(raw)
        if item["shot_id"]:
            out[item["shot_id"]] = item
    return out


def description_sentence(item: Optional[dict]) -> str:
    """Compact Chinese sentence for the keyframe prompt. Layers → light → subject → composition."""
    if not item:
        return ""
    item = normalize_item(item)
    bits: list[str] = []
    layers = item["layers"]
    layer_bits = [f"前景{layers['foreground'].rstrip('。')}" if layers["foreground"] and layers["foreground"] != "无" else "",
                  f"中景{layers['midground'].rstrip('。')}" if layers["midground"] and layers["midground"] != "无" else "",
                  f"背景{layers['background'].rstrip('。')}" if layers["background"] and layers["background"] != "无" else ""]
    layer_bits = [b for b in layer_bits if b]
    if layer_bits:
        bits.append("；".join(layer_bits) + "。")
    light = item["light"]
    light_bits = [f"主光{light['key'].rstrip('。')}" if light["key"] else "",
                  f"补光{light['fill'].rstrip('。')}" if light["fill"] else "",
                  f"实用光源{light['practical'].rstrip('。')}" if light["practical"] else "",
                  light["quality"].rstrip("。") if light["quality"] else ""]
    light_bits = [b for b in light_bits if b]
    if light_bits:
        bits.append("，".join(light_bits) + "。")
    subject = item["subject"]
    holding = _t((item.get("still_start") or {}).get("holding")) or subject["holding"]
    subject_bits = [f"身体{subject['facing'].rstrip('。')}" if subject["facing"] else "",
                    f"手{subject['hands'].rstrip('。')}" if subject["hands"] else "",
                    f"拿着{holding.rstrip('。')}" if holding else "",
                    f"表情{subject['micro_expression'].rstrip('。')}" if subject["micro_expression"] else ""]
    subject_bits = [b for b in subject_bits if b]
    if subject_bits:
        bits.append("，".join(subject_bits) + "。")
    comp = item["composition"]
    comp_bits = [f"构图重心{comp['weight'].rstrip('。')}" if comp["weight"] else "",
                 f"留白{comp['negative_space'].rstrip('。')}" if comp["negative_space"] else "",
                 f"头顶空间{comp['headroom'].rstrip('。')}" if comp["headroom"] else ""]
    comp_bits = [b for b in comp_bits if b]
    if comp_bits:
        bits.append("，".join(comp_bits) + "。")
    if item["height_meaning"]:
        bits.append(item["height_meaning"].rstrip("。") + "。")
    if item["forbidden"]:
        bits.append("画面里不得出现：" + "、".join(item["forbidden"]) + "。")
    return "".join(bits)


def render_frame_descriptions_md(data: dict, title: str = "") -> str:
    lines = [f"# 画面描述 · {title or '第 01 集'}", ""]
    lines.append("每镜一段给人读的**首帧（第 0 秒）**：三层、光、手、构图、机高意味。关键帧 Agent 照这一段画起幅，不照 `one_action` 把结果画进首帧。有尾帧的镜另写落幅。")
    lines.append("")
    for raw in (data or {}).get("items") or []:
        item = normalize_item(raw)
        lines.append(f"## {item['shot_id']}")
        lines.append("")
        lines.append(item["one_paragraph"])
        lines.append("")
        if item["last_paragraph"]:
            lines.append(f"- **落幅**：{item['last_paragraph']}")
        start = item["still_start"]
        if start.get("pose") or start.get("holding") or start.get("prop_state"):
            lines.append(f"- 起幅冻结：姿态 {start.get('pose') or '—'}；拿 {start.get('holding') or item['subject']['holding'] or '—'}；道具 {start.get('prop_state') or '—'}")
        lines.append(f"- 前景 / 中景 / 背景：{item['layers']['foreground'] or '—'} / {item['layers']['midground'] or '—'} / {item['layers']['background'] or '—'}")
        lines.append(f"- 光：主 {item['light']['key'] or '—'}；补 {item['light']['fill'] or '—'}；实用 {item['light']['practical'] or '—'}；{item['light']['quality'] or '—'}")
        lines.append(f"- 人物：{item['subject']['facing'] or '—'}；手 {item['subject']['hands'] or '—'}；拿 {item['subject']['holding'] or '—'}；表情 {item['subject']['micro_expression'] or '—'}")
        lines.append(f"- 构图：重心 {item['composition']['weight'] or '—'}；留白 {item['composition']['negative_space'] or '—'}；头顶 {item['composition']['headroom'] or '—'}")
        if item["height_meaning"]:
            lines.append(f"- 机高意味：{item['height_meaning']}")
        if item["forbidden"]:
            lines.append(f"- 不得出现：{'、'.join(item['forbidden'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def compile_frame_desc_from_shot(shot: dict) -> dict:
    """Deterministic first/last still text from a v2 table row. No LLM.

    The face is described only by what is visible (琳眼瞪大 / 咬牙); feeling words
    in `expression` are dropped (acting is behavior, not adjectives).
    """
    from .acting import physical_expression
    from .still_t0 import result_tokens

    sid = _t(shot.get("shot_id"))
    still = _t(shot.get("still_start") or shot.get("in_from"))
    in_from = _t(shot.get("in_from"))
    out_to = _t(shot.get("out_to"))
    expr = _t(shot.get("expression"))
    action = _t(shot.get("one_action"))
    left = _t(shot.get("left"))
    right = _t(shot.get("right"))
    facing = _t(shot.get("body_facing"))
    light = shot.get("light") if isinstance(shot.get("light"), dict) else {}
    quality = _t(light.get("quality"))
    color = _t(light.get("color"))
    no_face = (not expr) or ("无脸" in expr)
    face = expr if no_face else physical_expression(expr)
    para = "。".join(part.rstrip("。") for part in (still, face, in_from) if part)
    extra = "数字电影 CG，16:9，板上无汉字无高棉文。"
    one = (para + "。" + extra).replace("。。", "。")
    if len(one) > MAX_PARAGRAPH:
        one = "。".join(part.rstrip("。") for part in (still, face) if part)
        one = (one + "。" + extra).replace("。。", "。")[:MAX_PARAGRAPH]
    last_para = ""
    if _t(shot.get("keyframe_plan")) == "first_last":
        last_para = "。".join(part.rstrip("。") for part in (out_to, "动作已完成的那一格") if part)[:MAX_PARAGRAPH]
    forbidden = ["汉字", "可读高棉文", "真人", "photoreal"]
    forbidden.extend(result_tokens(action))
    return normalize_item({
        "shot_id": sid,
        "layers": {
            "foreground": left or still or "无",
            "midground": face or in_from or "无",
            "background": right or _t(shot.get("location_id")) or "无",
        },
        "light": {
            "key": quality or color or "主光守本场灯管方向",
            "fill": "一半灯管冷白散射" if "一半" in quality else (color or "冷白补"),
            "practical": quality or "本场实用光",
            "quality": color or quality or "冷白",
        },
        "subject": {
            "facing": facing or ("无人" if no_face else "朝镜头"),
            "hands": "无人" if no_face and "手" not in expr else (still or "尚未做本镜动作"),
            "holding": _holding_from_still(still, action),
            "micro_expression": face or ("无脸" if no_face else ""),
        },
        "composition": {
            "weight": left or "主体在轴上",
            "negative_space": right or "给动作留方向",
            "headroom": "特写收紧" if _t(shot.get("scale")) in {"close", "insert", "otc"} else "交代空间",
        },
        "height_meaning": _t(shot.get("height")) or "平视",
        "forbidden": forbidden,
        "one_paragraph": one,
        "last_paragraph": last_para,
        "still_start": {
            "pose": still,
            "holding": _holding_from_still(still, action),
            "prop_state": still,
            "one_paragraph": one,
        },
        "still_end": {
            "pose": out_to,
            "holding": "",
            "prop_state": out_to,
            "one_paragraph": last_para,
        },
    })


def _holding_from_still(still: str, action: str) -> str:
    blob = still + action
    if any(token in blob for token in ("钥匙还在", "尚未出手", "手里尚未", "还在手里", "仍在手里")):
        return "钥匙仍在手里"
    if any(token in blob for token in ("钥匙仍在地上", "钥匙还在地上", "尚未弯腰")):
        return "空手，钥匙在地上"
    if "扫把还在墙边" in blob or "未入手" in still:
        return "空手"
    if "旧牌仍在手里" in blob or "尚未入袋" in still:
        return "旧工牌在手里"
    if "扫把还在她手里" in still or "扫把还在手里" in still:
        return "扫把在手里"
    return ""


def compile_frame_descriptions_from_table(table: dict) -> dict:
    items = [compile_frame_desc_from_shot(shot) for shot in (table.get("shots") or []) if _t(shot.get("shot_id"))]
    return {
        "schema": SCHEMA,
        "status": "ready",
        "origin": "compiled-from-shot-table",
        "items": items,
    }
