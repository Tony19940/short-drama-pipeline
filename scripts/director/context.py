"""Explicit production / episode / revision context. No shared mutable current episode."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .pipeline import episode_artifact_name, episode_frame_dir, episode_label, episode_number, episode_shot_dir, parse_episode

_ACTIVE: ContextVar[Optional["ProductionContext"]] = ContextVar("director_production_context", default=None)
_ACTIVE_EPISODE: ContextVar[Any] = ContextVar("director_active_episode", default=1)


@dataclass(frozen=True)
class ProductionContext:
    prod: Path
    production_id: str
    episode_id: str
    episode_no: int
    revision_id: str

    @classmethod
    def resolve(cls, prod: Path, episode: Any = 1, revision_id: str = "") -> "ProductionContext":
        prod = Path(prod)
        no, label = parse_episode(episode)
        episode_id = label or ("" if no == 1 else f"ep{no:02d}")
        return cls(
            prod=prod,
            production_id=prod.name,
            episode_id=episode_id,
            episode_no=no,
            revision_id=str(revision_id or ""),
        )

    @property
    def episode_token(self) -> Any:
        return self.episode_id or self.episode_no

    def artifact_name(self, base: str) -> str:
        return episode_artifact_name(base, self.episode_token)

    def frame_dir(self) -> str:
        return episode_frame_dir(self.episode_token)

    def shot_dir(self) -> str:
        return episode_shot_dir(self.episode_token)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "episode_id": self.episode_id or f"ep{self.episode_no:02d}",
            "episode_no": self.episode_no,
            "revision_id": self.revision_id,
        }


def current_context() -> Optional[ProductionContext]:
    return _ACTIVE.get()


def set_current_context(ctx: Optional[ProductionContext]) -> Optional[ProductionContext]:
    prev = _ACTIVE.get()
    _ACTIVE.set(ctx)
    if ctx is not None:
        _ACTIVE_EPISODE.set(ctx.episode_token)
    return prev


def active_episode_token() -> Any:
    ctx = _ACTIVE.get()
    if ctx is not None:
        return ctx.episode_token
    return _ACTIVE_EPISODE.get()


def set_active_episode_token(episode: Any) -> Any:
    prev = active_episode_token()
    token = 1 if episode in (None, "") else episode
    _ACTIVE_EPISODE.set(token)
    return prev
