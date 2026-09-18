"""8 Agent rail: fingerprints, stale detection, virtual locks for old productions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from .store import approvals_path, load_approvals, save_approvals

AGENTS = [
    {"id": "0", "label": "小说", "tab": "story"},
    {"id": "A", "label": "编剧", "tab": "writer"},
    {"id": "B", "label": "资产", "tab": "art"},
    {"id": "C", "label": "分镜", "tab": "design"},
    {"id": "C1", "label": "说明书", "tab": "spec"},
    {"id": "C2", "label": "生成包", "tab": "package"},
    {"id": "D", "label": "关键帧", "tab": "frames"},
    {"id": "E", "label": "视频", "tab": "render"},
    {"id": "E+", "label": "声音", "tab": "sound"},
    {"id": "F", "label": "剪辑", "tab": "edit"},
]
AGENT_ORDER = [item["id"] for item in AGENTS]
LOCKABLE = ["0", "A", "P", "B", "S", "C", "C1", "C2", "D", "E", "E+", "F"]

UPSTREAM: dict[str, list[str]] = {
    "0": [],
    "A": ["0"],
    "P": ["A"],
    "B": ["P", "A"],
    "S": ["B"],
    "C": ["B", "P", "A", "0", "S"],
    "C1": ["C"],
    "C2": ["C1", "C", "B"],
    "D": ["C2", "C1", "C"],
    "E": ["D", "C2", "C", "B", "A"],
    "E+": ["E", "D", "C1"],
    "F": ["E+", "E", "C2", "C"],
}

UNLOCK_DOWNSTREAM: dict[str, list[str]] = {
    "0": ["A", "P", "B", "S", "C", "C1", "C2", "D", "E", "E+", "F"],
    "A": ["P", "B", "S", "C", "C1", "C2", "D", "E", "E+", "F"],
    "P": ["B", "S", "C", "C1", "C2", "D", "E", "E+", "F"],
    "B": ["S", "C", "C1", "C2", "D", "E", "E+", "F"],
    "S": ["C", "C1", "C2", "D", "E", "E+", "F"],
    "C": ["C1", "C2", "D", "E", "E+", "F"],
    "C1": ["C2", "D", "E", "E+", "F"],
    "C2": ["D", "E", "E+", "F"],
    "D": ["E", "E+", "F"],
    "E": ["E+", "F"],
    "E+": ["F"],
    "F": [],
}

STATUS_LABELS = {
    "waiting": "等待上一步",
    "draft": "草稿待审核",
    "locked": "已锁定",
    "stale": "上游已修改",
}

_HASH_CACHE: dict[tuple, str] = {}


def _exists(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    if not _exists(path):
        return ""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    cached = _HASH_CACHE.get(key)
    if cached:
        return cached
    digest = hash_bytes(path.read_bytes())
    _HASH_CACHE[key] = digest
    return digest


def _is_draft(path: Path) -> bool:
    name = path.name
    return ".draft." in name or name.endswith(".draft") or name.startswith(".")


def _rel(prod: Path, path: Path) -> str:
    return path.relative_to(prod).as_posix()


def _add_if_file(prod: Path, rel: str, out: list[Path]) -> None:
    path = prod / rel
    if _exists(path) and not _is_draft(path):
        out.append(path)


def _glob_files(root: Path, pattern: str = "*") -> list[Path]:
    if not root.exists():
        return []
    items = []
    for path in sorted(root.glob(pattern)):
        if path.is_file() and not _is_draft(path) and path.name != ".DS_Store":
            items.append(path)
    return items


def agent_files(prod: Path, agent_id: str) -> list[Path]:
    files: list[Path] = []
    if agent_id == "0":
        _add_if_file(prod, ".pipeline/novel.json", files)
        source = prod / "01-bible" / "source"
        if source.exists():
            for path in sorted(source.rglob("*")):
                if path.is_file() and not _is_draft(path) and path.name != ".DS_Store":
                    files.append(path)
        return files
    if agent_id == "A":
        _add_if_file(prod, ".pipeline/writer.json", files)
        for rel in ("01-bible/confirm.md", "01-bible/blueprint.md", "01-bible/CAST.md"):
            _add_if_file(prod, rel, files)
        bible = prod / "01-bible"
        if bible.exists():
            for path in sorted(bible.glob("ep*.md")):
                if path.is_file() and not _is_draft(path):
                    files.append(path)
        return files
    if agent_id == "P":
        for rel in ("01-bible/producer/plan.md", "01-bible/producer/manifest.json"):
            _add_if_file(prod, rel, files)
        return files
    if agent_id == "B":
        _add_if_file(prod, ".pipeline/assets.json", files)
        _add_if_file(prod, "02-assets/LOOK.md", files)
        for folder in _glob_dirs(prod / "02-assets" / "characters"):
            for slot in ("master.jpg", "face.jpg"):
                _add_if_file(prod, str((folder / slot).relative_to(prod)), files)
        for folder in _glob_dirs(prod / "02-assets" / "scenes"):
            _add_if_file(prod, str((folder / "master.jpg").relative_to(prod)), files)
        for folder in _glob_dirs(prod / "02-assets" / "props"):
            _add_if_file(prod, str((folder / "master.jpg").relative_to(prod)), files)
        return files
    if agent_id == "S":
        _add_if_file(prod, "03-storyboard/sets.json", files)
        for folder in _glob_dirs(prod / "02-assets" / "scenes"):
            _add_if_file(prod, str((folder / "blocking.jpg").relative_to(prod)), files)
        return files
    if agent_id == "C":
        for rel in (
            "03-storyboard/sets.json",
            "03-storyboard/coverage.md",
            "03-storyboard/beats.md",
            "03-storyboard/shots.json",
            ".pipeline/shot_list.json",
        ):
            _add_if_file(prod, rel, files)
        for folder in _glob_dirs(prod / "02-assets" / "scenes"):
            _add_if_file(prod, str((folder / "blocking.jpg").relative_to(prod)), files)
        return files
    if agent_id == "C1":
        _add_if_file(prod, ".pipeline/shot_specs.json", files)
        return files
    if agent_id == "C2":
        _add_if_file(prod, ".pipeline/gen_packages.json", files)
        _add_if_file(prod, ".pipeline/frame_descriptions.json", files)
        return files
    if agent_id == "D":
        _add_if_file(prod, ".pipeline/keyframes.json", files)
        frames = prod / "04-frames"
        for path in _glob_files(frames, "*.jpg"):
            name = path.name.lower()
            if name.endswith("-last.jpg"):
                continue
            files.append(path)
        return files
    if agent_id == "E":
        _add_if_file(prod, ".pipeline/clips.json", files)
        for path in _glob_files(prod / "05-shots", "*.mp4"):
            if "kenburns" in path.name.lower() or "still-pass" in path.name.lower():
                continue
            files.append(path)
        return files
    if agent_id == "E+":
        _add_if_file(prod, ".pipeline/audio.json", files)
        export = prod / "06-export"
        for path in _glob_files(export, "preview*.mp4"):
            files.append(path)
        dub = prod / "07-dubbing"
        if dub.exists():
            for path in sorted(dub.iterdir()):
                if path.is_file() and not _is_draft(path) and path.suffix.lower() in {".json", ".md"}:
                    files.append(path)
        return files
    if agent_id == "F":
        _add_if_file(prod, ".pipeline/cut.json", files)
        _add_if_file(prod, "06-export/ep01.mp4", files)
        for rel in ("08-qc/report.json", "08-qc/report.md", "01-bible/qc/report.md"):
            _add_if_file(prod, rel, files)
        return files
    return files


def _glob_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [child for child in sorted(root.iterdir()) if child.is_dir() and not child.name.startswith(".")]


def file_hashes(prod: Path, agent_id: str) -> dict[str, str]:
    return {_rel(prod, path): hash_file(path) for path in agent_files(prod, agent_id)}


def agent_fingerprint(prod: Path, agent_id: str, files: Optional[dict[str, str]] = None) -> str:
    payload = files if files is not None else file_hashes(prod, agent_id)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hash_bytes(raw.encode("utf-8"))


def upstream_fingerprints(prod: Path, agent_id: str) -> dict[str, str]:
    return {uid: agent_fingerprint(prod, uid) for uid in UPSTREAM.get(agent_id, [])}


def lock_record(prod: Path, agent_id: str, reason: str, at: int) -> dict:
    files = file_hashes(prod, agent_id)
    return {
        "locked": True,
        "at": at,
        "reason": reason,
        "fingerprint": agent_fingerprint(prod, agent_id, files),
        "files": files,
        "upstream": upstream_fingerprints(prod, agent_id),
    }


def story_migrated(prod: Path) -> bool:
    bible = prod / "01-bible"
    source = bible / "source"
    official = []
    if source.exists():
        official = [
            path
            for path in source.rglob("*")
            if path.is_file() and not _is_draft(path) and path.name != ".DS_Store"
        ]
    if official:
        return False
    return any(_exists(bible / name) for name in ("CAST.md", "blueprint.md", "ep01.md"))


def actually_locked(approvals: dict, agent_id: str) -> bool:
    return bool((approvals.get("gates") or {}).get(agent_id, {}).get("locked"))


def virtual_locked(prod: Path, agent_id: str, files: dict, approvals: dict) -> bool:
    if actually_locked(approvals, agent_id):
        return False
    if agent_id == "0":
        return story_migrated(prod) or actually_locked(approvals, "A")
    if agent_id == "P":
        return actually_locked(approvals, "B")
    if agent_id in {"C1", "C2"}:
        return actually_locked(approvals, "C") and not (prod / ".pipeline" / ("shot_specs.json" if agent_id == "C1" else "gen_packages.json")).exists()
    if agent_id == "D":
        return actually_locked(approvals, "C") and bool(files.get("locked_frame_count"))
    if agent_id == "E":
        d_locked = actually_locked(approvals, "D") or actually_locked(approvals, "C")
        shot_count = int(files.get("shot_count") or 0)
        video_count = int(files.get("video_count") or 0)
        return bool(d_locked and shot_count and video_count >= shot_count)
    if agent_id == "F":
        return bool(files.get("episode_export"))
    return False


def is_locked(prod: Path, agent_id: str, files: dict, approvals: dict) -> bool:
    return actually_locked(approvals, agent_id) or virtual_locked(prod, agent_id, files, approvals)


def stale_reason(prod: Path, agent_id: str, approvals: dict) -> str:
    rec = (approvals.get("gates") or {}).get(agent_id) or {}
    if not rec.get("locked") or not rec.get("fingerprint"):
        return ""
    live_files = file_hashes(prod, agent_id)
    live = agent_fingerprint(prod, agent_id, live_files)
    if live != rec.get("fingerprint"):
        changed = [
            rel
            for rel, digest in live_files.items()
            if (rec.get("files") or {}).get(rel) != digest
        ]
        missing = [rel for rel in (rec.get("files") or {}) if rel not in live_files]
        names = changed or missing or ["正式文件"]
        return "正式文件已改：" + ", ".join(names[:6])
    for uid, digest in (rec.get("upstream") or {}).items():
        if agent_fingerprint(prod, uid) != digest:
            return f"上游 {uid} 已修改，需要重审"
    return ""


def is_stale(prod: Path, agent_id: str, approvals: Optional[dict] = None) -> bool:
    approvals = approvals if approvals is not None else load_approvals(prod)
    return bool(stale_reason(prod, agent_id, approvals))


def assert_not_stale(prod: Path, agent_id: str) -> None:
    approvals = load_approvals(prod)
    reason = stale_reason(prod, agent_id, approvals)
    if reason:
        raise PermissionError(f"关卡 {agent_id} 已失效：{reason}。重审后再出片。")


def previous_satisfied(prod: Path, gate_id: str, files: dict, approvals: dict) -> bool:
    if gate_id in {"0", "A"}:
        if gate_id == "A":
            source = prod / "01-bible" / "source"
            has_source = source.exists() and any(
                path.is_file() and not _is_draft(path) for path in source.rglob("*")
            )
            if has_source:
                return is_locked(prod, "0", files, approvals)
        return True
    if gate_id == "P":
        return is_locked(prod, "A", files, approvals)
    if gate_id == "B":
        return is_locked(prod, "P", files, approvals) or actually_locked(approvals, "A")
    if gate_id == "S":
        return is_locked(prod, "B", files, approvals)
    if gate_id == "C":
        return actually_locked(approvals, "S") or is_locked(prod, "B", files, approvals)
    if gate_id == "C1":
        return is_locked(prod, "C", files, approvals)
    if gate_id == "C2":
        return is_locked(prod, "C1", files, approvals) or is_locked(prod, "C", files, approvals)
    if gate_id == "D":
        return is_locked(prod, "C2", files, approvals) or actually_locked(approvals, "C")
    if gate_id == "E":
        return is_locked(prod, "D", files, approvals) or actually_locked(approvals, "C")
    if gate_id == "E+":
        return is_locked(prod, "E", files, approvals) or actually_locked(approvals, "D")
    if gate_id == "F":
        return is_locked(prod, "E+", files, approvals) or bool(files.get("episode_export"))
    return False


def draft_paths(prod: Path, agent_id: str) -> list[str]:
    candidates = {
        "0": [
            "01-bible/source/brief.draft.md",
            "01-bible/source/source.draft.json",
            "01-bible/source/original.draft.md",
            "01-bible/source/story-outline.draft.md",
            "01-bible/source/characters.draft.md",
            "01-bible/source/timeline.draft.md",
        ],
        "A": [
            "01-bible/blueprint.draft.md",
            "01-bible/script.draft.txt",
            "01-bible/overview.draft.json",
        ],
        "P": [
            "01-bible/producer/plan.draft.md",
            "01-bible/producer/manifest.draft.json",
        ],
        "C": [
            "03-storyboard/shots.draft.json",
            "03-storyboard/beats.draft.md",
            "03-storyboard/coverage.draft.md",
            "03-storyboard/sets.draft.json",
            ".pipeline/shot_list.json",
        ],
        "C1": [".pipeline/shot_specs.json"],
        "C2": [".pipeline/gen_packages.json"],
        "D": [".pipeline/keyframes.json"],
        "E": [".pipeline/clips.json"],
        "E+": ["07-dubbing/sound-contract.draft.json", ".pipeline/audio.json"],
        "F": ["08-qc/report.draft.json", "08-qc/report.draft.md", ".pipeline/cut.json"],
    }
    found = []
    for rel in candidates.get(agent_id, []):
        if _exists(prod / rel):
            found.append(rel)
    return found


def ui_status(*, locked: bool, stale: bool, previous: bool, has_draft: bool, ready: bool) -> str:
    if stale:
        return "stale"
    if locked:
        return "locked"
    if not previous:
        return "waiting"
    if has_draft or ready:
        return "draft"
    return "waiting"


def agent_diff(prod: Path, agent_id: str) -> dict:
    approvals = load_approvals(prod)
    rec = (approvals.get("gates") or {}).get(agent_id) or {}
    live = file_hashes(prod, agent_id)
    stored = rec.get("files") or {}
    changed = sorted(
        {rel for rel in set(live) | set(stored) if live.get(rel) != stored.get(rel)}
    )
    upstream = []
    for uid, digest in (rec.get("upstream") or {}).items():
        if agent_fingerprint(prod, uid) != digest:
            upstream.append(uid)
    return {
        "id": agent_id,
        "changed": changed,
        "upstream_changed": upstream,
        "stale": bool(stale_reason(prod, agent_id, approvals) or upstream),
    }


def ensure_lock_fingerprints(prod: Path, approvals: dict) -> tuple[dict, bool]:
    """Fill missing hashes on already-locked gates. Never creates .director."""
    if not approvals_path(prod).exists():
        return approvals, False
    dirty = False
    gates = approvals.setdefault("gates", {})
    for gate_id, rec in list(gates.items()):
        if not rec.get("locked") or rec.get("fingerprint"):
            continue
        if gate_id not in LOCKABLE:
            continue
        filled = lock_record(prod, gate_id, rec.get("reason") or "", int(rec.get("at") or 0))
        rec.update(filled)
        dirty = True
    if dirty:
        save_approvals(prod, approvals)
        approvals = load_approvals(prod)
    return approvals, dirty


def annotate_agent(
    spec: dict,
    prod: Path,
    files: dict,
    approvals: dict,
    ready: bool,
    reason: str,
) -> dict:
    agent_id = spec["id"]
    rec = (approvals.get("gates") or {}).get(agent_id) or {}
    locked_real = bool(rec.get("locked"))
    virtual = virtual_locked(prod, agent_id, files, approvals)
    locked = locked_real or virtual
    stale = bool(stale_reason(prod, agent_id, approvals)) if locked_real else False
    previous = previous_satisfied(prod, agent_id, files, approvals)
    drafts = draft_paths(prod, agent_id)
    status = ui_status(
        locked=locked,
        stale=stale,
        previous=previous,
        has_draft=bool(drafts),
        ready=ready,
    )
    return {
        **spec,
        "ready": ready,
        "locked": locked,
        "virtual": virtual,
        "stale": stale,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "reason": stale_reason(prod, agent_id, approvals) if stale else reason,
        "previous_locked": previous,
        "has_draft": bool(drafts),
        "drafts": drafts,
        "locked_at": rec.get("at"),
        "migrated": agent_id == "0" and virtual and story_migrated(prod),
    }


def migrated_story_view(prod: Path) -> dict:
    bible = prod / "01-bible"
    cast = (bible / "CAST.md").read_text(encoding="utf-8") if _exists(bible / "CAST.md") else ""
    blueprint = (bible / "blueprint.md").read_text(encoding="utf-8") if _exists(bible / "blueprint.md") else ""
    episode = (bible / "ep01.md").read_text(encoding="utf-8") if _exists(bible / "ep01.md") else ""
    people = []
    for line in cast.splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and "中文" not in cells[0]:
            people.append(re.sub(r"\*+", "", cells[0]).strip())
    return {
        "migrated": True,
        "note": "已从旧剧本迁移。正式剧本没有改写。",
        "characters": people[:20],
        "cast": cast,
        "outline": blueprint,
        "episode": episode,
    }
