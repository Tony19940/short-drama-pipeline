"""Layered clip QC. Text compliance is never visual proof.

technical  — decode, duration, internal cuts
text       — frame_desc / prompt leftovers (not pixels)
visual     — only a review bound to this media hash; never auto-pass
performance— acting timing; never auto-pass from text
scene_cut  — crude last-to-next-first pixel warning; skipped on setup change
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

LAYERS = ("technical", "text", "visual", "performance", "scene_cut")


def empty_layers() -> dict[str, dict[str, Any]]:
    return {name: {"status": "unknown", "notes": []} for name in LAYERS}


def _note(layer: dict, message: str) -> None:
    if message and message not in layer["notes"]:
        layer["notes"].append(message)


def evaluate_clip_layers(
    *,
    technical_ok: bool,
    technical_notes: Optional[list[str]] = None,
    text_notes: Optional[list[str]] = None,
    visual_review: Optional[dict] = None,
    media_hash: str = "",
    next_first_diff: Optional[float] = None,
    setup_changed: bool = False,
    vlm_score: Optional[float] = None,
) -> dict[str, dict[str, Any]]:
    layers = empty_layers()
    layers["technical"]["status"] = "pass" if technical_ok else "fail"
    for note in technical_notes or []:
        _note(layers["technical"], note)

    if text_notes:
        layers["text"]["status"] = "warn"
        for note in text_notes:
            _note(layers["text"], note)
            _note(layers["text"], "text check is not a visual pass")
    else:
        layers["text"]["status"] = "pass"

    review = visual_review if isinstance(visual_review, dict) else {}
    bound = str(review.get("image_sha256") or review.get("media_hash") or "").strip()
    verdict = str(review.get("status") or review.get("visual") or "").strip()
    if verdict == "pass" and bound and media_hash and bound == media_hash:
        layers["visual"]["status"] = "pass"
        _note(layers["visual"], "visual pass bound to media hash")
    elif verdict == "fail":
        layers["visual"]["status"] = "fail"
        _note(layers["visual"], "visual review failed")
    else:
        layers["visual"]["status"] = "unknown"
        if verdict == "pass" and (not bound or bound != media_hash):
            _note(layers["visual"], "visual review not bound to this media hash")
        else:
            _note(layers["visual"], "visual layer requires a hash-bound review; text pass is not enough")

    layers["performance"]["status"] = "unknown"
    _note(layers["performance"], "performance is not inferred from prompt text")

    if setup_changed:
        layers["scene_cut"]["status"] = "skip"
        _note(layers["scene_cut"], "camera setup changed; last-to-next pixel diff is not continuity proof")
    elif next_first_diff is not None and next_first_diff > 0.35:
        layers["scene_cut"]["status"] = "warn"
        _note(layers["scene_cut"], f"last vs next-first differs {next_first_diff:.2f} (crude)")
    else:
        layers["scene_cut"]["status"] = "pass"

    if vlm_score is not None:
        _note(layers["visual"], f"VLM score {vlm_score} is evidence, not an automatic pass")
        if layers["visual"]["status"] == "pass" and not (bound and bound == media_hash):
            layers["visual"]["status"] = "unknown"

    return layers


def layers_allow_auto_pass(layers: dict[str, dict[str, Any]]) -> bool:
    """Paid finish still needs a hash-bound visual review. Technical+text is not enough."""
    visual = (layers.get("visual") or {}).get("status")
    return visual == "pass"
