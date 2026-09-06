"""Read and write production files in place."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .gates import inspect_files, parent_still
from .paths import ROOT, SLUG_RE, list_productions, media_url, productions_root, safe_under
from .store import load_jobs

EPISODE_SPLIT = re.compile(r"\n(?=第\s*\d+\s*集|EP\s*\d+|Episode\s*\d+)", re.I)
TEXT_FILES = {
    "bible": [
        "01-bible/STATUS.md",
        "01-bible/confirm.md",
        "01-bible/blueprint.md",
        "01-bible/STORY.md",
        "01-bible/series-bible.md",
        "01-bible/ep01.md",
        "01-bible/ep02.md",
        "01-bible/ep03.md",
        "01-bible/ep04.md",
        "01-bible/ep05.md",
    ],
    "coverage": [
        "03-storyboard/beats.md",
        "03-storyboard/coverage.md",
        "03-storyboard/shot-list.md",
    ],
}



def create_production(slug: str, title: str = "") -> dict:
    slug = (slug or "").strip()
    if not SLUG_RE.match(slug):
        raise ValueError("项目名只能用字母数字、点、下划线和短横线")
    dest = productions_root() / slug
    if dest.exists():
        raise FileExistsError(f"已经有这个项目：{slug}")
    template = ROOT / "productions" / "_template"
    if not template.exists():
        raise FileNotFoundError("缺少 productions/_template")
    shutil.copytree(template, dest)
    readme = dest / "README.md"
    heading = title.strip() or slug
    readme.write_text(f"# {heading}\n\n从参考片反推或从剧本开拍。当前关卡写在 `01-bible/STATUS.md`。\n", encoding="utf-8")
    reverse = dest / "00-reverse"
    (reverse / "source").mkdir(parents=True, exist_ok=True)
    (reverse / "frames").mkdir(parents=True, exist_ok=True)
    (reverse / "audio").mkdir(parents=True, exist_ok=True)
    (dest / "01-bible" / "STATUS.md").write_text(
        "# 状态\n\n- **关卡**：Gate 0 故事 / Gate A 编剧\n- **圣经**：draft\n- **资产**：—\n- **分镜**：draft\n- **首帧**：—\n- **成片**：—\n- **旁白**：—\n\n下一件：填创意简报，或把 Inkos 导出的小说/剧本上传到 `01-bible/source/`。反推参考片仍走隐藏的 `00-reverse/`。\n",
        encoding="utf-8",
    )
    return {"id": slug, "name": heading, "path": str(dest)}


def overview() -> list[dict]:
    items = []
    for prod in list_productions():
        files = inspect_files(prod)
        items.append(
            {
                "id": prod.name,
                "name": _title(prod),
                "path": str(prod),
                "shot_count": files["shot_count"],
                "video_count": files["video_count"],
                "review": files["review"],
            }
        )
    return items


def _title(prod: Path) -> str:
    readme = prod / "README.md"
    if readme.exists():
        for line in readme.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                return line.lstrip("# ").strip()
    return prod.name


def load_json(prod: Path, rel: str, default):
    path = safe_under(prod, rel)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(prod: Path, rel: str, data) -> None:
    path = safe_under(prod, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(prod: Path, rel: str) -> str:
    path = safe_under(prod, rel)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(prod: Path, rel: str, content: str) -> None:
    path = safe_under(prod, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def bible(prod: Path) -> dict:
    files = {rel: read_text(prod, rel) for rel in TEXT_FILES["bible"]}
    return {"files": files, "status": files.get("01-bible/STATUS.md", "")}


def save_bible_file(prod: Path, rel: str, content: str) -> dict:
    if not rel.startswith("01-bible/"):
        raise ValueError("只能改 01-bible 下的文件")
    write_text(prod, rel, content)
    return bible(prod)


def split_script(text: str) -> list[tuple[str, str]]:
    chunks = [chunk.strip() for chunk in EPISODE_SPLIT.split(text) if chunk.strip()]
    if not chunks:
        return []
    episodes = []
    for index, chunk in enumerate(chunks, start=1):
        first = chunk.splitlines()[0][:40]
        episodes.append((f"ep{index:02d}.md", f"# {first}\n\n{chunk}\n"))
    return episodes


def import_script(prod: Path, text: str) -> dict:
    episodes = split_script(text)
    written = []
    if not episodes:
        write_text(prod, "01-bible/ep01.md", text)
        written.append("01-bible/ep01.md")
    else:
        for name, content in episodes[:5]:
            rel = f"01-bible/{name}"
            write_text(prod, rel, content)
            written.append(rel)
    draft = prod / "01-bible" / "script.draft.txt"
    draft.write_text(text, encoding="utf-8")
    return {"written": written, "count": len(written)}


def assets(prod: Path) -> dict:
    files = inspect_files(prod)
    characters = []
    for item in files["characters"]:
        slug = item["id"]
        folder = prod / "02-assets" / "characters" / slug
        views = {}
        for slot in ("master", "face", "front", "side", "back", "sheet"):
            path = folder / f"{slot}.jpg"
            views[slot] = path.exists()
            views[f"{slot}_url"] = media_url(prod, f"02-assets/characters/{slug}/{slot}.jpg")
        characters.append(
            {
                **item,
                **views,
                "card": read_text(prod, f"02-assets/characters/{slug}.md"),
            }
        )
    scenes = []
    for item in files["scenes"]:
        slug = item["id"]
        folder = prod / "02-assets" / "scenes" / slug
        views = {}
        for slot in ("master", "blocking", "door", "table", "sheet"):
            path = folder / f"{slot}.jpg"
            views[slot] = path.exists()
            views[f"{slot}_url"] = media_url(prod, f"02-assets/scenes/{slug}/{slot}.jpg")
        scenes.append(
            {
                **item,
                **views,
                "card": read_text(prod, f"02-assets/scenes/{slug}.md"),
            }
        )
    props = []
    prop_root = prod / "02-assets" / "props"
    if prop_root.exists():
        for child in sorted(prop_root.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                master = child / "master.jpg"
                extras = []
                for path in sorted(child.iterdir()):
                    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and path.name != "master.jpg":
                        extras.append(
                            {
                                "id": path.stem,
                                "url": media_url(prod, str(path.relative_to(prod))),
                            }
                        )
                props.append(
                    {
                        "id": child.name,
                        "master": master.exists(),
                        "master_url": media_url(prod, str(master.relative_to(prod))) if master.exists() else None,
                        "path": f"02-assets/props/{child.name}/master.jpg",
                        "files": extras,
                    }
                )
            elif child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                props.append(
                    {
                        "id": child.stem,
                        "master": True,
                        "master_url": media_url(prod, str(child.relative_to(prod))),
                        "path": str(child.relative_to(prod)),
                        "files": [],
                    }
                )
    return {
        "look": read_text(prod, "02-assets/LOOK.md"),
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "scale_url": media_url(prod, "02-assets/characters/scale.jpg"),
    }


def save_look(prod: Path, content: str) -> dict:
    write_text(prod, "02-assets/LOOK.md", content)
    return assets(prod)


def stage(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    sets = []
    for item in data.get("sets") or []:
        blocking = prod / item.get("blocking", f"02-assets/scenes/{item.get('id')}/blocking.jpg")
        master = prod / item.get("master", f"02-assets/scenes/{item.get('id')}/master.jpg")
        sets.append(
            {
                **item,
                "master_exists": master.exists(),
                "blocking_exists": blocking.exists(),
                "master_url": media_url(prod, item.get("master") or f"02-assets/scenes/{item.get('id')}/master.jpg"),
                "blocking_url": media_url(prod, item.get("blocking") or f"02-assets/scenes/{item.get('id')}/blocking.jpg"),
            }
        )
    return {"sets": sets, "raw": data}


def save_sets(prod: Path, data: dict) -> dict:
    if "sets" not in data:
        raise ValueError("sets.json 必须有 sets")
    save_json(prod, "03-storyboard/sets.json", data)
    return stage(prod)


def render_blocking(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    if not data.get("sets"):
        raise PermissionError("缺 sets.json")
    for item in data["sets"]:
        master = prod / item.get("master", "")
        if not master.exists():
            raise PermissionError(f"缺场景空镜 {master}")
    cmd = [sys.executable, str(ROOT / "scripts" / "render_blocking.py"), "--prod", str(prod)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "render_blocking 失败")
    return {"ok": True, "stdout": proc.stdout, "stage": stage(prod)}


def coverage(prod: Path) -> dict:
    return {
        "beats": read_text(prod, "03-storyboard/beats.md"),
        "coverage": read_text(prod, "03-storyboard/coverage.md"),
        "shot_list": read_text(prod, "03-storyboard/shot-list.md"),
        "shots": load_json(prod, "03-storyboard/shots.json", {"shots": []}),
    }


def save_coverage(prod: Path, field: str, content: str) -> dict:
    mapping = {
        "beats": "03-storyboard/beats.md",
        "coverage": "03-storyboard/coverage.md",
        "shot_list": "03-storyboard/shot-list.md",
    }
    if field not in mapping:
        raise ValueError("只能改 beats / coverage / shot_list")
    write_text(prod, mapping[field], content)
    return coverage(prod)


def save_shots(prod: Path, data: dict) -> dict:
    if "shots" not in data:
        raise ValueError("shots.json 必须有 shots")
    path = safe_under(prod, "03-storyboard/shots.json")
    original = path.read_text(encoding="utf-8") if path.exists() else None
    save_json(prod, "03-storyboard/shots.json", data)
    from .gates import run_check

    check = run_check(prod)
    if not check["ok"]:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，已回滚")
    return {"coverage": coverage(prod), "check": check, "shots": shot_board(prod)}


def save_shot_draft(prod: Path, data: dict) -> dict:
    if "shots" not in data:
        raise ValueError("shots.draft.json 必须有 shots")
    save_json(prod, "03-storyboard/shots.draft.json", data)
    return {"ok": True, "path": "03-storyboard/shots.draft.json", "count": len(data.get("shots") or [])}


def load_shot_draft(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/shots.draft.json", {"shots": []})
    board = _decorate_shots(prod, data)
    origin = str(data.get("origin") or "")
    if origin.startswith("scriptwriter"):
        kind = "scriptwriter"
        label = "专家草稿"
    elif origin.startswith("reverse"):
        kind = "reverse"
        label = "反推草稿"
    elif data.get("shots"):
        kind = "draft"
        label = "分镜草稿"
    else:
        kind = "empty"
        label = "还没有草稿"
    board["origin"] = origin
    board["draft_kind"] = kind
    board["draft_label"] = label
    return board


def accept_shot_draft(prod: Path) -> dict:
    draft = load_json(prod, "03-storyboard/shots.draft.json", {"shots": []})
    if not draft.get("shots"):
        raise FileNotFoundError("没有 shots.draft.json")
    runtime = {
        "parent", "frame_exists", "frame_url", "source_frame_url", "video_exists",
        "video_url", "last_exists", "last_url", "i2v", "refs", "missing_sheets",
        "compiled_prompt", "video_mode", "files", "jobs", "draft_kind", "draft_label",
        "compiled_h3", "end",
    }
    cleaned = {
        "episode": draft.get("episode"),
        "kind": draft.get("kind"),
        "aspect": draft.get("aspect"),
        "origin": draft.get("origin"),
        "shots": [],
    }
    for shot in draft.get("shots") or []:
        cleaned["shots"].append({k: v for k, v in shot.items() if k not in runtime})
    return save_shots(prod, cleaned)


def _decorate_shots(prod: Path, data: dict) -> dict:
    shots = data.get("shots") or []
    files = inspect_files(prod)
    board = []
    for shot in shots:
        parent = parent_still(prod, shot, shots)
        frame_rel = shot.get("frame", f"04-frames/{shot['id']}.jpg")
        video = prod / "05-shots" / f"{shot['id']}.mp4"
        last = prod / shot.get("last_frame", f"04-frames/{shot['id']}-last.jpg")
        from .gates import designed_end_frame, i2v_source
        from .prompts import compile_h3_fields, compile_video_prompt, missing_sheets, still_refs, video_mode

        refs = still_refs(prod, shot)
        source = i2v_source(prod, shot, shots)
        source_frame = shot.get("source_frame")
        board.append(
            {
                **shot,
                "parent": parent,
                "frame_exists": (prod / frame_rel).exists(),
                "frame_url": media_url(prod, frame_rel),
                "source_frame_url": media_url(prod, source_frame) if source_frame else None,
                "video_exists": video.exists(),
                "video_url": media_url(prod, f"05-shots/{shot['id']}.mp4"),
                "last_exists": last.exists(),
                "last_url": media_url(prod, str(last.relative_to(prod))),
                "i2v": source,
                "refs": refs,
                "missing_sheets": missing_sheets(prod, shot),
                "compiled_prompt": compile_video_prompt(shot, refs=refs),
                "compiled_h3": compile_h3_fields(shot, silent=True, refs=refs),
                "video_mode": video_mode(shot, source["kind"], refs),
                "end": designed_end_frame(prod, shot),
            }
        )
    return {
        "episode": data.get("episode"),
        "kind": data.get("kind"),
        "aspect": data.get("aspect"),
        "origin": data.get("origin"),
        "shots": board,
        "files": files,
        "jobs": load_jobs(prod),
    }


def shot_board(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/shots.json", {"shots": []})
    board = _decorate_shots(prod, data)
    board["draft_kind"] = "official"
    board["draft_label"] = "正式合同"
    return board


def accept_draft(prod: Path, draft_rel: str, dest_rel: str) -> dict:
    draft = safe_under(prod, draft_rel)
    dest = safe_under(prod, dest_rel)
    if not draft.exists():
        raise FileNotFoundError(f"没有草稿 {draft_rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft, dest)
    return {"ok": True, "dest": dest_rel}
