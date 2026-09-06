"""整场宫格预览。给人/导演 Agent 看调度，不作为 H3 输入。"""

from __future__ import annotations

from pathlib import Path

from .gates import inspect_files, parent_still
from .paths import media_url
from .production import load_json


def storyboard_grid(prod: Path, source: str = "official") -> dict:
    rel = "03-storyboard/shots.draft.json" if source == "draft" else "03-storyboard/shots.json"
    data = load_json(prod, rel, {"shots": []})
    shots = list(data.get("shots") or [])
    files = inspect_files(prod)
    cells = []
    warnings = []
    prev = None
    for shot in shots:
        frame_rel = str(shot.get("frame") or f"04-frames/{shot.get('id')}.jpg")
        frame = prod / frame_rel
        parent = parent_still(prod, shot, shots)
        blocking = prod / "02-assets" / "scenes" / str(shot.get("scene") or "") / "blocking.jpg"
        image = ""
        if frame.exists() and frame.stat().st_size > 0:
            image = frame_rel
        elif parent.get("exists"):
            image = str(parent.get("path") or "")
        elif blocking.exists():
            image = str(blocking.relative_to(prod))
        if (
            prev
            and shot.get("setup") == prev.get("setup")
            and shot.get("characters") == prev.get("characters")
            and shot.get("scene") == prev.get("scene")
        ):
            warnings.append(f"{shot.get('id')} 和 {prev.get('id')} 同场同人同景别连排")
        if (
            prev
            and shot.get("axis")
            and prev.get("axis")
            and shot.get("axis") != prev.get("axis")
            and shot.get("cut") == "continue"
        ):
            warnings.append(f"{shot.get('id')} 同场续镜可能跳轴：{prev.get('axis')} → {shot.get('axis')}")
        cells.append(
            {
                "id": shot.get("id"),
                "setup": shot.get("setup"),
                "move": shot.get("move"),
                "start": shot.get("start") or "",
                "new_info": shot.get("new_info") or "",
                "scene": shot.get("scene") or "",
                "image": image,
                "url": media_url(prod, image) if image else "",
                "missing": not bool(image),
            }
        )
        prev = shot
    return {
        "source": source,
        "note": "宫格只给人看整场。出片仍按单镜首帧 + video_prompt。",
        "count": len(cells),
        "cells": cells,
        "warnings": warnings,
        "ready_frames": sum(1 for item in files.get("frames") or [] if item.get("frame")),
    }
