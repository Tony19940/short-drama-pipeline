"""One explicit binding for an episode revision, shared by every production stage.

No registry means the historical episode-label layout is retained. Once a
registry exists, missing/unknown active revisions never fall back to old files.
Paths may be production-relative or absolute *inside* this production.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REGISTRY_REL = ".pipeline/revisions.json"
SCHEMA = "production-revisions-v1"
ROUTED_ARTIFACTS = frozenset({
    "writer.json", "shot_list.json", "shot_specs.json", "gen_packages.json",
    "keyframes.json", "clips.json", "audio.json", "cut.json",
    "frame_descriptions.json", "scene_cards.json", "events.json",
    "event_evidence.json", "sequence_reviews.json", "narrative_reviews.json",
})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RevisionError(ValueError):
    """An absent or ambiguous production binding; a caller must not fall back."""


def _relative(prod: Path, value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or "\\" in text:
        raise RevisionError(f"{label}: missing or invalid production path")
    raw = Path(text)
    if ".." in raw.parts:
        raise RevisionError(f"{label}: parent traversal is forbidden")
    root = Path(prod).resolve()
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise RevisionError(f"{label}: path is outside production") from exc
    if rel == ".":
        raise RevisionError(f"{label}: production root is not an artifact path")
    return rel


def _episode(episode: Any) -> tuple[int, str, str]:
    from .pipeline import parse_episode

    number, label = parse_episode(episode)
    return number, f"ep{number:02d}", label


def _id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise RevisionError(f"invalid {label}: {text!r}")
    return text


@dataclass(frozen=True)
class RevisionBinding:
    prod: Path
    mode: str
    episode_id: str
    episode_no: int
    revision_id: str = ""
    artifact_token: Any = 1
    artifacts: dict[str, str] = field(default_factory=dict)
    frames_dir: str = "04-frames"
    shots_dir: str = "05-shots"
    cut_file: str = ".pipeline/cut.json"

    @property
    def episode_token(self) -> Any:
        return self.artifact_token

    def artifact_rel(self, base: str) -> str:
        from .pipeline import episode_artifact_name

        if "/" in base or "\\" in base or ".." in base:
            raise RevisionError(f"expected a base artifact name, got {base!r}")
        if base == "cut.json":
            return self.cut_file
        return self.artifacts.get(base) or f".pipeline/{episode_artifact_name(base, self.artifact_token)}"

    def artifact_path(self, base: str) -> Path:
        return self.prod / self.artifact_rel(base)

    def read_artifact(self, base: str, default: Optional[dict] = None, *, required: bool = False) -> dict:
        path = self.artifact_path(base)
        if not path.is_file():
            if required:
                raise RevisionError(f"missing {self.episode_id}/{self.revision_id or 'legacy'} artifact: {self.artifact_rel(base)}")
            return {} if default is None else json.loads(json.dumps(default))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RevisionError(f"invalid revision artifact: {self.artifact_rel(base)}") from exc
        if not isinstance(data, dict):
            raise RevisionError(f"revision artifact must be an object: {self.artifact_rel(base)}")
        return data

    def to_dict(self) -> dict:
        return {
            "production_id": self.prod.name, "episode_id": self.episode_id,
            "episode_no": self.episode_no, "revision_id": self.revision_id,
            "binding_mode": self.mode, "artifact_token": self.artifact_token,
            "frames_dir": self.frames_dir, "shots_dir": self.shots_dir,
            "cut_file": self.cut_file, "artifacts": dict(self.artifacts),
        }

    def source_report(self, base: str = "shot_list.json") -> dict:
        path = self.artifact_path(base)
        report = self.to_dict()
        report.update(source_file=self.artifact_rel(base), source_sha256="", shot_count=0)
        if path.is_file():
            report["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            data = self.read_artifact(base, required=True)
            report["shot_count"] = len(data.get("shots") or [])
        return report


def load_registry(prod: Path) -> Optional[dict]:
    path = Path(prod) / REGISTRY_REL
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RevisionError(f"invalid revision registry: {REGISTRY_REL}") from exc
    return validate_registry(prod, raw)


def validate_registry(prod: Path, raw: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise RevisionError(f"revision registry needs schema={SCHEMA}")
    if raw.get("production_id") not in (None, "", Path(prod).name):
        raise RevisionError("revision registry belongs to another production")
    active = raw.get("active")
    rows = raw.get("revisions")
    if not isinstance(active, dict) or not isinstance(rows, list) or not rows:
        raise RevisionError("revision registry needs active object and nonempty revisions list")
    result = {"schema": SCHEMA, "production_id": Path(prod).name, "active": {}, "revisions": []}
    seen = set()
    tokens = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RevisionError("revision entry must be an object")
        number, ep, _ = _episode(row.get("episode_id") or row.get("episode_no") or 1)
        rev = _id(row.get("revision_id"), "revision_id")
        if (ep, rev) in seen:
            raise RevisionError(f"duplicate revision: {ep}/{rev}")
        seen.add((ep, rev))
        token = str(row.get("artifact_token") or f"{ep}-{rev}")
        token_no, _, token_label = _episode(token)
        if token_no != number or not token_label:
            raise RevisionError(f"artifact_token must be a labeled revision of {ep}")
        if token_label in tokens:
            raise RevisionError(f"duplicate artifact_token: {token_label}")
        tokens.add(token_label)
        artifacts = row.get("artifacts") or {}
        if not isinstance(artifacts, dict):
            raise RevisionError("artifacts must map base names to production paths")
        normalized = {}
        for base, value in artifacts.items():
            if "/" in base or "\\" in base or ".." in base or not base.endswith(".json"):
                raise RevisionError(f"invalid artifact base name: {base!r}")
            normalized[base] = _relative(prod, value, label=base)
        from .pipeline import episode_artifact_name

        normalized.setdefault("shot_list.json", f".pipeline/{episode_artifact_name('shot_list.json', token_label)}")
        cut_file = _relative(prod, row.get("cut_file") or normalized.get("cut.json") or f".pipeline/{episode_artifact_name('cut.json', token_label)}", label="cut_file")
        normalized["cut.json"] = cut_file
        result["revisions"].append({
            "episode_id": ep, "episode_no": number, "revision_id": rev,
            "artifact_token": token_label, "artifacts": normalized,
            "frames_dir": _relative(prod, row.get("frames_dir") or f"04-frames/{token_label}", label="frames_dir"),
            "shots_dir": _relative(prod, row.get("shots_dir") or f"05-shots/{token_label}", label="shots_dir"),
            "cut_file": cut_file,
        })
    for episode, revision in active.items():
        _, ep, _ = _episode(episode)
        rev = _id(revision, "active revision")
        if (ep, rev) not in seen:
            raise RevisionError(f"active revision is not registered: {ep}/{rev}")
        if ep in result["active"] and result["active"][ep] != rev:
            raise RevisionError(f"conflicting active aliases for {ep}")
        result["active"][ep] = rev
    return result


def resolve_binding(prod: Path, episode: Any = 1, revision_id: str = "") -> RevisionBinding:
    prod = Path(prod)
    number, ep, label = _episode(episode)
    registry = load_registry(prod)
    requested = str(revision_id or "").strip()
    if registry is None:
        from .pipeline import episode_artifact_name, episode_frame_dir, episode_shot_dir

        token = episode
        if requested:
            requested = _id(requested, "revision_id")
            token = requested if requested.startswith(ep + "-") else f"{ep}-{requested}"
            if label and label != token:
                raise RevisionError("episode label and explicit revision disagree")
            requested = token[len(ep) + 1:]
        legacy_revision = requested or (label[len(ep) + 1:] if label.startswith(ep + "-") else "")
        return RevisionBinding(prod, "legacy", label or ep, number, legacy_revision, token,
                               frames_dir=episode_frame_dir(token), shots_dir=episode_shot_dir(token),
                               cut_file=f".pipeline/{episode_artifact_name('cut.json', token)}")
    rows = [row for row in registry["revisions"] if row["episode_id"] == ep]
    if requested:
        matches = [row for row in rows if row["revision_id"] == requested or row["artifact_token"] == requested]
        if label and matches and matches[0]["artifact_token"] != label:
            raise RevisionError("episode label and explicit revision disagree")
    elif label and label != ep:
        matches = [row for row in rows if row["artifact_token"] == label]
    else:
        active = registry["active"].get(ep)
        if not active:
            raise RevisionError(f"no active revision for {ep}; choose --revision explicitly")
        matches = [row for row in rows if row["revision_id"] == active]
    if len(matches) != 1:
        raise RevisionError(f"unknown or ambiguous revision: {ep}/{requested or label or 'active'}")
    row = matches[0]
    return RevisionBinding(prod=prod, mode="registered", **row)


def register_revision(prod: Path, row: dict, *, activate: bool = False) -> dict:
    """Register paths only. Never changes production tables, images or approvals."""
    prod = Path(prod)
    old = load_registry(prod) or {"schema": SCHEMA, "production_id": prod.name, "active": {}, "revisions": []}
    candidate = json.loads(json.dumps(old))
    _, ep, _ = _episode(row.get("episode_id") or row.get("episode_no") or 1)
    rev = _id(row.get("revision_id"), "revision_id")
    if any(r["episode_id"] == ep and r["revision_id"] == rev for r in candidate["revisions"]):
        raise RevisionError(f"revision already registered: {ep}/{rev}; use a new revision ID")
    candidate["revisions"].append(dict(row, episode_id=ep, revision_id=rev))
    if activate:
        candidate["active"][ep] = rev
    normalized = validate_registry(prod, candidate)
    _save_registry(prod, normalized)
    return normalized


def _save_registry(prod: Path, registry: dict) -> None:
    path = Path(prod) / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def activate_revision(prod: Path, episode: Any, revision_id: str) -> dict:
    registry = load_registry(prod)
    if registry is None:
        raise RevisionError("no revision registry")
    binding = resolve_binding(prod, episode, revision_id)
    registry["active"][f"ep{binding.episode_no:02d}"] = binding.revision_id
    _save_registry(prod, registry)
    return binding.to_dict()


def routed_artifact_path(prod: Path, name: str) -> Optional[Path]:
    """Compatibility bridge for old read_artifact calls in registered shows."""
    from .pipeline import parse_artifact_filename

    if not (Path(prod) / REGISTRY_REL).exists():
        return None
    base, episode = parse_artifact_filename(name)
    registry = load_registry(prod)
    mapped = {key for row in registry["revisions"] for key in row["artifacts"]}
    if base not in ROUTED_ARTIFACTS and base not in mapped:
        return None
    from .context import context_for

    return context_for(prod, episode).artifact_path(base)
