"""Layered knowledge snippets. Never dump the whole library into one prompt.

Director-side stations (analysis / design / critic / spec / frame_desc) get a much
larger budget than the rest: cutting craft lives in playbook + cases, and a 3.5k
cap used to truncate the playbook mid-sentence.
"""

from __future__ import annotations

import re
from pathlib import Path

from .paths import ROOT

KNOWLEDGE = ROOT / "knowledge"
LAYERS = ("rules", "writer", "director", "art", "camera", "sound", "cases")
AGENT_LAYERS = {
    "writer": ("rules", "writer"),
    "director": ("rules", "director", "cases"),
    "design": ("rules", "director", "cases"),
    "analysis": ("rules", "director", "cases"),
    "critic": ("rules", "director", "cases"),
    "spec": ("rules", "director"),
    "frame_desc": ("rules", "director", "art", "camera"),
    "package": ("rules", "camera"),
    "art": ("rules", "art"),
    "camera": ("rules", "camera"),
    "frames": ("rules", "camera"),
    "render": ("rules", "camera"),
    "edit": ("rules", "sound"),
    "sound": ("rules", "sound"),
    "qc": ("rules", "cases"),
    "producer": ("rules", "art"),
    "novel": ("rules", "writer"),
}
# Director-side stations read the whole cutting library; everyone else stays on the old diet.
DIRECTOR_AGENTS = {"director", "design", "analysis", "critic", "spec", "frame_desc"}
DEFAULT_BUDGET = 3500
DIRECTOR_BUDGET = 16000


def _read_layer(name: str, max_chars: int = 3500) -> str:
    folder = KNOWLEDGE / name
    if not folder.exists():
        return ""
    chunks = []
    size = 0
    for path in sorted(folder.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        block = f"## {path.stem}\n{text}\n"
        if size + len(block) > max_chars:
            remain = max_chars - size
            if remain > 80:
                chunks.append(block[:remain] + "\n")
            break
        chunks.append(block)
        size += len(block)
    return "".join(chunks).strip()


def budget_for(agent: str) -> int:
    return DIRECTOR_BUDGET if agent in DIRECTOR_AGENTS else DEFAULT_BUDGET


def load_for(agent: str, max_chars: int | None = None) -> dict[str, str]:
    layers = AGENT_LAYERS.get(agent, ("rules",))
    total = max_chars if max_chars is not None else budget_for(agent)
    per = max(800, total // max(len(layers), 1))
    return {name: _read_layer(name, per) for name in layers}


PACK = KNOWLEDGE / "pipeline-pack" / "prompts"
PACK_PROMPTS = {
    "novel": "01_小说.md",
    "writer": "02_编剧.md",
    "art": "03_视觉资产.md",
    "director": "04_分镜设计.md",
    "design": "04_分镜设计.md",
    "analysis": "04a_场戏分析.md",
    "critic": "04b_分镜评审.md",
    "spec": "05_分镜说明书_5.1.md",
    "package": "06_生成包_5.2.md",
    "frames": "07_关键帧_6.1.md",
    "frame_desc": "07a_画面描述.md",
    "camera": "08_视频生成_6.2.md",
    "render": "08_视频生成_6.2.md",
    "sound": "09_声音.md",
    "edit": "10_剪辑.md",
    "producer": "00_制片统筹.md",
}


def prompt_block(agent: str, include_pack: bool = True) -> str:
    parts = []
    for name, body in load_for(agent).items():
        if body:
            parts.append("# knowledge/" + name + chr(10) + body)
    pack_name = PACK_PROMPTS.get(agent)
    if include_pack and pack_name:
        path = PACK / pack_name
        if path.exists():
            packed = path.read_text(encoding="utf-8").strip()
            parts.append("# pipeline-pack/" + pack_name + chr(10) + packed[:1200])
    return (chr(10) * 2).join(parts)


def pack_prompt(agent: str, max_chars: int = 12000) -> str:
    pack_name = PACK_PROMPTS.get(agent)
    if not pack_name:
        return ""
    path = PACK / pack_name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()[:max_chars]


# --- case cards -------------------------------------------------------------

_TAG_LINE = re.compile(r"^(?:tags|标签|场型)\s*[:：]\s*(.+)$", re.M)


def case_cards() -> list[dict]:
    """Every card under knowledge/cases with its tag words. README is not a card."""
    folder = KNOWLEDGE / "cases"
    if not folder.exists():
        return []
    cards = []
    for path in sorted(folder.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        tags: list[str] = []
        match = _TAG_LINE.search(text)
        if match:
            tags = [t.strip() for t in re.split(r"[、,，;； /]+", match.group(1)) if t.strip()]
        title = text.splitlines()[0].lstrip("# ").strip()
        cards.append({"id": path.stem, "title": title, "tags": tags, "text": text})
    return cards


def cases_for(scene_text: str, limit: int = 2) -> list[dict]:
    """Pick the 1–2 case cards whose tags appear in this scene's text. Empty when nothing matches."""
    blob = str(scene_text or "")
    if not blob:
        return []
    scored = []
    for card in case_cards():
        hits = sum(1 for tag in card["tags"] if tag and tag in blob)
        if card["title"] and card["title"] in blob:
            hits += 1
        if hits:
            scored.append((hits, card))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [{"id": c["id"], "title": c["title"], "text": c["text"]} for _, c in scored[:limit]]
