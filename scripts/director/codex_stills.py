"""Codex still-frame contract: 5-ref cap, parent first, costume masters, identity gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

CODEX_STILL_MAX_REFS = 5
CHECK_KEYS = ("in_frame", "absent", "left_right", "costume", "bopha", "text")
IDENTITY_GATES = ("pass", "fail", "awaiting_user")
BLOCK_STILLS_FROM_EPISODE = 6

REVIEW_SHOTS = {
    2: {"starts": ["SH001", "SH014", "SH020"], "hardest": ["SH005", "SH013", "SH017", "SH028"]},
    3: {"starts": ["SH001", "SH009", "SH021"], "hardest": ["SH006", "SH011", "SH023"]},
    4: {"starts": ["SH001", "SH012", "SH021"], "hardest": ["SH007", "SH015", "SH024"]},
    5: {"starts": ["SH001", "SH008", "SH014", "SH020"], "hardest": ["SH004", "SH010", "SH017", "SH029"]},
}


class StillPackError(ValueError):
    """Costume plate or parent required for a Codex still is missing or invalid."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _rel(value: Any) -> str:
    return _text(value).replace(chr(92), '/').lstrip('./')


def missing_costume_state_files(prod: Path, refs: list[str], assets: dict) -> list[str]:
    """Hard errors when a selected costume_state asset is not on disk."""
    by_id = {item.get("asset_id"): item for item in (assets.get("assets") or []) if item.get("asset_id")}
    missing: list[str] = []
    for rid in refs or []:
        item = by_id.get(rid) or {}
        if item.get("type") != "costume_state":
            continue
        rel = _rel(item.get("file"))
        if rel and not (Path(prod) / rel).exists():
            missing.append(f"{rid} file missing: {rel}")
    return missing


def scene_master_rel(location_id: str) -> str:
    loc = _rel(location_id)
    return f"02-assets/scenes/{loc}/master.jpg"


def review_role_for(episode, shot_id: str) -> str:
    from director.pipeline import episode_number

    spec = REVIEW_SHOTS.get(episode_number(episode)) or {}
    sid = _text(shot_id)
    if sid in (spec.get("starts") or []):
        return "scene_start"
    if sid in (spec.get("hardest") or []):
        return "hardest"
    return "normal"


def identity_gate_from_checks(checks: dict, review_role: str) -> str:
    for key in CHECK_KEYS:
        if _text((checks or {}).get(key)) != "pass":
            return "fail"
    if review_role in {"scene_start", "hardest"}:
        return "awaiting_user"
    return "pass"


def parse_checks(raw: str) -> dict:
    text = _text(raw)
    if not text:
        raise StillPackError("promote 必须带 --checks in_frame=pass,absent=pass,...")
    if text.startswith("{"):
        import json

        data = json.loads(text)
        if not isinstance(data, dict):
            raise StillPackError("checks JSON 必须是对象")
        out = {key: _text(data.get(key)) for key in CHECK_KEYS}
    else:
        out = {key: "" for key in CHECK_KEYS}
        for part in text.split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = _text(key)
            if key in out:
                out[key] = _text(value)
    missing = [key for key in CHECK_KEYS if out.get(key) not in {"pass", "fail"}]
    if missing:
        raise StillPackError("checks 缺项或取值不是 pass/fail：" + ", ".join(missing))
    return out


def episode_still_blocked(prod: Path, episode) -> str:
    from director.pipeline import episode_number

    if Path(prod).name == "010-gongpai" and episode_number(episode) >= BLOCK_STILLS_FROM_EPISODE:
        return "010-gongpai EP06–EP15 静帧未开：闸门和 EP02 样片过了再出"
    return ""


def item_is_costume_path(rel: str) -> bool:
    path = _rel(rel)
    return "/rin-line-leader/" in path or "/rin-guest/" in path


def pack_codex_still_refs(
    prod: Path,
    *,
    parent: str,
    state: Optional[dict],
    assets: dict,
    table: Optional[dict] = None,
    hard: Optional[dict] = None,
    episode: int = 1,
    max_refs: int = CODEX_STILL_MAX_REFS,
    strict_existing: bool = True,
) -> list[str]:
    """Image 1 = this shot parent. Remaining slots = in-frame costume masters (faces if over cap).

    Location plates are not repeated in slots 2-5. Missing costume_state master is a hard error.
    """
    from .continuity_hard import resolve_costume_token
    from .pipeline import _pick_character_by_state, resolve_cast_bind
    from .shot_table import normalize_state

    parent_rel = _rel(parent)
    if not parent_rel:
        raise StillPackError("静帧参考缺少父图")
    if strict_existing and not (Path(prod) / parent_rel).exists():
        raise StillPackError(f"父图不存在：{parent_rel}")

    items = [item for item in (assets.get("assets") or []) if item.get("asset_id")]
    by_id = {item.get("asset_id"): item for item in items}
    bible = table.get("continuity_bible") if isinstance(table, dict) and isinstance(table.get("continuity_bible"), dict) else {}
    norm = normalize_state(state) if isinstance(state, dict) else None
    chars = (norm or {}).get("characters") if isinstance(norm, dict) else {}
    if not isinstance(chars, dict):
        chars = {}

    identity: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for cid, cstate in chars.items():
        if not isinstance(cstate, dict) or cstate.get("in_frame") is False:
            continue
        bind = resolve_cast_bind(cid, bible, items)
        if not bind or bind in seen:
            continue
        seen.add(bind)
        costume = resolve_costume_token(hard, cid, episode, cstate.get("costume") or "")
        ids = _pick_character_by_state(items, bind, costume, faces=True)
        master_rel = ""
        face_rel = ""
        costume_item = None
        for aid in ids:
            item = by_id.get(aid) or {}
            rel = _rel(item.get("file"))
            if item.get("type") == "costume_state":
                costume_item = item
                if rel.endswith("master.jpg"):
                    master_rel = rel
            elif rel.endswith("face.jpg"):
                face_rel = rel
            elif rel.endswith("master.jpg") and not master_rel:
                master_rel = rel
        if costume_item and not master_rel:
            master_rel = _rel(costume_item.get("file"))
        if not master_rel:
            for item in items:
                if _text(item.get("binds_to")) == bind and item.get("type") == "character":
                    rel = _rel(item.get("file"))
                    if rel.endswith("master.jpg"):
                        master_rel = rel
                        break
        if not master_rel:
            continue
        is_costume = bool(costume_item) or item_is_costume_path(master_rel)
        if not (Path(prod) / master_rel).exists():
            if is_costume:
                raise StillPackError(f"缺服装护照 {bind} {costume or ''}: {master_rel}")
            if strict_existing:
                raise StillPackError(f"缺角色护照 {bind}: {master_rel}")
        if not face_rel:
            sibling = master_rel[: -len("master.jpg")] + "face.jpg" if master_rel.endswith("master.jpg") else ""
            if sibling and (Path(prod) / sibling).exists():
                face_rel = sibling
            else:
                base_face = f"02-assets/characters/{bind}/face.jpg"
                if (Path(prod) / base_face).exists():
                    face_rel = base_face
        identity.append((bind, master_rel, face_rel))

    files = [parent_rel]
    slots = max(0, int(max_refs) - 1)
    if len(identity) <= slots:
        chosen = [master for _bind, master, _face in identity]
    else:
        chosen = [face or master for _bind, master, face in identity[:slots]]
    for rel in chosen:
        if rel and rel not in files:
            files.append(rel)
        if len(files) >= int(max_refs):
            break
    return files[: int(max_refs)]


def first_frame_parent(
    prod: Path,
    shot_id: str,
    episode,
    location_id: str,
    still_parent: str = "",
) -> tuple[str, bool]:
    """(parent_rel, allow_master).

    An explicit still_parent in the episode table is authoritative. This is
    needed for deliberate re-anchoring shots such as the EP01-v2 corridor
    block, where several shots must restart from the factory-gate plate even
    though they share a scene id. Without this branch, the generic same-scene
    continuation rule silently replaces the table's parent with the previous
    frame.
    """
    from place_codex_frame import previous_same_scene_parent

    hint = _rel(still_parent)
    if hint:
        return hint, True
    prev = previous_same_scene_parent(prod, shot_id, episode)
    if prev:
        return prev, False
    return scene_master_rel(location_id), True


def scene_blocked_for_later(prod: Path, episode: int, scene_id: str, shots: list[dict], current_shot_id: str = "") -> str:
    """Why this shot must not generate yet. Empty = allowed. Scene-start itself is never blocked here."""
    from director.paths import safe_under
    from place_codex_frame import dest_rel, identity_gate_of

    scene = _text(scene_id)
    current = _text(current_shot_id)
    previous: list[tuple[str, str, bool]] = []
    for row in shots:
        if _text(row.get("scene_id")) != scene:
            continue
        sid = _text(row.get("shot_id") or row.get("id"))
        if current and sid == current:
            break
        rel = dest_rel(sid, "first", episode)
        exists = safe_under(prod, rel).exists()
        gate = identity_gate_of(prod, rel) if exists else ""
        previous.append((sid, gate, exists))
    if not previous:
        return ""
    start_sid, start_gate, start_exists = previous[0]
    if not start_exists:
        return f"场首镜 {start_sid} 未出，该场后续不出"
    if start_gate != "pass":
        return f"场首镜 {start_sid} identity_gate={start_gate or 'missing'}，该场后续不出"
    for prev_sid, prev_gate, exists in previous:
        if exists and prev_gate == "fail":
            return f"{prev_sid} identity_gate=fail，停场"
        if not exists:
            return f"{prev_sid} 未出，停场"
    return ""
