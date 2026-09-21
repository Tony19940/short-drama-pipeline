"""Choose a heavier generation control only for high-risk shots.

This does not invent vendor fields. It records a recommendation next to the
existing gen_mode / VendorRequest. Paid submit still uses the confirmed request.
"""

from __future__ import annotations

from typing import Any

HAND_WORDS = ("手", "指", "握", "抹", "递", "拧", "接", "交", "捡", "塞", "掏")
OCCLUSION_WORDS = ("挡", "遮", "三人", "两人之间", "穿过", "挤")
EXCHANGE_WORDS = ("交给", "递过", "接过", "换手", "塞进")


def _t(value: Any) -> str:
    return str(value or "").strip()


def _blob(shot: dict) -> str:
    bits = [
        shot.get("one_action"),
        shot.get("shot_job"),
        shot.get("in_from"),
        shot.get("out_to"),
        shot.get("action_now"),
    ]
    return "".join(_t(item) for item in bits)


def high_risk_reasons(shot: Optional[dict]) -> list[str]:
    shot = shot if isinstance(shot, dict) else {}
    blob = _blob(shot)
    reasons: list[str] = []
    if shot.get("hardest"):
        reasons.append("marked_hardest")
    if any(word in blob for word in EXCHANGE_WORDS) or (
        any(word in blob for word in HAND_WORDS) and any(word in blob for word in ("钥", "刀", "杯", "信", "钱", "袋"))
    ):
        reasons.append("hand_prop_exchange")
    if any(word in blob for word in OCCLUSION_WORDS) or _t(shot.get("coverage_type")) in {"otc", "ots"} and "三人" in blob:
        reasons.append("occlusion_or_eyeline")
    move = _t(shot.get("move_type"))
    if move and move not in {"static", ""}:
        reasons.append("moving_camera")
    if _t(shot.get("coverage_type")) == "continuous":
        reasons.append("needs_extend")
    return reasons


def shot_risk_class(shot: Optional[dict]) -> str:
    return "high" if high_risk_reasons(shot) else "normal"


def recommended_control(shot: Optional[dict]) -> str:
    """Which existing task kind is worth trying. Never a new unofficial API field."""
    shot = shot if isinstance(shot, dict) else {}
    reasons = high_risk_reasons(shot)
    planned = _t(shot.get("keyframe_plan"))
    if planned in {"first", "first_last"}:
        return "first_last" if planned == "first_last" else "first_frame"
    if "needs_extend" in reasons:
        return "extend"
    if "hand_prop_exchange" in reasons or "occlusion_or_eyeline" in reasons:
        if _t(shot.get("in_from")) and _t(shot.get("out_to")):
            return "first_last"
        return "reference"
    if "moving_camera" in reasons and _t(shot.get("in_from")) and _t(shot.get("out_to")):
        return "first_last"
    if shot.get("source_video") or _t(shot.get("gen_mode")) == "edit":
        return "edit"
    return "first_frame"


def control_note(shot: Optional[dict]) -> dict:
    reasons = high_risk_reasons(shot)
    return {
        "risk": "high" if reasons else "normal",
        "recommend": recommended_control(shot),
        "reasons": reasons,
    }
