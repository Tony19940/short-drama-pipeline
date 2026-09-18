"""Machine-readable 连戏硬项 for package compile.

Human copy lives in `01-bible/LOOK-LOCK.md`. This file is optional; productions
without `02-assets/continuity-hard.json` keep the old binding enum behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

HARD_REL = "02-assets/continuity-hard.json"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _text(value).lower().replace("_", "-")


def load_continuity_hard(prod: Path) -> dict:
    path = Path(prod) / HARD_REL
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _entries(hard: Optional[dict]) -> list[dict]:
    items = (hard or {}).get("characters") if isinstance(hard, dict) else None
    return [item for item in (items or []) if isinstance(item, dict) and _text(item.get("cast_id"))]


def band_for(entry: dict, episode: int) -> dict:
    try:
        ep = int(episode)
    except (TypeError, ValueError):
        ep = 1
    for band in entry.get("costume_bands") or []:
        if not isinstance(band, dict):
            continue
        episodes = band.get("episodes") or []
        if ep in {int(x) for x in episodes if str(x).isdigit() or isinstance(x, int)}:
            return band
    return {}


def resolve_costume_token(hard: Optional[dict], cast_id: str, episode: int, declared: str) -> str:
    """Episode-band costume_state_id wins when the hard table names one."""
    cid = _text(cast_id)
    for entry in _entries(hard):
        if _text(entry.get("cast_id")) != cid:
            continue
        band = band_for(entry, episode)
        token = _text(band.get("costume_state_id"))
        if token:
            return token
    return _text(declared)


def hard_items_for_state(hard: Optional[dict], episode: int, state: Optional[dict]) -> list[str]:
    """One locked sentence per in-frame character that the table names."""
    chars = (state or {}).get("characters") if isinstance(state, dict) else None
    if not isinstance(chars, dict):
        return []
    out: list[str] = []
    for entry in _entries(hard):
        cid = _text(entry.get("cast_id"))
        item = chars.get(cid)
        if not isinstance(item, dict) or item.get("in_frame") is False:
            continue
        bits = [_text(x) for x in (entry.get("items") or []) if _text(x)]
        band = band_for(entry, episode)
        if _text(band.get("costume_state_id")):
            bits.append(f"costume_state={_text(band.get('costume_state_id'))}")
        if not bits:
            continue
        name = _text(entry.get("name")) or cid
        out.append(f"{name}：{'；'.join(bits)}")
    return out


def package_binding(physical: str, hard_items: list[str]) -> str:
    """Keep restraint enums (wrists_behind…). If none, inject the hard-item sentence."""
    restraint = _text(physical)
    if restraint and restraint != "none":
        return restraint
    if hard_items:
        return "；".join(hard_items)
    return restraint


def costume_aliases(item: dict) -> set[str]:
    declared = _norm(item.get("costume_state_id") or item.get("costume_state") or item.get("state"))
    aliases = {_norm(x) for x in (item.get("costume_aliases") or []) if _text(x)}
    if declared:
        aliases.add(declared)
    return aliases
