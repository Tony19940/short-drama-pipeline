"""Production filesystem helpers. The studio never invents a second database."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
PRODUCTIONS = ROOT / "productions"
DIRECTOR_DIRNAME = ".director"
SLUG_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def productions_root() -> Path:
    return PRODUCTIONS


def list_productions() -> list[Path]:
    if not PRODUCTIONS.exists():
        return []
    items = []
    for child in sorted(PRODUCTIONS.iterdir()):
        if child.is_dir() and not child.name.startswith("_") and not child.name.startswith("."):
            if (child / "01-bible").exists() or (child / "03-storyboard").exists():
                items.append(child)
    return items


def prod_path(slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ValueError(f"非法项目名：{slug}")
    path = (PRODUCTIONS / slug).resolve()
    if PRODUCTIONS.resolve() not in path.parents and path != PRODUCTIONS.resolve():
        raise ValueError("项目路径越界")
    if not path.exists():
        raise FileNotFoundError(f"没有这个项目：{slug}")
    return path


def director_dir(prod: Path, create: bool = False) -> Path:
    path = prod / DIRECTOR_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
        (path / "candidates").mkdir(exist_ok=True)
        (path / "backups").mkdir(exist_ok=True)
        (path / "inbox").mkdir(exist_ok=True)
    return path


def safe_under(prod: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"非法路径：{rel}")
    path = (prod / rel_path).resolve()
    if prod.resolve() not in path.parents and path != prod.resolve():
        raise ValueError(f"路径越界：{rel}")
    return path


def media_kind(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".m4a", ".wav", ".mp3"}:
        return "video" if suffix in {".mp4", ".mov", ".webm"} else "audio"
    if suffix in {".md", ".json", ".txt", ".html"}:
        return "text"
    return None


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def media_url(prod: Path, rel: str) -> Optional[str]:
    rel = str(rel).replace("\\", "/").lstrip("/")
    path = prod / rel
    if not path.exists() or not path.is_file():
        return None
    return f"/media/{prod.name}/{rel}?v={int(path.stat().st_mtime)}"
