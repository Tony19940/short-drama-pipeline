"""Take (generated clip) vs EditSegment (what the cut actually uses).

A director Shot is the plan. A Take is one paid generation. An EditSegment
is the slice of a take that lands in the assembly. Model min duration does
not dictate editorial in/out.

take_id is an independent media identity. request_hash proves the confirmed
input. attempt_id distinguishes a vendor-task resume from a new paid try.
Official 05-shots/<id>.mp4 is the current selection index, not unique storage.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .vendor_request import sha256_file

TAKES_REL = ".pipeline/takes.json"
TAKE_MEDIA_DIR = ".pipeline/takes/media"


def episode_key(episode: Any = 1) -> str:
    from .pipeline import episode_label, episode_number

    return episode_label(episode) or str(episode_number(episode))


def episode_export_rel(episode: Any = 1) -> str:
    from .pipeline import episode_label, episode_number

    label = episode_label(episode)
    if label:
        return f"06-export/{label}.mp4"
    return f"06-export/ep{episode_number(episode):02d}.mp4"


def selected_key(shot_id: str, episode: Any = 1) -> str:
    return f"{episode_key(episode)}:{shot_id}"


@dataclass
class Take:
    take_id: str
    shot_id: str
    request_hash: str
    dest: str
    media_hash: str = ""
    task_id: str = ""
    attempt_id: str = ""
    qc: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    episode_id: str = ""
    revision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Take":
        return cls(
            take_id=str(data.get("take_id") or ""),
            shot_id=str(data.get("shot_id") or ""),
            request_hash=str(data.get("request_hash") or ""),
            dest=str(data.get("dest") or ""),
            media_hash=str(data.get("media_hash") or ""),
            task_id=str(data.get("task_id") or ""),
            attempt_id=str(data.get("attempt_id") or ""),
            qc=dict(data.get("qc") or {}),
            created_at=int(data.get("created_at") or 0),
            episode_id=str(data.get("episode_id") or ""),
            revision_id=str(data.get("revision_id") or ""),
        )


@dataclass
class EditSegment:
    segment_id: str
    take_id: str
    shot_id: str
    in_sec: float
    out_sec: float
    audio_in_sec: float = 0.0
    audio_out_sec: float = 0.0
    audio_take_id: str = ""
    episode_id: str = ""
    revision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditSegment":
        inn = data.get("in_sec", data.get("in_point", 0))
        out = data.get("out_sec", data.get("out_point", 0))
        audio_in = data.get("audio_in_sec", inn)
        audio_out = data.get("audio_out_sec", out)
        return cls(
            segment_id=str(data.get("segment_id") or ""),
            take_id=str(data.get("take_id") or ""),
            shot_id=str(data.get("shot_id") or ""),
            in_sec=float(inn or 0),
            out_sec=float(out or 0),
            audio_in_sec=float(audio_in or 0),
            audio_out_sec=float(audio_out or 0),
            audio_take_id=str(data.get("audio_take_id") or ""),
            episode_id=str(data.get("episode_id") or ""),
            revision_id=str(data.get("revision_id") or ""),
        )


def _store_path(prod: Path) -> Path:
    return Path(prod) / TAKES_REL


def load_takes(prod: Path) -> dict[str, Any]:
    path = _store_path(prod)
    if not path.is_file():
        return {"takes": [], "segments": [], "selected": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"takes": [], "segments": [], "selected": {}}
    if not isinstance(data, dict):
        return {"takes": [], "segments": [], "selected": {}}
    data.setdefault("takes", [])
    data.setdefault("segments", [])
    data.setdefault("selected", {})
    return data


def _write_store(prod: Path, data: dict[str, Any]) -> None:
    dest = _store_path(prod)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)


def persist_take(prod: Path, take: Take) -> Take:
    from .store import exclusive_state_lock

    with exclusive_state_lock(prod, "takes"):
        data = load_takes(prod)
        rows = [item for item in data["takes"] if item.get("take_id") != take.take_id]
        body = take.to_dict()
        if not body.get("created_at"):
            body["created_at"] = int(time.time())
        rows.append(body)
        data["takes"] = rows
        _write_store(prod, data)
    return take


def get_take(prod: Path, take_id: str) -> Optional[Take]:
    want = str(take_id or "").strip()
    if not want:
        return None
    for item in load_takes(prod).get("takes") or []:
        if str(item.get("take_id") or "") == want:
            return Take.from_dict(item)
    return None


def takes_for_shot(prod: Path, shot_id: str, episode: Any = 1) -> list[Take]:
    key = episode_key(episode)
    rows = []
    for item in load_takes(prod).get("takes") or []:
        if item.get("shot_id") != shot_id:
            continue
        stored = str(item.get("episode_id") or "1")
        if stored not in {"", key, str(episode)} and episode_key(stored) != key:
            continue
        rows.append(Take.from_dict(item))
    rows.sort(key=lambda item: item.created_at)
    return rows


def find_resume_take(prod: Path, *, shot_id: str, request_hash: str, task_id: str, episode: Any = 1) -> Optional[Take]:
    if not request_hash or not task_id:
        return None
    for take in takes_for_shot(prod, shot_id, episode):
        if take.request_hash == request_hash and take.task_id == task_id:
            return take
    return None


def selected_take_id(prod: Path, shot_id: str, episode: Any = 1) -> str:
    data = load_takes(prod)
    return str((data.get("selected") or {}).get(selected_key(shot_id, episode)) or "")


def selected_take(prod: Path, shot_id: str, episode: Any = 1) -> Optional[Take]:
    return get_take(prod, selected_take_id(prod, shot_id, episode))


def take_media_rel(take_id: str) -> str:
    return f"{TAKE_MEDIA_DIR}/{take_id}.mp4"


def freeze_take_media(prod: Path, src: Path, take_id: str) -> tuple[str, str]:
    rel = take_media_rel(take_id)
    dest = Path(prod) / rel
    src = Path(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() != src.resolve():
        tmp = dest.with_suffix(".mp4.part")
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
    return rel, sha256_file(dest)


def take_media_file(prod: Path, take: Take | dict) -> Path:
    row = take if isinstance(take, dict) else take.to_dict()
    rel = str(row.get("dest") or "")
    path = Path(rel) if Path(rel).is_absolute() else Path(prod) / rel
    if not path.is_file():
        raise PermissionError(f"take media missing: {rel}")
    digest = str(row.get("media_hash") or "")
    if digest and sha256_file(path) != digest:
        raise PermissionError(f"take media changed: {rel}")
    return path


def resolve_shot_media(prod: Path, shot_id: str, episode: Any = 1) -> Path:
    take = selected_take(prod, shot_id, episode)
    if take:
        return take_media_file(prod, take)
    from .pipeline import episode_shot_dir

    official = Path(prod) / episode_shot_dir(episode) / f"{shot_id}.mp4"
    if official.is_file():
        return official
    fallback = Path(prod) / "05-shots" / f"{shot_id}.mp4"
    if fallback.is_file():
        return fallback
    raise PermissionError(f"缺单镜视频：{shot_id}")


def _set_selected(prod: Path, shot_id: str, take_id: str, episode: Any = 1) -> None:
    from .store import exclusive_state_lock

    with exclusive_state_lock(prod, "takes"):
        data = load_takes(prod)
        selected = dict(data.get("selected") or {})
        selected[selected_key(shot_id, episode)] = take_id
        data["selected"] = selected
        _write_store(prod, data)


def select_take(prod: Path, shot_id: str, take_id: str, episode: Any = 1) -> Take:
    take = get_take(prod, take_id)
    if take is None or take.shot_id != shot_id:
        raise PermissionError(f"take {take_id} is not a candidate for {shot_id}")
    src = take_media_file(prod, take)
    from .pipeline import episode_shot_dir

    official = Path(prod) / episode_shot_dir(episode) / f"{shot_id}.mp4"
    official.parent.mkdir(parents=True, exist_ok=True)
    if official.resolve() != src.resolve():
        tmp = official.with_suffix(".mp4.part")
        shutil.copyfile(src, tmp)
        tmp.replace(official)
    _set_selected(prod, shot_id, take.take_id, episode)
    _retarget_cut(prod, shot_id, take.take_id, episode)
    return take


def _retarget_cut(prod: Path, shot_id: str, take_id: str, episode: Any = 1) -> None:
    from .pipeline import episode_artifact_name, read_artifact, write_artifact

    name = episode_artifact_name("cut.json", episode)
    cut = read_artifact(prod, name)
    timeline = list(cut.get("timeline") or [])
    if not timeline:
        return
    changed = False
    for item in timeline:
        if item.get("shot_id") == shot_id and item.get("take_id") != take_id:
            item["take_id"] = take_id
            changed = True
    if changed:
        write_artifact(prod, name, cut)


def _infer_prod(dest: Path) -> Path:
    parts = Path(dest).resolve().parts
    for index, name in enumerate(parts):
        if name == "05-shots":
            return Path(*parts[:index])
    return Path(dest).resolve().parent


def take_from_render(
    *,
    shot_id: str,
    dest: Path,
    request_hash: str,
    task_id: str = "",
    episode_id: str = "",
    revision_id: str = "",
    qc: Optional[dict] = None,
    take_id: str = "",
    attempt_id: str = "",
    prod: Optional[Path] = None,
) -> Take:
    dest = Path(dest)
    tid = take_id or f"take-{uuid.uuid4().hex[:12]}"
    root = Path(prod) if prod else _infer_prod(dest)
    if dest.is_file():
        rel, media = freeze_take_media(root, dest, tid)
    else:
        rel, media = str(dest), ""
    return Take(
        take_id=tid,
        shot_id=shot_id,
        request_hash=request_hash,
        dest=rel,
        media_hash=media,
        task_id=task_id,
        attempt_id=attempt_id or f"attempt-{uuid.uuid4().hex[:12]}",
        qc=dict(qc or {}),
        created_at=int(time.time()),
        episode_id=str(episode_id or episode_key(1)),
        revision_id=str(revision_id or ""),
    )


def record_render_take(
    prod: Path,
    *,
    shot_id: str,
    dest: Path,
    request_hash: str,
    task_id: str = "",
    episode: Any = 1,
    revision_id: str = "",
    qc: Optional[dict] = None,
    new_attempt: bool = False,
) -> Take:
    dest = Path(dest)
    ep = episode_key(episode)
    existing = None if new_attempt else find_resume_take(
        prod, shot_id=shot_id, request_hash=request_hash, task_id=task_id, episode=episode
    )
    take_id = existing.take_id if existing else f"take-{uuid.uuid4().hex[:12]}"
    attempt_id = existing.attempt_id if existing else f"attempt-{uuid.uuid4().hex[:12]}"
    rel, digest = freeze_take_media(prod, dest, take_id)
    take = Take(
        take_id=take_id,
        shot_id=shot_id,
        request_hash=request_hash,
        dest=rel,
        media_hash=digest,
        task_id=task_id,
        attempt_id=attempt_id,
        qc=dict(qc or {}),
        created_at=existing.created_at if existing else int(time.time()),
        episode_id=ep,
        revision_id=str(revision_id or (existing.revision_id if existing else "")),
    )
    persist_take(prod, take)
    select_take(prod, shot_id, take.take_id, episode)
    return take


def persist_segment(prod: Path, segment: EditSegment) -> EditSegment:
    from .store import exclusive_state_lock

    with exclusive_state_lock(prod, "takes"):
        data = load_takes(prod)
        rows = [item for item in data["segments"] if item.get("segment_id") != segment.segment_id]
        rows.append(segment.to_dict())
        data["segments"] = rows
        _write_store(prod, data)
    return segment


def segments_from_timeline(timeline: list[dict], episode: Any = 1) -> list[EditSegment]:
    ep = episode_key(episode)
    out = []
    for index, item in enumerate(timeline):
        if not item.get("used", True):
            continue
        row = dict(item)
        row.setdefault("segment_id", str(item.get("segment_id") or f"seg-{index:03d}-{item.get('shot_id') or index}"))
        row.setdefault("episode_id", item.get("episode_id") or ep)
        out.append(EditSegment.from_dict(row))
    return out


def resolve_segment_takes(prod: Path, segment: EditSegment, episode: Any = 1) -> tuple[Take, Take]:
    picture = get_take(prod, segment.take_id)
    if picture is None and segment.shot_id:
        picture = selected_take(prod, segment.shot_id, episode)
    if picture is None:
        raise PermissionError(f"{segment.shot_id or segment.segment_id} 没有可剪的 Take")
    audio_id = segment.audio_take_id or segment.take_id or picture.take_id
    audio = get_take(prod, audio_id) if audio_id != picture.take_id else picture
    if audio is None:
        audio = picture
    return picture, audio
