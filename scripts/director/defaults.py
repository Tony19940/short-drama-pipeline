"""Production defaults. Old shows keep their locked aspect in confirm / shots.json."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ASPECT = "16:9"
ASPECTS = ("16:9", "9:16")

# Paper pace (shot-split-proposal). Render still uses the model floor (usually 4s).
PACE_SPM_MIN = 14
PACE_SPM_MAX = 18
PACE_SPM_WORK = 16
PACE_SPM_WARN_BELOW = 12
PACE_ASL_MIN = 3.3
PACE_ASL_MAX = 4.3
PAPER_REACTION = (1.2, 2.0)
PAPER_INSERT = (1.5, 2.5)
PAPER_DIALOGUE = (2.5, 4.5)
PAPER_ESTABLISH = (3.0, 5.0)
PAPER_LONG = (5.0, 8.0)
PAPER_LONG_CAP = 8.0
PAPER_HARD_FAIL_SEC = 12.0
LONG_TAKE_REASON = "信息在连续时间里"


def frame_label(aspect: str) -> str:
    return "Widescreen 16:9" if aspect == "16:9" else "Vertical 9:16"


def production_aspect(prod: Path | None = None, explicit: str | None = None) -> str:
    if explicit in ASPECTS:
        return explicit
    if prod is not None:
        shots = prod / "03-storyboard" / "shots.json"
        if shots.exists():
            try:
                data = json.loads(shots.read_text(encoding="utf-8"))
                aspect = str(data.get("aspect") or "")
                if aspect in ASPECTS:
                    return aspect
            except (OSError, json.JSONDecodeError):
                pass
        confirm = prod / "01-bible" / "confirm.md"
        if confirm.exists():
            try:
                text = confirm.read_text(encoding="utf-8")
            except OSError:
                text = ""
            for line in text.splitlines():
                if "画幅" in line:
                    if "16:9" in line:
                        return "16:9"
                    if "9:16" in line:
                        return "9:16"
            if "16:9" in text and "9:16" not in text:
                return "16:9"
            if "9:16" in text and "16:9" not in text:
                return "9:16"
    return DEFAULT_ASPECT
