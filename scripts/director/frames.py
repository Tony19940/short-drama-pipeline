"""Parent-frame stills. Master is generated once; everything else is an edit."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from .gates import inspect_files, parent_still
from .paths import director_dir, media_url, safe_under
from .production import load_json
from .store import load_approvals, save_approvals

def _imagine():
    import sys
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from image_backends.grok_imagine import GrokImagine, ImagineError

    return GrokImagine, ImagineError


def _shots(prod: Path) -> list[dict]:
    return list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])


def candidates_dir(prod: Path) -> Path:
    path = director_dir(prod, create=True) / "candidates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_candidates(prod: Path, target: Optional[str] = None) -> list[dict]:
    items = []
    folder = director_dir(prod) / "candidates"
    if not folder.exists():
        return items
    for path in sorted(folder.glob("*"), reverse=True):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        meta_path = path.with_suffix(path.suffix + ".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if target and meta.get("target") != target and path.stem.split("__")[0] != target:
            continue
        items.append(
            {
                "id": path.name,
                "url": media_url(prod, f".director/candidates/{path.name}"),
                "target": meta.get("target"),
                "parent": meta.get("parent"),
                "mode": meta.get("mode"),
                "prompt": meta.get("prompt"),
                "created_at": meta.get("created_at"),
            }
        )
    return items


def _write_candidate(prod: Path, target: str, image_bytes: bytes, meta: dict) -> dict:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{target}__{stamp}-{uuid.uuid4().hex[:6]}.jpg"
    dest = candidates_dir(prod) / name
    dest.write_bytes(image_bytes)
    payload = {
        **meta,
        "target": target,
        "created_at": int(time.time()),
        "file": f".director/candidates/{name}",
    }
    dest.with_suffix(dest.suffix + ".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "id": name,
        "url": media_url(prod, f".director/candidates/{name}"),
        "meta": payload,
    }


def resolve_asset_parent(prod: Path, kind: str, slug: str, slot: str) -> dict:
    if kind == "character":
        folder = prod / "02-assets" / "characters" / slug
        master = folder / "master.jpg"
        if slot == "master":
            return {
                "kind": "generate" if not master.exists() else "edit",
                "path": str(master.relative_to(prod)) if master.exists() else "",
                "exists": master.exists(),
                "dest": str(master.relative_to(prod)),
                "reason": "角色主图只许全新生成一次，之后全部改这张",
            }
        if slot in {"face", "front", "side", "back", "sheet"}:
            if not master.exists():
                raise PermissionError(f"先有角色 master.jpg，才能改出 {slot}.jpg")
            return {
                "kind": "edit",
                "path": str(master.relative_to(prod)),
                "exists": True,
                "dest": str((folder / f"{slot}.jpg").relative_to(prod)),
                "reason": f"{slot} 从 master 改，不准另开一张新脸",
            }
    if kind == "scene":
        folder = prod / "02-assets" / "scenes" / slug
        master = folder / "master.jpg"
        if slot == "master":
            return {
                "kind": "generate" if not master.exists() else "edit",
                "path": str(master.relative_to(prod)) if master.exists() else "",
                "exists": master.exists(),
                "dest": str(master.relative_to(prod)),
                "reason": "场景空镜只许全新生成一次",
            }
        if slot == "blocking":
            raise PermissionError("舞台图用 render_blocking.py 打点，不走 Imagine")
        if slot in {"door", "table", "sheet"}:
            if not master.exists():
                raise PermissionError("先有场景空镜 master.jpg")
            return {
                "kind": "edit",
                "path": str(master.relative_to(prod)),
                "exists": True,
                "dest": str((folder / f"{slot}.jpg").relative_to(prod)),
                "reason": f"场景 {slot} 从空镜 master 改，不准另开房间",
            }
    raise ValueError("未知资产槽位")


def resolve_shot_parent(prod: Path, shot_id: str) -> dict:
    shots = _shots(prod)
    shot = next((item for item in shots if item.get("id") == shot_id), None)
    if not shot:
        raise FileNotFoundError(f"没有镜头 {shot_id}")
    parent = parent_still(prod, shot, shots)
    dest = shot.get("frame", f"04-frames/{shot_id}.jpg")
    if not parent.get("exists"):
        raise PermissionError(parent.get("reason") or "缺父图")
    return {
        "kind": "edit",
        "path": parent["path"],
        "exists": True,
        "dest": dest,
        "reason": parent["reason"],
        "from": parent.get("from"),
        "shot": shot,
    }


def generate_still(
    prod: Path,
    *,
    target: str,
    prompt: str,
    mode: str,
    parent_rel: Optional[str] = None,
    refs: Optional[list[str]] = None,
    aspect: str = "16:9",
) -> dict:
    GrokImagine, ImagineError = _imagine()
    if mode == "generate":
        if parent_rel:
            raise PermissionError("全新生成不能带父图")
        try:
            imagine = GrokImagine()
            image_bytes = imagine.generate(prompt, aspect=aspect)
        except ImagineError as exc:
            raise PermissionError(exc.message) from exc
    elif mode == "edit":
        if not parent_rel:
            raise PermissionError("改图必须挂父图")
        parent = safe_under(prod, parent_rel)
        if not parent.exists():
            raise PermissionError(f"父图不存在：{parent_rel}")
        try:
            imagine = GrokImagine()
            ref_paths = [safe_under(prod, rel) for rel in (refs or [])]
            image_bytes = imagine.edit(parent, prompt, refs=ref_paths, aspect=aspect)
        except ImagineError as exc:
            raise PermissionError(exc.message) from exc
    else:
        raise ValueError("mode 只能是 generate 或 edit")
    return _write_candidate(
        prod,
        target,
        image_bytes,
        {
            "mode": mode,
            "parent": parent_rel,
            "prompt": prompt,
            "refs": refs or [],
            "aspect": aspect,
        },
    )


def request_asset_still(prod: Path, kind: str, slug: str, slot: str, prompt: str) -> dict:
    parent = resolve_asset_parent(prod, kind, slug, slot)
    target = f"{kind}-{slug}-{slot}"
    return generate_still(
        prod,
        target=target,
        prompt=prompt,
        mode=parent["kind"],
        parent_rel=parent["path"] or None,
    )


def request_shot_still(prod: Path, shot_id: str, prompt: Optional[str] = None) -> dict:
    from .gates import require_fresh_gate
    from .prompts import compile_still_prompt, missing_sheets, still_refs

    require_fresh_gate(prod, "C")
    from .pipeline import assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod)
    parent = resolve_shot_parent(prod, shot_id)
    shot = parent["shot"]
    missing = missing_sheets(prod, shot)
    if missing:
        raise PermissionError("新首帧必须挂联络板，缺 sheet.jpg：" + ", ".join(missing))
    text = prompt or compile_still_prompt(shot)
    if not text.strip():
        raise PermissionError("这镜还没有提示词")
    refs = still_refs(prod, shot)
    return generate_still(
        prod,
        target=shot_id,
        prompt=text,
        mode="edit",
        parent_rel=parent["path"],
        refs=refs,
    )


def upload_candidate(prod: Path, target: str, filename: str, data: bytes, parent_rel: Optional[str] = None) -> dict:
    if not data:
        raise ValueError("空文件")
    return _write_candidate(
        prod,
        target,
        data,
        {
            "mode": "upload",
            "parent": parent_rel,
            "filename": filename,
        },
    )


def previous_frame_locked(prod: Path, dest_rel: str) -> None:
    dest = str(dest_rel or "")
    if not dest.startswith("04-frames/") or not dest.endswith(".jpg"):
        return
    shot_id = Path(dest).stem
    shots = _shots(prod)
    shot = next((item for item in shots if item.get("id") == shot_id), None)
    if not shot:
        return
    parent = parent_still(prod, shot, shots)
    if not parent.get("exists"):
        raise PermissionError(parent.get("reason") or f"{shot_id} 缺父图，不能锁首帧")
    if parent.get("kind") == "previous_frame":
        prev_id = parent.get("from") or shot.get("from") or shot.get("derived_from")
        prev_path = prod / str(parent.get("path") or "")
        if not prev_path.exists():
            raise PermissionError(f"{shot_id} 的上一镜 {prev_id} 还没锁首帧")
    idx = next((i for i, item in enumerate(shots) if item.get("id") == shot_id), None)
    if idx is None or idx == 0:
        return
    prev = shots[idx - 1]
    prev_frame = prod / prev.get("frame", f"04-frames/{prev['id']}.jpg")
    if not prev_frame.exists():
        raise PermissionError(f"{shot_id} 的上一镜 {prev.get('id')} 还没锁首帧")


def lock_candidate(prod: Path, candidate_id: str, dest_rel: str) -> dict:
    from .prompts import require_sheet_for_new_frame

    require_sheet_for_new_frame(prod, dest_rel)
    previous_frame_locked(prod, dest_rel)
    src = candidates_dir(prod) / candidate_id
    if not src.exists():
        raise FileNotFoundError(f"没有候选 {candidate_id}")
    dest = safe_under(prod, dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        backup = director_dir(prod, create=True) / "backups" / f"{dest.name}.{int(time.time())}"
        shutil.copyfile(dest, backup)
    shutil.copyfile(src, dest)
    approvals = load_approvals(prod)
    approvals.setdefault("frames", {})
    approvals["frames"][dest_rel] = {
        "candidate": candidate_id,
        "at": int(time.time()),
    }
    save_approvals(prod, approvals)
    return {"ok": True, "dest": dest_rel, "url": media_url(prod, dest_rel)}


def frame_board(prod: Path) -> dict:
    from .prompts import compile_still_prompt, missing_sheets

    shots = _shots(prod)
    items = []
    for shot in shots:
        parent = parent_still(prod, shot, shots)
        dest = shot.get("frame", f"04-frames/{shot['id']}.jpg")
        sequence_ok = True
        sequence_reason = ""
        if parent.get("kind") == "previous_frame" and not parent.get("exists"):
            sequence_ok = False
            sequence_reason = parent.get("reason") or "上一镜首帧还没锁"
        idx = next((i for i, item in enumerate(shots) if item.get("id") == shot.get("id")), None)
        if sequence_ok and idx:
            prev = shots[idx - 1]
            prev_frame = prod / prev.get("frame", f"04-frames/{prev['id']}.jpg")
            if not prev_frame.exists():
                sequence_ok = False
                sequence_reason = f"上一镜 {prev.get('id')} 还没锁首帧"
        items.append(
            {
                "id": shot["id"],
                "setup": shot.get("setup"),
                "move": shot.get("move"),
                "cut": shot.get("cut"),
                "from": shot.get("from"),
                "new_info": shot.get("new_info"),
                "prompt": shot.get("prompt"),
                "video_prompt": shot.get("video_prompt"),
                "camera": shot.get("camera"),
                "action": shot.get("action"),
                "start": shot.get("start"),
                "look": shot.get("look"),
                "characters": shot.get("characters") or [],
                "missing_sheets": missing_sheets(prod, shot),
                "still_prompt": compile_still_prompt(shot) if shot.get("start") else shot.get("prompt"),
                "one_change": (
                    f"从父图改，第 0 秒只改到：{shot.get('start')}"
                    if shot.get("start") else "先写 start"
                ),
                "sequence_ok": sequence_ok,
                "sequence_reason": sequence_reason,
                "parent": parent,
                "dest": dest,
                "exists": (prod / dest).exists(),
                "url": media_url(prod, dest),
                "candidates": list_candidates(prod, shot["id"]),
            }
        )
    return {"shots": items, "files": inspect_files(prod)}
