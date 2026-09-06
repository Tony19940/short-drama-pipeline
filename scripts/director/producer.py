"""Gate P producer: gap list and task sheet. Never generates images."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .production import read_text

PRODUCER_DIR = "01-bible/producer"
CHAR_SLOTS = ("master", "face", "sheet")
SCENE_SLOTS = ("master",)


def _slug_token(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9\-]+", "-", text).strip("-").lower()
    return token


CAST_ALIASES = {
    "yeay": "ros",
    "ros": "ros",
    "sophea": "sophea",
    "sara": "sara",
    "piseth": "piseth",
    "neary": "neary",
    "davi": "davi",
    "malis": "malis",
    "nita": "nita",
    "pov": "pov",
    "som": "som",
    "chando": "chando",
    "chhun": "chhun",
    "sokha": "sokha",
}


def _cast_slugs(prod: Path) -> list[str]:
    slugs: list[str] = []
    cast = read_text(prod, "01-bible/CAST.md")
    for match in re.finditer(r"\*\*([A-Za-z][A-Za-z0-9 \-]+)\*\*", cast):
        first = match.group(1).split("/")[0].split()[0].lower()
        slug = CAST_ALIASES.get(first, _slug_token(first))
        if slug and slug not in slugs:
            slugs.append(slug)
    char_root = prod / "02-assets" / "characters"
    if char_root.exists():
        for child in sorted(char_root.iterdir()):
            if child.is_dir() and child.name not in slugs:
                slugs.append(child.name)
    return slugs


def _scene_ids(prod: Path) -> list[str]:
    ids: list[str] = []
    sets_path = prod / "03-storyboard" / "sets.json"
    if sets_path.exists():
        data = json.loads(sets_path.read_text(encoding="utf-8"))
        for item in data.get("sets") or []:
            if item.get("id") and item["id"] not in ids:
                ids.append(item["id"])
    scene_root = prod / "02-assets" / "scenes"
    if scene_root.exists():
        for child in sorted(scene_root.iterdir()):
            if child.is_dir() and child.name not in ids:
                ids.append(child.name)
    return ids


def _prop_ids(prod: Path) -> list[str]:
    root = prod / "02-assets" / "props"
    if not root.exists():
        return []
    ids = []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            ids.append(child.name)
        elif child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            ids.append(child.stem)
    return ids


def _missing_slots(folder: Path, slots: tuple[str, ...]) -> list[str]:
    missing = []
    for slot in slots:
        path = folder / f"{slot}.jpg"
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(slot)
    return missing


def build_manifest(prod: Path) -> dict:
    from .gates import inspect_files

    files = inspect_files(prod)
    tasks = []
    for slug in _cast_slugs(prod):
        folder = prod / "02-assets" / "characters" / slug
        missing = _missing_slots(folder, CHAR_SLOTS) if folder.exists() else list(CHAR_SLOTS)
        if not folder.exists():
            missing = ["folder"] + list(CHAR_SLOTS)
        if missing:
            tasks.append(
                {
                    "kind": "character",
                    "slug": slug,
                    "missing": missing,
                    "dest": f"02-assets/characters/{slug}/",
                    "note": "制片只开任务，生图走美术 / Codex",
                }
            )
    for sid in _scene_ids(prod):
        folder = prod / "02-assets" / "scenes" / sid
        missing = _missing_slots(folder, SCENE_SLOTS) if folder.exists() else list(SCENE_SLOTS)
        if missing:
            tasks.append(
                {
                    "kind": "scene",
                    "slug": sid,
                    "missing": missing,
                    "dest": f"02-assets/scenes/{sid}/",
                    "note": "空镜 master，不在这里生图",
                }
            )
    for pid in _prop_ids(prod):
        folder = prod / "02-assets" / "props" / pid
        master = folder / "master.jpg" if folder.is_dir() else prod / "02-assets" / "props" / f"{pid}.jpg"
        if not master.exists():
            tasks.append(
                {
                    "kind": "prop",
                    "slug": pid,
                    "missing": ["master"],
                    "dest": f"02-assets/props/{pid}/master.jpg",
                    "note": "道具主图",
                }
            )
    shot_count = int(files.get("shot_count") or 0)
    seconds = 0
    shots_path = prod / "03-storyboard" / "shots.json"
    if shots_path.exists():
        shots = json.loads(shots_path.read_text(encoding="utf-8")).get("shots") or []
        seconds = sum(int(s.get("seconds") or 0) for s in shots)
        shot_count = shot_count or len(shots)
    return {
        "shot_count": shot_count,
        "seconds": seconds,
        "characters": _cast_slugs(prod),
        "scenes": _scene_ids(prod),
        "tasks": tasks,
        "task_count": len(tasks),
        "filmable": not any(task.get("kind") == "character" and "folder" in task.get("missing", []) for task in tasks),
        "budget_note": "人物主图/脸/联络板先齐；三人以上复杂走位才考虑 Blender 白模。",
    }


def _plan_markdown(manifest: dict) -> str:
    lines = [
        "# 制片任务单",
        "",
        f"- 镜头量：{manifest.get('shot_count') or '未出分镜'} 镜 / {manifest.get('seconds') or '—'} 秒",
        f"- 缺口：{manifest.get('task_count')} 项",
        f"- 可拍性：{'可进入美术' if manifest.get('filmable') else '缺角色文件夹，先建档'}",
        f"- 预算粗估：{manifest.get('budget_note')}",
        "",
        "制片不生图。下面交给美术。",
        "",
        "| 种类 | slug | 缺什么 | 路径 |",
        "|---|---|---|---|",
    ]
    for task in manifest.get("tasks") or []:
        lines.append(
            f"| {task['kind']} | {task['slug']} | {', '.join(task['missing'])} | `{task['dest']}` |"
        )
    if not manifest.get("tasks"):
        lines.append("| — | — | 无缺口 | — |")
    lines.append("")
    return "\n".join(lines)


def write_producer_draft(prod: Path) -> dict:
    dest = prod / PRODUCER_DIR
    dest.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(prod)
    (dest / "manifest.draft.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "plan.draft.md").write_text(_plan_markdown(manifest), encoding="utf-8")
    return snapshot_producer(prod)


def promote_producer_drafts(prod: Path) -> None:
    dest = prod / PRODUCER_DIR
    for src_name, official in (("plan.draft.md", "plan.md"), ("manifest.draft.json", "manifest.json")):
        src = dest / src_name
        if src.exists() and src.stat().st_size > 0:
            (dest / official).write_bytes(src.read_bytes())


def snapshot_producer(prod: Path) -> dict:
    dest = prod / PRODUCER_DIR
    live = build_manifest(prod)
    official = {}
    drafts = {}
    if dest.exists():
        for path in dest.iterdir():
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if ".draft." in path.name:
                drafts[path.name] = text
            else:
                official[path.name] = text
    manifest = live
    if "manifest.json" in official:
        try:
            manifest = json.loads(official["manifest.json"])
        except json.JSONDecodeError:
            manifest = live
    elif "manifest.draft.json" in drafts:
        try:
            manifest = json.loads(drafts["manifest.draft.json"])
        except json.JSONDecodeError:
            manifest = live
    return {
        "dir": PRODUCER_DIR,
        "manifest": manifest,
        "live": live,
        "official": official,
        "drafts": drafts,
        "ready": bool(official.get("plan.md") and official.get("manifest.json")),
    }
