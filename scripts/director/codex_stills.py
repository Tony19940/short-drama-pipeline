"""Codex still-frame contract: 5-ref cap, parent first, costume masters, identity gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

CODEX_STILL_MAX_REFS = 5
CHECK_KEYS = ("in_frame", "absent", "left_right", "costume", "bopha", "text")
IDENTITY_GATES = ("pass", "fail", "awaiting_user")
_LAST_PACK_REPORT: dict = {}


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


def last_still_pack_report() -> dict:
    return dict(_LAST_PACK_REPORT)


def review_role_for(episode, shot_id: str, prod: Optional[Path] = None) -> str:
    from director.pipeline import episode_number
    from director.show_policy import load_show_policy

    return load_show_policy(prod).review_role(episode_number(episode), shot_id)


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

    from director.show_policy import load_show_policy

    policy = load_show_policy(prod)
    if policy.block_stills_from_episode and episode_number(episode) >= policy.block_stills_from_episode:
        return f"{Path(prod).name} EP{episode_number(episode):02d} 静帧未开：闸门过了再出"
    return ""


def item_is_costume_path(rel: str) -> bool:
    path = _rel(rel)
    return "/rin-line-leader/" in path or "/rin-guest/" in path


def pack_codex_still_refs_report(
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
) -> dict:
    """Parent + scored identity/prop refs. Over-budget items are listed, never silently forgotten."""
    from .continuity_hard import hard_items_for_state, resolve_costume_token
    from .pipeline import _pick_assets, _pick_character_by_state, resolve_cast_bind
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
    prop_ids = list((norm or {}).get("props") or []) if isinstance(norm, dict) else []
    hard_list = hard_items_for_state(hard, episode, norm) if hard and norm else []

    candidates: list[dict] = []
    seen_files: set[str] = set()
    identity: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    for index, (cid, cstate) in enumerate(chars.items()):
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
        score = 50
        if cstate.get("binding") and cstate.get("binding") not in {"none", "unknown", ""}:
            score = 80
        if cstate.get("carrying"):
            score = max(score, 85)
        identity.append((bind, master_rel, face_rel, score))
        candidates.append({
            "role": "identity",
            "name": bind,
            "file": face_rel or master_rel,
            "master": master_rel,
            "face": face_rel,
            "score": score,
            "index": index,
        })

    for pid in list(prop_ids):
        for aid in _pick_assets(items, pid, kind="prop"):
            item = by_id.get(aid) or {}
            rel = _rel(item.get("file"))
            if rel and rel not in seen_files:
                seen_files.add(rel)
                candidates.append({
                    "role": "prop",
                    "name": pid,
                    "file": rel,
                    "score": 90 if pid in hard_list or any(pid in (cstate.get("carrying") or []) for cstate in chars.values() if isinstance(cstate, dict)) else 60,
                    "index": 100 + len(candidates),
                })
    for cid, cstate in chars.items():
        if not isinstance(cstate, dict):
            continue
        for pid in list(cstate.get("carrying") or []) + ([cstate.get("bound_with")] if cstate.get("bound_with") else []):
            if not pid:
                continue
            for aid in _pick_assets(items, str(pid), kind="prop"):
                item = by_id.get(aid) or {}
                rel = _rel(item.get("file"))
                if rel and rel not in seen_files:
                    seen_files.add(rel)
                    candidates.append({
                        "role": "prop",
                        "name": str(pid),
                        "file": rel,
                        "score": 90,
                        "index": 100 + len(candidates),
                    })

    slots = max(0, int(max_refs) - 1)
    over_identity = len(identity) > slots
    ranked = sorted(candidates, key=lambda item: (-int(item["score"]), int(item["index"])))
    files = [parent_rel]
    kept: list[dict] = [{"role": "canvas", "name": "parent", "file": parent_rel, "score": 100}]
    dropped: list[dict] = []
    seen_drop: set[tuple[str, str]] = set()
    for item in ranked:
        rel = item.get("file") or ""
        if over_identity and item.get("role") == "identity":
            rel = item.get("face") or item.get("master") or rel
        if not rel or rel in files:
            continue
        if len(files) >= int(max_refs):
            key = (str(item["role"]), str(item["name"]))
            if key not in seen_drop:
                seen_drop.add(key)
                dropped.append({"role": item["role"], "name": item["name"], "file": rel, "reason": "over_budget"})
            continue
        files.append(rel)
        kept.append(item)
    risk = ""
    if dropped:
        names = "、".join(f"{item['role']}:{item['name']}" for item in dropped)
        risk = f"参考预算 {max_refs} 张，已丢 {names}；拆镜或合成补参考，勿静默出图"
    return {
        "files": files[: int(max_refs)],
        "kept": kept,
        "dropped": dropped,
        "risk": risk,
        "max_refs": int(max_refs),
    }


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
    """Image 1 = this shot parent. Remaining slots ranked by importance. See last_still_pack_report()."""
    global _LAST_PACK_REPORT
    report = pack_codex_still_refs_report(
        prod,
        parent=parent,
        state=state,
        assets=assets,
        table=table,
        hard=hard,
        episode=episode,
        max_refs=max_refs,
        strict_existing=strict_existing,
    )
    _LAST_PACK_REPORT = report
    return list(report["files"])


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
    from director.setup_anchors import resolve_first_parent

    hint = _rel(still_parent)
    if hint:
        return hint, True
    parent, allow_master = resolve_first_parent(prod, shot_id, episode, location_id)
    if parent:
        return parent, allow_master
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
