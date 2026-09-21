"""Take (generated clip) vs EditSegment (what the cut actually uses).

A director Shot is the plan. A Take is one paid generation. An EditSegment
is the slice of a take that lands in the assembly. Model min duration does
not dictate editorial in/out.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .vendor_request import sha256_file

TAKES_REL = ".pipeline/takes.json"


@dataclass
class Take:
    take_id: str
    shot_id: str
    request_hash: str
    dest: str
    media_hash: str = ""
    task_id: str = ""
    qc: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    episode_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditSegment:
    segment_id: str
    take_id: str
    shot_id: str
    in_sec: float
    out_sec: float
    audio_in_sec: float = 0.0
    audio_out_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _store_path(prod: Path) -> Path:
    return Path(prod) / TAKES_REL


def load_takes(prod: Path) -> dict[str, Any]:
    path = _store_path(prod)
    if not path.is_file():
        return {"takes": [], "segments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"takes": [], "segments": []}
    if not isinstance(data, dict):
        return {"takes": [], "segments": []}
    data.setdefault("takes", [])
    data.setdefault("segments", [])
    return data


def persist_take(prod: Path, take: Take) -> Take:
    data = load_takes(prod)
    rows = [item for item in data["takes"] if item.get("take_id") != take.take_id]
    body = take.to_dict()
    if not body.get("created_at"):
        body["created_at"] = int(time.time())
    rows.append(body)
    data["takes"] = rows
    dest = _store_path(prod)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return take


def take_from_render(
    *,
    shot_id: str,
    dest: Path,
    request_hash: str,
    task_id: str = "",
    episode_id: str = "",
    qc: Optional[dict] = None,
) -> Take:
    media = sha256_file(dest) if dest.is_file() else ""
    return Take(
        take_id=f"{shot_id}-{request_hash[:12]}" if request_hash else f"{shot_id}-{int(time.time())}",
        shot_id=shot_id,
        request_hash=request_hash,
        dest=str(dest),
        media_hash=media,
        task_id=task_id,
        qc=dict(qc or {}),
        created_at=int(time.time()),
        episode_id=episode_id,
    )
