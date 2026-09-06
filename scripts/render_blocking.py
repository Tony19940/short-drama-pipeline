#!/usr/bin/env python3
"""Paint set marks onto scene masters → blocking.jpg (local canvas)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
COLORS = [
    (212, 164, 74, 230),
    (80, 170, 220, 230),
    (220, 90, 90, 230),
    (120, 200, 120, 230),
    (200, 120, 220, 230),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def paint(master: Path, marks: list[dict], dest: Path) -> None:
    img = Image.open(master).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    title = font(max(28, w // 28))
    label_f = font(max(22, w // 36))
    draw.rectangle((0, 0, w, int(h * 0.08)), fill=(0, 0, 0, 140))
    draw.text((int(w * 0.04), int(h * 0.018)), "STAGE  " + dest.parent.name, font=title, fill=(244, 213, 141, 255))
    for i, m in enumerate(marks):
        x = float(m["x"]) * w
        y = float(m["y"]) * h
        color = COLORS[i % len(COLORS)]
        r = max(14, w // 40)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=(255, 255, 255, 255), width=3)
        name = str(m.get("id") or m.get("note") or i)
        note = str(m.get("note") or "")
        text = name if not note else f"{name}  {note}"
        bbox = draw.textbbox((0, 0), text, font=label_f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = min(max(12, x + r + 8), w - tw - 16)
        ty = min(max(int(h * 0.09), y - th // 2), h - th - 16)
        draw.rounded_rectangle((tx - 8, ty - 6, tx + tw + 8, ty + th + 6), radius=8, fill=(0, 0, 0, 170))
        draw.text((tx, ty), text, font=label_f, fill=(255, 255, 255, 255))
    out = Image.alpha_composite(img, overlay).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, quality=92)
    print(f"wrote {dest}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    args = p.parse_args()
    prod = Path(args.prod).resolve()
    data = json.loads((prod / "03-storyboard" / "sets.json").read_text())
    for st in data.get("sets") or []:
        master = prod / st["master"]
        dest = prod / st["blocking"]
        if not master.exists():
            raise SystemExit(f"missing master {master}")
        paint(master, st.get("marks") or [], dest)


if __name__ == "__main__":
    main()
