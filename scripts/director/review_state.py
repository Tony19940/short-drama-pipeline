"""Frame / still review state. Landing a file is not a pass."""

from __future__ import annotations

from typing import Any, Optional

REVIEW_STATES = ("unknown", "candidate", "pass", "fail", "awaiting_user")
PLACE_STATES = ("unknown", "candidate")
APPROVED = "pass"


class ReviewStateError(ValueError):
    pass


def normalize_review_state(value: Any, *, default: str = "unknown") -> str:
    state = str(value or "").strip() or default
    if state not in REVIEW_STATES:
        raise ReviewStateError(f"identity_gate 只能是 {' / '.join(REVIEW_STATES)}")
    return state


def default_place_state() -> str:
    return "unknown"


def is_approved(state: Any) -> bool:
    return str(state or "").strip() == APPROVED


def can_use_as_parent(state: Any) -> bool:
    return is_approved(state)


def require_pass_evidence(state: str, checks: Optional[dict]) -> None:
    if state != APPROVED:
        return
    evidence = checks if isinstance(checks, dict) else {}
    reviewer = str(evidence.get("reviewer") or "").strip()
    rule_version = str(evidence.get("rule_version") or "").strip()
    image_hash = str(evidence.get("image_sha256") or evidence.get("content_hash") or "").strip()
    if not (reviewer and rule_version and image_hash):
        raise ReviewStateError(
            "identity_gate=pass 需要绑定 reviewer、rule_version 和 image_sha256；落盘本身只产生 unknown/candidate"
        )
