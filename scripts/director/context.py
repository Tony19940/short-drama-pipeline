"""Explicit production / episode / revision context. No shared mutable current episode."""

from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .pipeline import episode_artifact_name, episode_frame_dir, episode_label, episode_number, episode_shot_dir, parse_episode
from .revisions import RevisionBinding, resolve_binding

_ACTIVE: ContextVar[Optional["ProductionContext"]] = ContextVar("director_production_context", default=None)
_ACTIVE_EPISODE: ContextVar[Any] = ContextVar("director_active_episode", default=1)


@dataclass(frozen=True)
class ProductionContext:
    prod: Path
    production_id: str
    episode_id: str
    episode_no: int
    revision_id: str
    binding: Optional[RevisionBinding] = field(default=None, repr=False, compare=False)

    @classmethod
    def resolve(cls, prod: Path, episode: Any = 1, revision_id: str = "") -> "ProductionContext":
        prod = Path(prod)
        binding = resolve_binding(prod, episode, revision_id)
        no, label = parse_episode(binding.episode_token)
        episode_id = binding.episode_id if binding.mode == "registered" else label or ("" if no == 1 else f"ep{no:02d}")
        return cls(
            prod=prod,
            production_id=prod.name,
            episode_id=episode_id,
            episode_no=no,
            revision_id=binding.revision_id,
            binding=binding,
        )

    @property
    def episode_token(self) -> Any:
        if self.binding is not None:
            return self.binding.episode_token
        return self.episode_id or self.episode_no

    def artifact_name(self, base: str) -> str:
        if self.binding is not None:
            rel = Path(self.binding.artifact_rel(base))
            try:
                return rel.relative_to(".pipeline").as_posix()
            except ValueError as exc:
                raise ValueError("artifact is outside .pipeline; use context.read_artifact or artifact_path") from exc
        return episode_artifact_name(base, self.episode_token)

    def artifact_rel(self, base: str) -> str:
        return self.binding.artifact_rel(base) if self.binding is not None else f".pipeline/{self.artifact_name(base)}"

    def artifact_path(self, base: str) -> Path:
        return self.prod / self.artifact_rel(base)

    def read_artifact(self, base: str, default: Optional[dict] = None, *, required: bool = False) -> dict:
        binding = self.binding or resolve_binding(self.prod, self.episode_token, self.revision_id)
        return binding.read_artifact(base, default, required=required)

    def source_report(self, base: str = "shot_list.json") -> dict:
        binding = self.binding or resolve_binding(self.prod, self.episode_token, self.revision_id)
        return binding.source_report(base)

    @property
    def mode(self) -> str:
        return self.binding.mode if self.binding is not None else "legacy"

    def cut_rel(self) -> str:
        return self.artifact_rel("cut.json")

    def frame_dir(self) -> str:
        if self.binding is not None:
            return self.binding.frames_dir
        return episode_frame_dir(self.episode_token)

    def shot_dir(self) -> str:
        if self.binding is not None:
            return self.binding.shots_dir
        return episode_shot_dir(self.episode_token)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "episode_id": self.episode_id or f"ep{self.episode_no:02d}",
            "episode_no": self.episode_no,
            "revision_id": self.revision_id,
            "binding_mode": self.mode,
        }


def current_context() -> Optional[ProductionContext]:
    return _ACTIVE.get()


def context_for(prod: Path, episode: Any = None, revision_id: str = "") -> ProductionContext:
    """Use an explicit/current revision without borrowing another production."""
    if isinstance(prod, ProductionContext):
        return prod
    current = current_context()
    if current is not None and current.prod.resolve() == Path(prod).resolve() and not revision_id:
        number, label = parse_episode(episode)
        if episode is None or (number == current.episode_no and (not label or label == f"ep{number:02d}" or label == current.episode_token)):
            return current
    return ProductionContext.resolve(prod, 1 if episode is None else episode, revision_id)


@contextmanager
def using_context(ctx: ProductionContext):
    """Task-local binding, restored even if a check or worker raises."""
    token = _ACTIVE.set(ctx)
    episode_token = _ACTIVE_EPISODE.set(ctx.episode_token)
    try:
        yield ctx
    finally:
        _ACTIVE.reset(token)
        _ACTIVE_EPISODE.reset(episode_token)


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
