"""Drop-folder stills. Task slips first; images become candidates, never auto-lock."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from .frames import upload_candidate
from .gates import parent_still
from .paths import director_dir
from .prompts import character_sheet_prompt, compile_still_prompt, still_refs
from .production import load_json

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SHOT_NAME = re.compile(r"^(SH\d{3})$", re.I)
ASSET_NAME = re.compile(r"^(character|scene)-([0-9A-Za-z._-]+)-([a-z]+)$", re.I)
SHORT_ASSET = re.compile(r"^([0-9A-Za-z._-]+)-(master|face|front|side|back|sheet|door|table)$", re.I)


def inbox_dir(prod: Path, create: bool = False) -> Path:
    path = director_dir(prod, create=create) / "inbox"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _task_path(prod: Path, task_id: str) -> Path:
    return inbox_dir(prod, create=True) / f"{task_id}.task.json"


def list_tasks(prod: Path) -> list[dict]:
    folder = director_dir(prod) / "inbox"
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.task.json"))]


def write_task(prod: Path, spec: dict) -> dict:
    task_id = str(spec.get("id") or "").strip()
    if not task_id:
        raise ValueError("任务单缺 id")
    task = {
        "id": task_id,
        "kind": spec.get("kind") or "shot",
        "target": spec.get("target") or task_id,
        "dest": spec.get("dest") or "",
        "parent": spec.get("parent") or "",
        "refs": list(spec.get("refs") or []),
        "filename": spec.get("filename") or f"{task_id}.jpg",
        "prompt": spec.get("prompt") or "",
        "negatives": spec.get("negatives") or "",
        "status": "waiting",
        "updated_at": int(time.time()),
    }
    payload = {k: task[k] for k in ("id", "parent", "refs", "prompt", "dest")}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task["fingerprint"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    path = _task_path(prod, task_id)
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return task


def task_for_shot(prod: Path, shot_id: str) -> dict:
    shots = list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])
    shot = next((item for item in shots if item.get("id") == shot_id), None)
    if not shot:
        raise FileNotFoundError(f"没有镜头 {shot_id}")
    parent = parent_still(prod, shot, shots)
    return write_task(
        prod,
        {
            "id": shot_id,
            "kind": "shot",
            "target": shot_id,
            "dest": shot.get("frame", f"04-frames/{shot_id}.jpg"),
            "parent": parent.get("path") or "",
            "refs": still_refs(prod, shot),
            "filename": f"{shot_id}.jpg",
            "prompt": compile_still_prompt(shot),
            "negatives": shot.get("negatives") or "",
        },
    )


def task_for_asset(prod: Path, kind: str, slug: str, slot: str, prompt: str = "") -> dict:
    if kind == "character":
        dest = f"02-assets/characters/{slug}/{slot}.jpg"
        parent = f"02-assets/characters/{slug}/master.jpg"
        refs = [parent]
    elif kind == "scene":
        dest = f"02-assets/scenes/{slug}/{slot}.jpg"
        parent = f"02-assets/scenes/{slug}/master.jpg"
        refs = [parent]
    else:
        raise ValueError("kind 只能是 character 或 scene")
    if slot == "master" and not (prod / parent).exists():
        parent = ""
    task_id = f"{kind}-{slug}-{slot}"
    if prompt:
        body = prompt
    elif kind == "character":
        body = character_sheet_prompt(slug, slot)
    else:
        body = (
            f"Photoreal Phnom Penh {kind} {slot} of {slug}, match locked master geography and light, "
            "widescreen 16:9, no subtitle, no watermark, no extra people."
        )
    return write_task(
        prod,
        {
            "id": task_id,
            "kind": kind,
            "target": task_id,
            "dest": dest,
            "parent": parent,
            "refs": [item for item in refs if item],
            "filename": f"{task_id}.jpg",
            "prompt": body,
        },
    )


def _match_task(prod: Path, stem: str) -> Optional[dict]:
    tasks = {item["id"]: item for item in list_tasks(prod)}
    if stem in tasks:
        return tasks[stem]
    shot = SHOT_NAME.match(stem)
    if shot:
        sid = shot.group(1).upper()
        return tasks.get(sid) or task_for_shot(prod, sid)
    asset = ASSET_NAME.match(stem)
    if asset:
        kind, slug, slot = asset.group(1).lower(), asset.group(2), asset.group(3).lower()
        tid = f"{kind}-{slug}-{slot}"
        return tasks.get(tid) or task_for_asset(prod, kind, slug, slot)
    short = SHORT_ASSET.match(stem)
    if short:
        slug, slot = short.group(1), short.group(2).lower()
        if (prod / "02-assets" / "characters" / slug).exists():
            tid = f"character-{slug}-{slot}"
            return tasks.get(tid) or task_for_asset(prod, "character", slug, slot)
        if (prod / "02-assets" / "scenes" / slug).exists():
            tid = f"scene-{slug}-{slot}"
            return tasks.get(tid) or task_for_asset(prod, "scene", slug, slot)
    return None


def scan_inbox(prod: Path) -> dict:
    folder = director_dir(prod) / "inbox"
    if not folder.exists():
        return {"ingested": [], "unmatched": [], "tasks": []}
    ingested = []
    unmatched = []
    for path in sorted(folder.iterdir()):
        if path.parent.name == "processed":
            continue
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        task = _match_task(prod, path.stem)
        if not task:
            unmatched.append(path.name)
            continue
        created = upload_candidate(prod, task["target"], path.name, path.read_bytes(), task.get("parent") or None)
        actual_meta = director_dir(prod) / "candidates" / f"{created['id']}.json"
        if actual_meta.exists():
            payload = json.loads(actual_meta.read_text(encoding="utf-8"))
            payload.update(
                {
                    "mode": "inbox",
                    "task": task["id"],
                    "dest": task.get("dest"),
                    "refs": task.get("refs") or [],
                    "prompt": task.get("prompt") or "",
                }
            )
            actual_meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        processed = inbox_dir(prod, create=True) / "processed"
        processed.mkdir(exist_ok=True)
        shutil.move(str(path), str(processed / path.name))
        task["status"] = "ingested"
        task["candidate"] = created["id"]
        task["updated_at"] = int(time.time())
        _task_path(prod, task["id"]).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ingested.append({"file": path.name, "candidate": created["id"], "task": task["id"], "dest": task.get("dest")})
    return {"ingested": ingested, "unmatched": unmatched, "tasks": list_tasks(prod)}
