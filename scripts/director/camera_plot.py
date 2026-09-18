"""Camera-plot geometry: turn `sets.json` marks and cameras into left/right facts.

`sets[]` entries already carry `marks[]` `{id, x, y, note}` (0–1, image coordinates:
x to the right, y downward, painted onto blocking.jpg). This module adds `cameras[]`
`{id, x, y, facing_deg, lens, label}` in the same coordinate space.

`facing_deg` is a compass heading on the top-down plot: 0 = up (toward the back of
the set), 90 = right, 180 = down (toward the viewer of blocking.jpg), 270 = left.

From that the machine can say, without a model call, which mark lands on screen-left,
which way an eyeline reads, and whether two cameras straddle the axis between two
marks (the 180° rule). The shot table hooks in when a shot names a `camera_id`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

CAMERA_MARK_PREFIXES = ("camera", "cam")
EMPTY_TOKENS = ("", "空", "—", "-", "无")
SENSOR_WIDTH_MM = 36.0


def _t(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _xy(item: dict) -> tuple[float, float]:
    return _num(item.get("x"), 0.5), _num(item.get("y"), 0.5)


def normalize_camera(camera: Any) -> dict:
    item = dict(camera) if isinstance(camera, dict) else {}
    facing = item.get("facing_deg")
    return {
        "id": _t(item.get("id")),
        "x": _num(item.get("x"), 0.5),
        "y": _num(item.get("y"), 0.9),
        "facing_deg": None if facing in (None, "") else _num(facing) % 360.0,
        "lens": _t(item.get("lens")),
        "label": _t(item.get("label")),
    }


def set_cameras(set_entry: dict) -> list[dict]:
    return [normalize_camera(c) for c in (set_entry or {}).get("cameras") or [] if isinstance(c, dict) and _t(c.get("id"))]


def is_camera_mark(mark: dict) -> bool:
    """Legacy sets put the camera in `marks[]` as `camera` / `cam1`; those are not subjects."""
    mid = _t(mark.get("id")).lower()
    return any(mid == p or mid.startswith(p) and not mid[len(p):len(p) + 1].isalpha() for p in CAMERA_MARK_PREFIXES)


def subject_marks(set_entry: dict) -> list[dict]:
    """Marks that stand for people / things, not the legacy `camera` mark."""
    return [m for m in (set_entry or {}).get("marks") or [] if isinstance(m, dict) and _t(m.get("id")) and not is_camera_mark(m)]


def facing_vector(camera: dict, toward: Optional[tuple[float, float]] = None) -> tuple[float, float]:
    """Unit vector the camera looks along. Without `facing_deg` it looks at `toward` (or up)."""
    cx, cy = _xy(camera)
    deg = camera.get("facing_deg")
    if deg is None and toward is not None:
        dx, dy = toward[0] - cx, toward[1] - cy
        length = math.hypot(dx, dy)
        if length > 1e-9:
            return dx / length, dy / length
        return 0.0, -1.0
    rad = math.radians(_num(deg, 0.0))
    return math.sin(rad), -math.cos(rad)


def right_vector(facing: tuple[float, float]) -> tuple[float, float]:
    """Screen-right for a camera looking along `facing` (image coords, y down)."""
    fx, fy = facing
    return -fy, fx


def screen_x(camera: dict, mark: dict, facing: Optional[tuple[float, float]] = None) -> float:
    """Signed lateral offset of a mark as the camera sees it: <0 left of centre, >0 right."""
    cx, cy = _xy(camera)
    mx, my = _xy(mark)
    f = facing or facing_vector(camera, (mx, my))
    rx, ry = right_vector(f)
    return (mx - cx) * rx + (my - cy) * ry


def depth(camera: dict, mark: dict, facing: Optional[tuple[float, float]] = None) -> float:
    """Distance along the lens axis; <=0 means the mark sits behind the camera."""
    cx, cy = _xy(camera)
    mx, my = _xy(mark)
    f = facing or facing_vector(camera, (mx, my))
    return (mx - cx) * f[0] + (my - cy) * f[1]


def _facing_for_pair(camera: dict, mark_a: dict, mark_b: dict) -> tuple[float, float]:
    ax, ay = _xy(mark_a)
    bx, by = _xy(mark_b)
    return facing_vector(camera, ((ax + bx) / 2, (ay + by) / 2))


def screen_side(camera: dict, mark_a: dict, mark_b: dict) -> str:
    """Where `mark_a` lands relative to `mark_b` in this camera's frame: "left" or "right".

    Cross product of the two mark vectors seen from the camera; the camera's facing only
    decides which way is "right" when both marks sit in front of it.
    """
    camera = normalize_camera(camera)
    facing = _facing_for_pair(camera, mark_a, mark_b)
    xa = screen_x(camera, mark_a, facing)
    xb = screen_x(camera, mark_b, facing)
    if abs(xa - xb) < 1e-9:
        cx, cy = _xy(camera)
        ax, ay = _xy(mark_a)
        bx, by = _xy(mark_b)
        cross = (ax - cx) * (by - cy) - (ay - cy) * (bx - cx)
        return "left" if cross > 0 else "right"
    return "left" if xa < xb else "right"


def eyeline_direction(camera: dict, from_mark: dict, to_mark: dict) -> str:
    """How a look from `from_mark` to `to_mark` reads on screen: 画左 / 画右 / 朝镜头 / 背镜头."""
    camera = normalize_camera(camera)
    facing = facing_vector(camera, _xy(from_mark))
    rx, ry = right_vector(facing)
    fx, fy = _xy(from_mark)
    tx, ty = _xy(to_mark)
    gx, gy = tx - fx, ty - fy
    lateral = gx * rx + gy * ry
    toward = gx * facing[0] + gy * facing[1]
    if abs(lateral) >= abs(toward):
        return "画右" if lateral > 0 else "画左"
    return "背镜头" if toward > 0 else "朝镜头"


def axis_check(cameras: list[dict], mark_a: dict, mark_b: dict) -> list[str]:
    """180° rule: every camera must sit on the same side of the line A–B. Returns problems."""
    problems: list[str] = []
    ax, ay = _xy(mark_a)
    bx, by = _xy(mark_b)
    label = f"{_t(mark_a.get('id'))}–{_t(mark_b.get('id'))}"
    if abs(ax - bx) < 1e-9 and abs(ay - by) < 1e-9:
        return [f"axis {label}: the two marks share one point; no axis"]
    sides: dict[str, int] = {}
    for raw in cameras:
        cam = normalize_camera(raw)
        cx, cy = _xy(cam)
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) < 1e-6:
            problems.append(f"camera {cam['id']} sits on the axis {label}; it cannot tell left from right")
            continue
        sides[cam["id"]] = 1 if cross > 0 else -1
    if sides and len(set(sides.values())) > 1:
        majority = 1 if sum(1 for s in sides.values() if s > 0) >= sum(1 for s in sides.values() if s < 0) else -1
        crossing = [cid for cid, side in sides.items() if side != majority]
        problems.append(
            f"cameras {', '.join(crossing)} cross the axis {label}: they sit on the other side from {', '.join(c for c, s in sides.items() if s == majority)}"
        )
    return problems


def mark_matches(mark: dict, token: str) -> bool:
    """Does a designed left/right/eyeline token name this mark? id, label, name or note."""
    token = _t(token)
    if not token or token in EMPTY_TOKENS:
        return False
    for key in ("id", "label", "name"):
        value = _t(mark.get(key))
        if value and (value == token or value.lower() == token.lower()):
            return True
    for key in ("label", "name", "note"):
        value = _t(mark.get(key))
        if value and (token in value or value in token):
            return True
    for alias in mark.get("aliases") or []:
        if _t(alias) and (_t(alias) == token or _t(alias) in token or token in _t(alias)):
            return True
    return False


def find_mark(set_entry: dict, token: str) -> Optional[dict]:
    for mark in subject_marks(set_entry):
        if mark_matches(mark, token):
            return mark
    return None


def find_camera(set_entry: dict, camera_id: str) -> Optional[dict]:
    for cam in set_cameras(set_entry):
        if cam["id"] == _t(camera_id):
            return cam
    return None


def _mark_label(mark: dict) -> str:
    return _t(mark.get("label") or mark.get("name") or mark.get("id"))


def axis_marks(set_entry: dict) -> tuple[Optional[dict], Optional[dict]]:
    """The two marks that define the scene axis: `axis_marks: [a, b]` or the first two subject marks."""
    marks = subject_marks(set_entry)
    wanted = [_t(x) for x in (set_entry or {}).get("axis_marks") or [] if _t(x)]
    if len(wanted) >= 2:
        a = next((m for m in marks if _t(m.get("id")) == wanted[0]), None)
        b = next((m for m in marks if _t(m.get("id")) == wanted[1]), None)
        if a is not None and b is not None:
            return a, b
    if len(marks) >= 2:
        return marks[0], marks[1]
    return None, None


def suggest_sides(set_entry: dict, shot: dict) -> dict:
    """What the geometry says this shot's left / right / eyeline should be.

    Matches the shot's own tokens to marks first; when it cannot, orders every subject mark by
    screen position. Empty dict when the shot names no camera or the camera is unknown.
    """
    camera_id = _t((shot or {}).get("camera_id"))
    if not camera_id:
        return {}
    camera = find_camera(set_entry, camera_id)
    if camera is None:
        return {"camera": camera_id, "unknown_camera": True}
    marks = subject_marks(set_entry)
    if not marks:
        return {"camera": camera_id, "left": "", "right": "", "eyeline": "", "order": []}
    centre = (sum(_xy(m)[0] for m in marks) / len(marks), sum(_xy(m)[1] for m in marks) / len(marks))
    facing = facing_vector(camera, centre)
    ordered = sorted(marks, key=lambda m: screen_x(camera, m, facing))
    in_front = [m for m in ordered if depth(camera, m, facing) > 0]
    order = [{"id": _t(m.get("id")), "label": _mark_label(m), "screen_x": round(screen_x(camera, m, facing), 3)} for m in ordered]
    left_mark = find_mark(set_entry, _t(shot.get("left")))
    right_mark = find_mark(set_entry, _t(shot.get("right")))
    out: dict[str, Any] = {"camera": camera_id, "order": order, "behind": [_t(m.get("id")) for m in ordered if m not in in_front]}
    if left_mark is not None and right_mark is not None and left_mark is not right_mark:
        side = screen_side(camera, left_mark, right_mark)
        out["left"] = _mark_label(left_mark if side == "left" else right_mark)
        out["right"] = _mark_label(right_mark if side == "left" else left_mark)
        out["matches_design"] = side == "left"
    elif len(in_front) >= 2:
        out["left"] = _mark_label(in_front[0])
        out["right"] = _mark_label(in_front[-1])
    elif len(ordered) >= 2:
        out["left"] = _mark_label(ordered[0])
        out["right"] = _mark_label(ordered[-1])
    else:
        out["left"] = _mark_label(ordered[0])
        out["right"] = ""
    looker = left_mark or (in_front[0] if in_front else ordered[0])
    target = None
    eyeline_text = _t(shot.get("eyeline"))
    if eyeline_text:
        target = next((m for m in marks if m is not looker and mark_matches(m, eyeline_text)), None)
    if target is None and right_mark is not None and right_mark is not looker:
        target = right_mark
    if target is None:
        target = next((m for m in ordered if m is not looker), None)
    out["eyeline"] = eyeline_direction(camera, looker, target) if target is not None else ""
    out["eyeline_from"] = _mark_label(looker)
    out["eyeline_to"] = _mark_label(target) if target is not None else ""
    return out


def side_disagreements(set_entry: dict, shot: dict) -> list[str]:
    """Warnings when a shot's designed left/right contradict the camera geometry."""
    suggestion = suggest_sides(set_entry, shot)
    if not suggestion or suggestion.get("unknown_camera"):
        return []
    if suggestion.get("matches_design") is False:
        sid = _t(shot.get("shot_id"))
        return [
            f"{sid} designed left={_t(shot.get('left'))} right={_t(shot.get('right'))}, but camera {suggestion['camera']} sees "
            f"{suggestion.get('left')} on the left and {suggestion.get('right')} on the right; move the camera or swap the sides"
        ]
    return []


def set_report(set_entry: dict) -> dict:
    """Everything the studio shows for one set: cameras, marks, axis problems, per-camera view."""
    cameras = set_cameras(set_entry)
    marks = subject_marks(set_entry)
    a, b = axis_marks(set_entry)
    problems = axis_check(cameras, a, b) if (a is not None and b is not None and cameras) else []
    views = []
    for cam in cameras:
        if marks:
            centre = (sum(_xy(m)[0] for m in marks) / len(marks), sum(_xy(m)[1] for m in marks) / len(marks))
            facing = facing_vector(cam, centre)
            ordered = sorted(marks, key=lambda m: screen_x(cam, m, facing))
            views.append({
                "camera": cam["id"],
                "lens": cam["lens"],
                "left_to_right": [_mark_label(m) for m in ordered if depth(cam, m, facing) > 0],
                "behind": [_mark_label(m) for m in ordered if depth(cam, m, facing) <= 0],
                "eyeline_a_to_b": eyeline_direction(cam, a, b) if a is not None and b is not None else "",
            })
        else:
            views.append({"camera": cam["id"], "lens": cam["lens"], "left_to_right": [], "behind": [], "eyeline_a_to_b": ""})
    return {
        "id": _t(set_entry.get("id")),
        "name": _t(set_entry.get("name")),
        "marks": [{"id": _t(m.get("id")), "label": _mark_label(m), "x": _xy(m)[0], "y": _xy(m)[1]} for m in marks],
        "cameras": cameras,
        "axis": [_t(a.get("id")), _t(b.get("id"))] if a is not None and b is not None else [],
        "axis_problems": problems,
        "views": views,
    }


# --- rendering -------------------------------------------------------------------

PLOT_W, PLOT_H = 1200, 800
MARGIN = 60
INK = (243, 241, 234)
DIM = (154, 149, 136)
BG = (12, 12, 12)
GRID = (34, 34, 34)
MARK_COLORS = [(212, 164, 74), (80, 170, 220), (220, 90, 90), (120, 200, 120), (200, 120, 220)]
CAMERA_COLOR = (212, 51, 110)
AXIS_COLOR = (212, 164, 74)


def _font(size: int):
    from .animatic import find_font

    return find_font(size)


def _to_px(x: float, y: float) -> tuple[float, float]:
    return MARGIN + x * (PLOT_W - 2 * MARGIN), MARGIN + y * (PLOT_H - 2 * MARGIN)


def _dashed(draw, p0: tuple[float, float], p1: tuple[float, float], fill, dash: int = 12, width: int = 3) -> None:
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1e-6:
        return
    steps = int(length // dash)
    for i in range(0, steps + 1, 2):
        s = i * dash / length
        e = min((i + 1) * dash / length, 1.0)
        draw.line((x0 + (x1 - x0) * s, y0 + (y1 - y0) * s, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e), fill=fill, width=width)


def lens_fov_deg(lens: str) -> float:
    mm = _num(_t(lens).lower().replace("mm", ""), 0.0)
    if mm <= 0:
        return 50.0
    return math.degrees(2 * math.atan(SENSOR_WIDTH_MM / (2 * mm)))


def render_plot(set_entry: dict, out_path: Path) -> Path:
    """Top-down PNG: marks as dots, cameras as wedges (facing + lens), axis A–B dashed."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (PLOT_W, PLOT_H), BG)
    draw = ImageDraw.Draw(img)
    for i in range(0, 11):
        x = MARGIN + i * (PLOT_W - 2 * MARGIN) / 10
        y = MARGIN + i * (PLOT_H - 2 * MARGIN) / 10
        draw.line((x, MARGIN, x, PLOT_H - MARGIN), fill=GRID, width=1)
        draw.line((MARGIN, y, PLOT_W - MARGIN, y), fill=GRID, width=1)
    draw.rectangle((MARGIN, MARGIN, PLOT_W - MARGIN, PLOT_H - MARGIN), outline=(58, 58, 58), width=2)
    title = _font(30)
    small = _font(20)
    draw.text((MARGIN, 14), f"CAMERA PLOT  {_t(set_entry.get('id'))}  {_t(set_entry.get('name'))}".strip(), font=title, fill=INK)
    draw.text((MARGIN, PLOT_H - MARGIN + 14), "top-down · y down = toward the viewer of blocking.jpg · facing 0=up 90=right", font=small, fill=DIM)

    marks = subject_marks(set_entry)
    a, b = axis_marks(set_entry)
    if a is not None and b is not None:
        _dashed(draw, _to_px(*_xy(a)), _to_px(*_xy(b)), AXIS_COLOR)
        ax, ay = _to_px(*_xy(a))
        bx, by = _to_px(*_xy(b))
        draw.text(((ax + bx) / 2 + 8, (ay + by) / 2 - 26), "axis", font=small, fill=AXIS_COLOR)

    cameras = set_cameras(set_entry)
    centre = (sum(_xy(m)[0] for m in marks) / len(marks), sum(_xy(m)[1] for m in marks) / len(marks)) if marks else (0.5, 0.5)
    for cam in cameras:
        cx, cy = _to_px(cam["x"], cam["y"])
        facing = facing_vector(cam, centre)
        heading = math.degrees(math.atan2(facing[0], -facing[1]))
        half = lens_fov_deg(cam["lens"]) / 2
        reach = 0.28 * (PLOT_H - 2 * MARGIN)
        pts = [(cx, cy)]
        for deg in (heading - half, heading, heading + half):
            rad = math.radians(deg)
            pts.append((cx + math.sin(rad) * reach, cy - math.cos(rad) * reach))
        wedge = [pts[0], pts[1], pts[2], pts[3]]
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.polygon(wedge, fill=CAMERA_COLOR + (60,), outline=CAMERA_COLOR + (200,))
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
        draw = ImageDraw.Draw(img)
        draw.line((cx, cy, pts[2][0], pts[2][1]), fill=CAMERA_COLOR, width=2)
        r = 10
        draw.rectangle((cx - r, cy - r, cx + r, cy + r), fill=CAMERA_COLOR, outline=INK, width=2)
        label = " ".join(x for x in (cam["id"], cam["lens"], cam["label"]) if x)
        draw.text((cx + r + 6, cy - 10), label, font=small, fill=INK)

    for i, mark in enumerate(marks):
        mx, my = _to_px(*_xy(mark))
        color = MARK_COLORS[i % len(MARK_COLORS)]
        r = 13
        draw.ellipse((mx - r, my - r, mx + r, my + r), fill=color, outline=INK, width=3)
        note = _t(mark.get("note"))
        text = _mark_label(mark) + (f"  {note}" if note and note != _mark_label(mark) else "")
        draw.text((mx + r + 6, my - 12), text, font=small, fill=INK)

    problems = axis_check(cameras, a, b) if (a is not None and b is not None and cameras) else []
    y = MARGIN + 8
    for line in problems[:4]:
        draw.text((MARGIN + 8, y), "! " + line, font=small, fill=(255, 91, 110))
        y += 26
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def plot_rel(set_id: str) -> str:
    return f"02-assets/scenes/{set_id}/camera-plot.png"


def render_all(prod: Path, sets: Optional[dict] = None) -> dict:
    """One PNG per set that has marks or cameras. Returns what was written and the axis report."""
    from .production import load_json

    data = sets if sets is not None else load_json(prod, "03-storyboard/sets.json", {"sets": []})
    written = []
    reports = []
    for entry in data.get("sets") or []:
        if not isinstance(entry, dict) or not _t(entry.get("id")):
            continue
        if not (subject_marks(entry) or set_cameras(entry)):
            continue
        rel = plot_rel(_t(entry.get("id")))
        render_plot(entry, prod / rel)
        written.append(rel)
        reports.append(set_report(entry))
    return {"ok": True, "written": written, "sets": reports}


def snapshot_camera_plot(prod: Path) -> dict:
    from .paths import media_url
    from .production import load_json

    data = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    out = []
    for entry in data.get("sets") or []:
        if not isinstance(entry, dict) or not _t(entry.get("id")):
            continue
        report = set_report(entry)
        report["plot_url"] = media_url(prod, plot_rel(report["id"]))
        out.append(report)
    return {"sets": out}
