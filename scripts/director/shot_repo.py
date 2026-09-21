"""Unified shot selection. v2 shot_list is runtime truth; shots.json is legacy import only."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .context import ProductionContext
from .pipeline import episode_frame_dir, read_artifact, uses_pipeline
from .production import load_json


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_v2(row: dict, *, episode: Any = 1) -> dict:
    item = dict(row)
    sid = _text(item.get("shot_id") or item.get("id"))
    item["id"] = sid
    item["shot_id"] = sid
    prefix = episode_frame_dir(episode)
    item.setdefault("frame", f"{prefix}/{sid}.jpg")
    return item


def _normalize_legacy(row: dict) -> dict:
    item = dict(row)
    sid = _text(item.get("id") or item.get("shot_id"))
    item["id"] = sid
    item["shot_id"] = sid
    item.setdefault("frame", f"04-frames/{sid}.jpg")
    return item


def list_shots(prod: Path, episode: Any = 1) -> list[dict]:
    """Shots for this production/episode. Pipeline projects never silently read shots.json."""
    ctx = prod if isinstance(prod, ProductionContext) else ProductionContext.resolve(prod, episode)
    root = ctx.prod
    token = ctx.episode_token
    if uses_pipeline(root):
        table = read_artifact(root, ctx.artifact_name("shot_list.json"))
        rows = [row for row in (table.get("shots") or []) if isinstance(row, dict) and _text(row.get("shot_id") or row.get("id"))]
        return [_normalize_v2(row, episode=token) for row in rows]
    legacy = load_json(root, "03-storyboard/shots.json", {"shots": []})
    return [_normalize_legacy(row) for row in (legacy.get("shots") or []) if isinstance(row, dict) and _text(row.get("id") or row.get("shot_id"))]


def select_shots(prod: Path, shot_ids: Optional[list[str]] = None, episode: Any = 1) -> list[dict]:
    shots = list_shots(prod, episode)
    want = {_text(x) for x in (shot_ids or []) if _text(x)}
    selected = [shot for shot in shots if not want or shot["id"] in want]
    if not selected:
        raise ValueError("没有可出的镜头")
    missing = sorted(want - {shot["id"] for shot in selected}) if want else []
    if missing:
        raise ValueError("没有这些镜头：" + ", ".join(missing))
    return selected
