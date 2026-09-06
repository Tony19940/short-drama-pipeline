"""Layered knowledge snippets. Never dump the whole library into one prompt."""

from __future__ import annotations

from pathlib import Path

from .paths import ROOT

KNOWLEDGE = ROOT / "knowledge"
LAYERS = ("rules", "writer", "director", "art", "camera", "sound", "cases")
AGENT_LAYERS = {
    "writer": ("rules", "writer"),
    "director": ("rules", "director"),
    "design": ("rules", "director"),
    "spec": ("rules", "director"),
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


def _read_layer(name: str, max_chars: int = 3500) -> str:
    folder = KNOWLEDGE / name
    if not folder.exists():
        return ""
    chunks = []
    size = 0
    for path in sorted(folder.glob("*.md")):
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


def load_for(agent: str, max_chars: int = 3500) -> dict[str, str]:
    layers = AGENT_LAYERS.get(agent, ("rules",))
    per = max(800, max_chars // max(len(layers), 1))
    return {name: _read_layer(name, per) for name in layers}


PACK = KNOWLEDGE / "pipeline-pack" / "prompts"
PACK_PROMPTS = {
    "novel": "01_小说.md",
    "writer": "02_编剧.md",
    "art": "03_视觉资产.md",
    "director": "04_分镜设计.md",
    "design": "04_分镜设计.md",
    "spec": "05_分镜说明书_5.1.md",
    "package": "06_生成包_5.2.md",
    "frames": "07_关键帧_6.1.md",
    "camera": "08_视频生成_6.2.md",
    "render": "08_视频生成_6.2.md",
    "sound": "09_声音.md",
    "edit": "10_剪辑.md",
    "producer": "00_制片统筹.md",
}


def prompt_block(agent: str) -> str:
    parts = []
    for name, body in load_for(agent).items():
        if body:
            parts.append("# knowledge/" + name + chr(10) + body)
    pack_name = PACK_PROMPTS.get(agent)
    if pack_name:
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

