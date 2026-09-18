#!/usr/bin/env python3
"""Blank-plate + real Khmer font overlay previews (010-gongpai P1/P2/S1/S2).

Uses existing GPT-quality plates (master-v3.jpg if present, else master.jpg).
Covers old glyph regions, then stamps Core Text–shaped Khmer. Writes only to
02-assets/_khmer-overlay/. Does not touch official master.jpg slots.

    python3 scripts/overlay_khmer_preview.py --prod productions/010-gongpai
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SCRIPTS = Path(__file__).resolve().parent
SWIFT_SRC = SCRIPTS / "khmer_coretext.swift"
ROOT = SCRIPTS.parent

FONT_KHMER = "KhmerSangamMN"
FONT_KHMER_BOLD = "KhmerMN-Bold"
FONT_LATIN = "HelveticaNeue-Medium"
FONT_LATIN_SERIF = "TimesNewRomanPS-BoldMT"

# Full forms from productions/010-gongpai/02-assets/KHMER-TEXT.md — no synonym swaps.
T_FACTORY = "រោងចក្រកាត់ដេរ បុរី"
T_LATIN_CO = "Borey Garment Co., Ltd."
T_SECURITY = "សន្តិសុខ"
T_STAFF_INFO = "ព័ត៌មានសម្រាប់បុគ្គលិក"
T_SAFETY = "សុវត្ថិភាព"
T_DISCIPLINE = "វិន័យ"
T_QUALITY = "គុណភាព"
T_GOOD_WORK = "ការងារល្អ"
T_GOOD_LIFE = "ជីវិតល្អ"
T_WASTE = "សំរាម"
T_EMPLOYEE = "បុគ្គលិករោងចក្រ"
T_NAME = "ឈ្មោះ៖ បុប្ផា"
T_NAME_LATIN = "Bopha"
T_TITLE = "មុខតំណែង៖ អគ្គនាយករង"
T_TITLE_LATIN = "Deputy General Manager"
T_ID = "លេខសម្គាល់៖ F-0287"
T_FAMILY = "គ្រួសាររបស់យើង"

GOLD = "E6C15A"
GOLD_DEEP = "C9A046"
NAVY = "1C3A6E"
NEAR_BLACK = "161616"
WHITE = "F4F4F4"
BADGE_INK = "1A1A1A"


def resolve_plate(prod: Path, kind_dir: str, slug: str) -> tuple[Path, str]:
    folder = prod / "02-assets" / kind_dir / slug
    v3 = folder / "master-v3.jpg"
    master = folder / "master.jpg"
    if v3.exists():
        return v3, "master-v3.jpg"
    if not master.exists():
        raise SystemExit(f"missing plate {folder}/master.jpg")
    return master, "master.jpg"


def compile_coretext(bin_path: Path) -> Path:
    if bin_path.exists() and bin_path.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return bin_path
    subprocess.run(
        ["swiftc", "-O", "-o", str(bin_path), str(SWIFT_SRC)],
        check=True,
    )
    return bin_path


def render_lines(coretext: Path, jobs: list[dict], cache: Path) -> dict[str, Image.Image]:
    cache.mkdir(parents=True, exist_ok=True)
    batch = []
    paths = {}
    for i, job in enumerate(jobs):
        out = cache / f"{i:03d}.png"
        paths[job["key"]] = out
        batch.append(
            {
                "text": job["text"],
                "font": job.get("font", FONT_KHMER),
                "size": job.get("size", 64),
                "color": job.get("color", "000000"),
                "out": str(out),
            }
        )
    batch_path = cache / "jobs.json"
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    subprocess.run([str(coretext), "--batch", str(batch_path)], check=True)
    return {k: trim_alpha(Image.open(p).convert("RGBA")) for k, p in paths.items()}


def trim_alpha(im: Image.Image, pad: int = 4) -> Image.Image:
    bbox = im.split()[3].getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.size[0], x1 + pad)
    y1 = min(im.size[1], y1 + pad)
    return im.crop((x0, y0, x1, y1))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[piv] = m[piv], m[i]
        if abs(m[i][i]) < 1e-12:
            raise ValueError("singular homography")
        div = m[i][i]
        for c in range(i, n + 1):
            m[i][c] /= div
        for r in range(n):
            if r == i:
                continue
            factor = m[r][i]
            for c in range(i, n + 1):
                m[r][c] -= factor * m[i][c]
    return [m[i][n] for i in range(n)]


def perspective_coeffs(src, dst):
    matrix = []
    rhs = []
    for (u, v), (x, y) in zip(src, dst):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    return _solve(matrix, rhs)


def paste_on_quad(base: Image.Image, overlay: Image.Image, quad, opacity: float = 1.0) -> None:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, y0 = int(min(xs)), int(min(ys))
    x1, y1 = int(max(xs)) + 1, int(max(ys)) + 1
    local = [(p[0] - x0, p[1] - y0) for p in quad]
    ow, oh = overlay.size
    src_q = [(0, 0), (ow - 1, 0), (ow - 1, oh - 1), (0, oh - 1)]
    coeffs = perspective_coeffs(src_q, local)
    warped = overlay.transform((x1 - x0, y1 - y0), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    if opacity < 1:
        r, g, b, a = warped.split()
        a = a.point(lambda v: int(v * opacity))
        warped = Image.merge("RGBA", (r, g, b, a))
    base.paste(warped, (x0, y0), warped)


def paste_fit(base: Image.Image, overlay: Image.Image, box, align: str = "center") -> None:
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    ow, oh = overlay.size
    scale = min(bw / ow, bh / oh)
    nw, nh = max(1, int(ow * scale)), max(1, int(oh * scale))
    resized = overlay.resize((nw, nh), Image.Resampling.LANCZOS)
    if align == "center":
        x = x0 + (bw - nw) // 2
        y = y0 + (bh - nh) // 2
    elif align == "top":
        x = x0 + (bw - nw) // 2
        y = y0
    else:
        x, y = x0, y0
    base.paste(resized, (x, y), resized)


def stack_lines(images: list[Image.Image], gap: int = 8) -> Image.Image:
    widths = [im.size[0] for im in images]
    heights = [im.size[1] for im in images]
    w = max(widths)
    h = sum(heights) + gap * (len(images) - 1)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for im in images:
        canvas.paste(im, ((w - im.size[0]) // 2, y), im)
        y += im.size[1] + gap
    return canvas


def recolor(im: Image.Image, rgba: tuple[int, int, int, int]) -> Image.Image:
    r, g, b, a = rgba
    alpha = im.split()[3]
    solid = Image.new("RGBA", im.size, (r, g, b, 255))
    solid.putalpha(alpha.point(lambda v: int(v * a / 255)))
    return solid


def with_shadow(im: Image.Image, dx: int = 2, dy: int = 3, shadow=(55, 38, 12, 170)) -> Image.Image:
    sh = recolor(im, shadow)
    w, h = im.size
    canvas = Image.new("RGBA", (w + abs(dx) + 6, h + abs(dy) + 6), (0, 0, 0, 0))
    canvas.paste(sh, (3 + dx, 3 + dy), sh)
    canvas.paste(im, (3, 3), im)
    return canvas


def luma(p) -> float:
    return 0.3 * p[0] + 0.59 * p[1] + 0.11 * p[2]


def median_rgb(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not colors:
        return (128, 128, 128)
    rs, gs, bs = zip(*colors)
    mid = len(colors) // 2
    return (
        sorted(rs)[mid],
        sorted(gs)[mid],
        sorted(bs)[mid],
    )


def sample_ring(im: Image.Image, box, band: int = 8) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    w, h = im.size
    pix = im.load()
    colors = []
    for y in range(max(0, y0 - band), min(h, y1 + band)):
        for x in range(max(0, x0 - band), min(w, x1 + band)):
            if x0 <= x < x1 and y0 <= y < y1:
                continue
            colors.append(pix[x, y][:3])
    return median_rgb(colors)


def fill_box(im: Image.Image, box, color, feather: int = 0) -> None:
    draw = ImageDraw.Draw(im)
    draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=color)
    if feather:
        crop = im.crop(box).filter(ImageFilter.GaussianBlur(feather))
        im.paste(crop, (box[0], box[1]))


def fill_matched(
    im: Image.Image,
    box,
    ink_pred=None,
    grain: int = 5,
    sample: str = "ring",
    skip_pred=None,
    feather: float = 0.0,
    sample_box=None,
) -> None:
    """Paint a uniform plaque/strip with sampled plate color + light grain.

    sample=ring uses pixels just outside the box so leftover ink cannot tint the fill.
    skip_pred pixels (e.g. hair) are left untouched.
    """
    x0, y0, x1, y1 = box
    w, h = im.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    pix = im.load()
    if sample_box is not None:
        sx0, sy0, sx1, sy1 = sample_box
        samples = [pix[x, y][:3] for y in range(sy0, sy1) for x in range(sx0, sx1)]
        color = median_rgb(samples)
    elif sample == "ring":
        color = sample_ring(im, (x0, y0, x1, y1), band=10)
    else:
        samples = []
        for y in range(y0, y1):
            for x in range(x0, x1):
                p = pix[x, y][:3]
                if ink_pred is None or not ink_pred(p):
                    samples.append(p)
        color = median_rgb(samples) if samples else sample_ring(im, box)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if skip_pred and skip_pred(x, y, pix[x, y][:3]):
                continue
            j = ((x * 13 + y * 37) % (grain * 2 + 1)) - grain if grain else 0
            pix[x, y] = (
                max(0, min(255, color[0] + j)),
                max(0, min(255, color[1] + j)),
                max(0, min(255, color[2] + j)),
            )
    if feather > 0:
        crop = im.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(feather))
        im.paste(crop, (x0, y0))


def fill_quad(im: Image.Image, quad, color) -> None:
    draw = ImageDraw.Draw(im)
    draw.polygon(quad, fill=color)


def _grow_mask(mask: list[list[bool]], grow: int) -> list[list[bool]]:
    if grow <= 0:
        return mask
    h = len(mask)
    w = len(mask[0])
    out = [row[:] for row in mask]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            for dy in range(-grow, grow + 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in range(-grow, grow + 1):
                    xx = x + dx
                    if 0 <= xx < w:
                        out[yy][xx] = True
    return out


def nn_inpaint(im: Image.Image, box, pred, grow: int = 2, maxr: int = 14) -> None:
    """Replace ink with the nearest unmasked neighbor (no column streaks)."""
    x0, y0, x1, y1 = box
    w, h = im.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    pix = im.load()
    mw, mh = x1 - x0, y1 - y0
    if mw <= 0 or mh <= 0:
        return
    mask = [[pred(pix[x0 + x, y0 + y][:3]) for x in range(mw)] for y in range(mh)]
    mask = _grow_mask(mask, grow)
    # copy source colors first so we never sample already-filled holes
    src = [[pix[x0 + x, y0 + y][:3] for x in range(mw)] for y in range(mh)]
    for y in range(mh):
        for x in range(mw):
            if not mask[y][x]:
                continue
            found = None
            for r in range(1, maxr + 1):
                for dy in range(-r, r + 1):
                    for dx in range(-r, r + 1):
                        if abs(dx) != r and abs(dy) != r:
                            continue
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < mw and 0 <= yy < mh and not mask[yy][xx]:
                            found = src[yy][xx]
                            break
                        gx, gy = x0 + xx, y0 + yy
                        if not (0 <= xx < mw and 0 <= yy < mh) and 0 <= gx < w and 0 <= gy < h:
                            found = pix[gx, gy][:3]
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                pix[x0 + x, y0 + y] = found


def far_from(bg: tuple[int, int, int], tol: int = 30):
    def pred(p) -> bool:
        return abs(p[0] - bg[0]) > tol or abs(p[1] - bg[1]) > tol or abs(p[2] - bg[2]) > tol

    return pred


def sample_corners(im: Image.Image, box, inset: int = 6) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    pix = im.load()
    pts = [
        (x0 + inset, y0 + inset),
        (x1 - inset - 1, y0 + inset),
        (x0 + inset, y1 - inset - 1),
        (x1 - inset - 1, y1 - inset - 1),
    ]
    cols = [pix[min(max(x, 0), im.size[0] - 1), min(max(y, 0), im.size[1] - 1)][:3] for x, y in pts]
    return median_rgb(cols)


def soften(im: Image.Image, radius: float = 0.45) -> Image.Image:
    if radius <= 0:
        return im
    return im.filter(ImageFilter.GaussianBlur(radius))


def is_gold(p) -> bool:
    r, g, b = p
    return r > 155 and 90 < g < 210 and b < 130 and r - b > 50 and r >= g - 8


def is_navy_ink(p) -> bool:
    r, g, b = p
    return luma(p) < 155 and b > r + 8 and b >= g and b > 55


def is_dark_ink(p, thresh: float = 100) -> bool:
    return luma(p) < thresh and max(p) - min(p) < 90


def is_title_ink(p) -> bool:
    """Cork-board header: near-black or navy painted type."""
    return is_navy_ink(p) or is_dark_ink(p, 95)


def is_whiteish(p) -> bool:
    return p[0] > 175 and p[1] > 175 and p[2] > 175


def is_hair(p) -> bool:
    r, g, b = p
    return luma(p) < 58 and r < 90 and abs(r - g) < 25 and b < r + 15


def blur_box(im: Image.Image, box, radius: float = 1.2) -> None:
    crop = im.crop(box).filter(ImageFilter.GaussianBlur(radius))
    im.paste(crop, (box[0], box[1]))


def save_jpg(im: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    rgb = im.convert("RGB")
    rgb.save(dest, format="JPEG", quality=92, optimize=True)


def factory_gate(im: Image.Image, glyphs: dict[str, Image.Image]) -> None:
    fill_matched(
        im,
        (110, 492, 356, 558),
        grain=4,
        sample="interior",
        ink_pred=is_gold,
        feather=0.4,
    )
    stamp = soften(with_shadow(glyphs["security"], dx=2, dy=3, shadow=(40, 28, 10, 160)), 0.35)
    paste_fit(im, stamp, (118, 496, 348, 554))

    # Dark inner plaque — wide enough to bury leftover បុរី on the right.
    fill_matched(
        im,
        (1208, 322, 1588, 462),
        grain=3,
        sample="interior",
        ink_pred=lambda p: is_gold(p) or luma(p) > 70,
    )
    stacked = stack_lines(
        [
            soften(with_shadow(glyphs["factory_gold"], dx=1, dy=2, shadow=(20, 14, 6, 140)), 0.3),
            soften(glyphs["factory_latin_gold"], 0.25),
        ],
        gap=6,
    )
    paste_on_quad(im, stacked, [(1212, 322), (1570, 330), (1564, 462), (1206, 454)])


def notice_board(im: Image.Image, glyphs: dict[str, Image.Image]) -> None:
    # Blank the cork header (letters are darker than cork; do not inpaint cork as ink).
    fill_matched(
        im,
        (610, 78, 1310, 172),
        grain=5,
        sample_box=(700, 80, 900, 92),
        feather=0.35,
    )
    paste_fit(im, soften(glyphs["staff_info"], 0.3), (640, 86, 1260, 164))

    # Full forms: គុណភាព, not the plate's សាមគ្គី synonym.
    fill_matched(
        im,
        (376, 158, 562, 386),
        grain=4,
        sample="interior",
        ink_pred=lambda p: is_navy_ink(p) or luma(p) < 80,
        feather=0.4,
    )
    stacked = stack_lines([glyphs["safety"], glyphs["discipline"], glyphs["quality"]], gap=22)
    paste_fit(im, soften(stacked, 0.3), (382, 168, 552, 372))

    fill_matched(
        im,
        (1386, 104, 1604, 234),
        grain=3,
        sample="interior",
        ink_pred=is_navy_ink,
        feather=0.35,
    )
    stacked = stack_lines([glyphs["good_work"], glyphs["good_life"]], gap=12)
    paste_fit(im, soften(stacked, 0.3), (1394, 112, 1594, 222))

    fill_matched(
        im,
        (390, 730, 524, 802),
        grain=3,
        sample="interior",
        ink_pred=is_whiteish,
        feather=0.3,
    )
    paste_fit(im, soften(glyphs["waste"], 0.35), (400, 736, 514, 796))


def _badge_panel(glyphs: dict[str, Image.Image]) -> Image.Image:
    """Typeset the white-card block as graphic design (not a sticker over junk type)."""
    rows = [
        glyphs["employee"],
        stack_lines([glyphs["name"], glyphs["name_latin"]], gap=2),
        stack_lines([glyphs["title"], glyphs["title_latin"]], gap=2),
        glyphs["ident"],
    ]
    widths = [im.size[0] for im in rows]
    w = max(widths) + 24
    heights = [im.size[1] for im in rows]
    gaps = [18, 22, 22]
    h = sum(heights) + sum(gaps) + 16
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 8
    for i, im in enumerate(rows):
        panel.paste(im, ((w - im.size[0]) // 2, y), im)
        y += im.size[1] + (gaps[i] if i < len(gaps) else 0)
    return soften(panel, 0.25)


def bopha_badge(im: Image.Image, glyphs: dict[str, Image.Image]) -> None:
    # Rebuild the white-card type block; keep clip / portrait / barcode / industrial plate.
    fill_matched(
        im,
        (698, 322, 1192, 738),
        grain=3,
        sample="interior",
        ink_pred=lambda p: luma(p) < 95,
        feather=0.4,
    )
    panel = _badge_panel(glyphs)
    paste_on_quad(im, panel, [(702, 328), (1182, 352), (1168, 742), (688, 712)])


def group_photo(im: Image.Image, glyphs: dict[str, Image.Image]) -> None:
    # Cover Latin descenders; stop short of hair on the right.
    # Do not treat black type as hair — only skip dark pixels at the hairline.
    fill_matched(
        im,
        (330, 110, 1000, 234),
        grain=3,
        sample="interior",
        ink_pred=lambda p: luma(p) < 150,
    )
    fill_matched(
        im,
        (1000, 110, 1124, 224),
        grain=3,
        sample="interior",
        ink_pred=lambda p: luma(p) < 150,
        skip_pred=lambda x, y, p: y > 218 and is_hair(p),
    )
    stacked = stack_lines([glyphs["factory_dark"], glyphs["factory_latin_dark"]], gap=4)
    paste_fit(im, soften(stacked, 0.3), (350, 116, 1100, 216))

    # Frame plaque — full form គ្រួសាររបស់យើង, not the shortened plate.
    fill_matched(
        im,
        (500, 956, 950, 1036),
        grain=2,
        sample="interior",
        ink_pred=lambda p: luma(p) < 140,
    )
    stacked = stack_lines([glyphs["family"], glyphs["factory_latin_dark"]], gap=2)
    paste_fit(im, soften(stacked, 0.25), (508, 960, 942, 1032))

    fill_matched(
        im,
        (1188, 308, 1342, 442),
        grain=3,
        sample="interior",
        ink_pred=lambda p: luma(p) < 140,
        feather=0.5,
    )
    paste_fit(im, soften(glyphs["quality_soft"], 0.55), (1200, 322, 1308, 408))


def glyph_jobs() -> list[dict]:
    return [
        {"key": "factory_gold", "text": T_FACTORY, "font": FONT_KHMER_BOLD, "size": 72, "color": GOLD},
        {"key": "factory_latin_gold", "text": T_LATIN_CO, "font": FONT_LATIN_SERIF, "size": 28, "color": GOLD},
        {"key": "security", "text": T_SECURITY, "font": FONT_KHMER_BOLD, "size": 70, "color": GOLD},
        {"key": "staff_info", "text": T_STAFF_INFO, "font": FONT_KHMER_BOLD, "size": 52, "color": NAVY},
        {"key": "safety", "text": T_SAFETY, "font": FONT_KHMER, "size": 44, "color": NAVY},
        {"key": "discipline", "text": T_DISCIPLINE, "font": FONT_KHMER, "size": 44, "color": NAVY},
        {"key": "quality", "text": T_QUALITY, "font": FONT_KHMER, "size": 44, "color": NAVY},
        {"key": "good_work", "text": T_GOOD_WORK, "font": FONT_KHMER, "size": 46, "color": NAVY},
        {"key": "good_life", "text": T_GOOD_LIFE, "font": FONT_KHMER, "size": 46, "color": NAVY},
        {"key": "waste", "text": T_WASTE, "font": FONT_KHMER, "size": 36, "color": WHITE},
        {"key": "employee", "text": T_EMPLOYEE, "font": FONT_KHMER_BOLD, "size": 48, "color": BADGE_INK},
        {"key": "name", "text": T_NAME, "font": FONT_KHMER, "size": 36, "color": BADGE_INK},
        {"key": "name_latin", "text": T_NAME_LATIN, "font": FONT_LATIN, "size": 22, "color": "333333"},
        {"key": "title", "text": T_TITLE, "font": FONT_KHMER, "size": 32, "color": BADGE_INK},
        {"key": "title_latin", "text": T_TITLE_LATIN, "font": FONT_LATIN, "size": 18, "color": "333333"},
        {"key": "ident", "text": T_ID, "font": FONT_KHMER, "size": 32, "color": BADGE_INK},
        {"key": "factory_dark", "text": T_FACTORY, "font": FONT_KHMER_BOLD, "size": 56, "color": NEAR_BLACK},
        {"key": "factory_latin_dark", "text": T_LATIN_CO, "font": FONT_LATIN, "size": 22, "color": NEAR_BLACK},
        {"key": "family", "text": T_FAMILY, "font": FONT_KHMER_BOLD, "size": 40, "color": NEAR_BLACK},
        {"key": "quality_soft", "text": T_QUALITY, "font": FONT_KHMER, "size": 36, "color": NEAR_BLACK},
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prod", default="productions/010-gongpai")
    p.add_argument("--only", choices=["factory-gate", "notice-board", "bopha-badge", "group-photo"], action="append")
    args = p.parse_args()
    prod = Path(args.prod)
    if not prod.is_absolute():
        prod = (ROOT / prod).resolve()
    out_dir = prod / "02-assets" / "_khmer-overlay"
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = [
        ("factory-gate", "scenes", "factory-gate", factory_gate, "factory-gate.jpg"),
        ("notice-board", "scenes", "notice-board", notice_board, "notice-board.jpg"),
        ("bopha-badge", "props", "bopha-badge", bopha_badge, "bopha-badge.jpg"),
        ("group-photo", "props", "group-photo", group_photo, "group-photo.jpg"),
    ]
    if args.only:
        assets = [a for a in assets if a[0] in args.only]

    bin_path = Path(tempfile.gettempdir()) / "khmer_coretext"
    coretext = compile_coretext(bin_path)
    cache = Path(tempfile.gettempdir()) / "khmer-overlay-glyphs"
    glyphs = render_lines(coretext, glyph_jobs(), cache)

    used = {}
    for key, kind, slug, fn, dest_name in assets:
        plate, label = resolve_plate(prod, kind, slug)
        used[key] = {"plate": str(plate.relative_to(prod)), "source": label, "size": None}
        im = Image.open(plate).convert("RGB")
        used[key]["size"] = list(im.size)
        fn(im, glyphs)
        dest = out_dir / dest_name
        save_jpg(im, dest)
        print(f"{dest_name}: {plate} → {dest} ({im.size[0]}x{im.size[1]})")

    meta = {
        "engine": "Core Text (scripts/khmer_coretext.swift)",
        "fonts": {
            "khmer": FONT_KHMER,
            "khmer_bold": FONT_KHMER_BOLD,
            "latin": FONT_LATIN,
            "latin_serif": FONT_LATIN_SERIF,
        },
        "used": used,
        "note": "preview only — official master.jpg unchanged",
    }
    (out_dir / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
