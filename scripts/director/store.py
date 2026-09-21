"""JSON state next to a production: approvals, jobs, candidates."""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .paths import director_dir


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def approvals_path(prod: Path) -> Path:
    return director_dir(prod) / "approvals.json"


def jobs_path(prod: Path) -> Path:
    return director_dir(prod) / "jobs.json"


def load_approvals(prod: Path) -> dict:
    data = _read(approvals_path(prod), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("gates", {})
    data.setdefault("frames", {})
    data.setdefault("updated_at", 0)
    return data


def save_approvals(prod: Path, data: dict) -> dict:
    director_dir(prod, create=True)
    data["updated_at"] = int(time.time())
    _write(approvals_path(prod), data)
    return data


def load_jobs(prod: Path) -> dict:
    data = _read(jobs_path(prod), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("jobs", [])
    return data


def save_jobs(prod: Path, data: dict) -> dict:
    director_dir(prod, create=True)
    data["updated_at"] = int(time.time())
    _write(jobs_path(prod), data)
    return data


@contextmanager
def exclusive_state_lock(prod: Path, name: str = "approvals") -> Iterator[None]:
    lock = director_dir(prod, create=True) / f"{name}.lock"
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
