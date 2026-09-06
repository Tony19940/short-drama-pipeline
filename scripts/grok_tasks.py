#!/usr/bin/env python3
"""Gate D/E task cards for the manual Grok Imagine canvas route.

Turns the locked shot contract into per-shot instructions: which parent image to
drop on the canvas, which reference images to attach, which canvas mode to use,
which prompt to paste, and what to name the file on the way back.

Clips on the canvas cap at 6 seconds, so shots longer than that are split into
same-axis continuation segments (SH003a, SH003b). That splits the generation
unit, not the cut: lens/axis/setup/move/look stay identical across segments and
the segments are concatenated with no transition, so the audience sees one long
take. See GROK-CANVAS.md section 3.

  python3 scripts/grok_tasks.py --prod productions/004-yuye-jinlian
  python3 scripts/grok_tasks.py --prod productions/004-yuye-jinlian --only SH003
  python3 scripts/grok_tasks.py --prod productions/004-yuye-jinlian --out cards.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from director.gates import continue_last_frame_rule  # noqa: E402
from director.prompts import (  # noqa: E402
    compile_still_prompt,
    compile_video_prompt,
    still_refs,
    video_mode,
)

CANVAS_CLIP_CAP = 6
CANVAS_REF_CAP = 3
SEGMENT_SUFFIXES = "abcdefghij"


def load_shots(prod: Path) -> list[dict]:
    path = prod / "03-storyboard" / "shots.json"
    if not path.exists():
        raise SystemExit(
            f"没有 {path}\n"
            "Gate C2 未完成。先写 shots.json 并跑 check_storyboard.py，再开画布。"
        )
    return json.loads(path.read_text(encoding="utf-8"))["shots"]


def load_sets(prod: Path) -> dict[str, dict]:
    path = prod / "03-storyboard" / "sets.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data.get("sets", [])}


def rank_refs(prod: Path, shot: dict) -> list[str]:
    """Faces first, then stage geography. Canvas edit nodes take 3."""
    refs = still_refs(prod, shot)
    faces = [r for r in refs if r.endswith(("sheet.jpg", "face.jpg"))]
    blocking = [r for r in refs if r.endswith("blocking.jpg")]
    rest = [r for r in refs if r not in faces and r not in blocking]
    return (faces + blocking + rest)[:CANVAS_REF_CAP]


def parent_for_first_frame(
    prod: Path, shot: dict, sets: dict[str, dict]
) -> tuple[str, str]:
    """Gate D parent image. Returns (path, why)."""
    derived = str(shot.get("derived_from") or "")
    scene = str(shot.get("scene") or "")
    if derived.endswith(".blocking"):
        set_id = derived[: -len(".blocking")]
        blocking = (sets.get(set_id) or {}).get("blocking")
        rel = blocking or f"02-assets/scenes/{set_id}/blocking.jpg"
        why = "换场硬切，从新场 blocking 改" if shot.get("cut") == "hard" else "本场第一镜，从 blocking 改"
        return rel, why
    if derived:
        return f"04-frames/{derived}.jpg", f"场内续镜，从上一镜首帧 {derived}.jpg 改"
    blocking = (sets.get(scene) or {}).get("blocking")
    if blocking:
        return blocking, "derived_from 缺失，回退到本场 blocking"
    return f"02-assets/scenes/{scene}/blocking.jpg", "derived_from 缺失，回退到本场 blocking"


def continue_eats_last_frame(shot: dict, prev: dict | None) -> tuple[bool, str]:
    """Same contract as i2v_source / render_shots: same setup + overlap."""
    return continue_last_frame_rule(shot, prev)


def segment_plan(shot: dict, eats_last: bool) -> list[dict]:
    """Split over-6s shots into same-axis continuation segments."""
    seconds = int(shot.get("seconds") or 0)
    sid = shot["id"]
    if seconds <= CANVAS_CLIP_CAP:
        source = f"{shot['from']}-last.jpg（上一镜末帧）" if eats_last else f"04-frames/{sid}.jpg（本镜设计首帧）"
        return [{"id": sid, "seconds": seconds, "first_frame": source, "note": ""}]

    count = math.ceil(seconds / CANVAS_CLIP_CAP)
    base, extra = divmod(seconds, count)
    plan = []
    for i in range(count):
        seg_id = f"{sid}{SEGMENT_SUFFIXES[i]}"
        secs = base + (1 if i < extra else 0)
        if i == 0:
            source = (
                f"{shot['from']}-last.jpg（上一镜末帧）"
                if eats_last
                else f"04-frames/{sid}.jpg（本镜设计首帧）"
            )
            note = "动作起始阶段"
        else:
            source = f"{sid}{SEGMENT_SUFFIXES[i - 1]} 的末帧"
            note = "动作推进阶段；lens / axis / setup / move / look 与上一段完全一致，一个字不改"
        plan.append({"id": seg_id, "seconds": secs, "first_frame": source, "note": note})
    return plan


def canvas_mode(shot: dict, eats_last: bool, refs: list[str]) -> tuple[str, str]:
    source_kind = "last_frame" if eats_last else "designed_frame"
    mode = video_mode(shot, source_kind, refs)
    if mode == "flf":
        return "首尾帧（锁首帧+设计尾帧）", "本镜有设计尾帧，动作用这个收住。"
    if eats_last:
        return (
            "同场续：上一镜真末帧再 FL2VA",
            "cut=continue 且同机位有人物交集 —— 必须锁上一镜末帧。参考图只挂在外面锁脸，不替代首帧。",
        )
    if mode == "r2v":
        return (
            "首帧图生 + 参考锁脸",
            "设计首帧驱动 FL2VA。sheet/face 走 Ref2VA 外挂，不替代第 0 秒。",
        )
    return "首帧图生（FL2VA）", "设计首帧驱动。"


def render_card(prod: Path, shot: dict, prev: dict | None, sets: dict[str, dict]) -> str:
    sid = shot["id"]
    refs = rank_refs(prod, shot)
    eats_last, why_last = continue_eats_last_frame(shot, prev)
    parent, why_parent = parent_for_first_frame(prod, shot, sets)
    mode, why_mode = canvas_mode(shot, eats_last, refs)
    segs = segment_plan(shot, eats_last)

    lines: list[str] = []
    lines.append(f"## {sid} · {shot.get('seconds')}s · {shot.get('setup')} / {shot.get('scale')}")
    lines.append("")
    lines.append(
        f"`{shot.get('lens')}` · `move={shot.get('move')}` · `axis={shot.get('axis')}` · "
        f"`scene={shot.get('scene')}` · `cut={shot.get('cut')}`"
        + (f" ← `{shot['from']}`" if shot.get("from") else "")
    )
    lines.append("")
    lines.append(f"**新信息：** {shot.get('new_info') or '—'}")
    if shot.get("caption"):
        lines.append(f"**字幕（后期叠，不进画面）：** {shot['caption']}")
    lines.append("")

    if eats_last:
        lines.append("### 1. 首帧")
        lines.append("")
        lines.append(f"**不出新首帧。** {why_last}。")
        lines.append("")
    else:
        lines.append("### 1. 首帧（Gate D）")
        lines.append("")
        lines.append(f"父图：`{parent}`")
        lines.append(f"理由：{why_parent}")
        missing = [] if (prod / parent).exists() else [parent]
        if missing:
            lines.append("")
            lines.append(f"> ⚠ 父图不存在：`{parent}` —— 先补 Gate S/D，别在画布上另开文生图。")
        lines.append("")
        lines.append(f"参考图（画布上限 {CANVAS_REF_CAP} 张，已按脸优先排序）：")
        if refs:
            for r in refs:
                tag = "脸" if r.endswith(("sheet.jpg", "face.jpg")) else ("地理" if r.endswith("blocking.jpg") else "光位")
                lines.append(f"- `{r}` （{tag}）")
        else:
            lines.append("- 无（空场）")
        lines.append("")
        lines.append("画布操作：拖入父图 → Edit 节点 → 挂参考图 → 粘贴下面这段 → 结果命名 "
                     f"`{sid}.jpg` 丢 `.director/inbox/`")
        lines.append("")
        lines.append("```text")
        lines.append(compile_still_prompt(shot))
        lines.append("```")
        lines.append("")

    lines.append("### 2. 出片（Gate E）")
    lines.append("")
    lines.append(f"模式：**{mode}**")
    lines.append(f"理由：{why_mode}")
    if not eats_last and shot.get("cut") == "continue" and shot.get("from"):
        lines.append("")
        lines.append(f"> {why_last}。`cut` 仍是 `continue`，因为地理连续 —— 但首帧不能用末帧。")
    lines.append("")
    if len(segs) > 1:
        lines.append(
            f"本镜 {shot.get('seconds')} 秒 > 画布 {CANVAS_CLIP_CAP} 秒上限，"
            f"拆 {len(segs)} 段同轴续接。**成片上这是一个长镜，不是 {len(segs)} 刀。**"
        )
        lines.append("")
        lines.append("| 段 | 秒 | 首帧 | 说明 |")
        lines.append("|---|---|---|---|")
        for s in segs:
            lines.append(f"| `{s['id']}` | {s['seconds']} | {s['first_frame']} | {s['note']} |")
        lines.append("")
        lines.append("回流文件名：" + "、".join(f"`{s['id']}.mp4`" for s in segs)
                     + f" —— `ingest_shots.py` 会合并成 `05-shots/{sid}.mp4`")
    else:
        s = segs[0]
        lines.append(f"首帧：{s['first_frame']}")
        lines.append(f"时长：{s['seconds']} 秒")
        lines.append("")
        lines.append(f"回流文件名：`{sid}.mp4` → `.director/inbox/`")
    lines.append("")
    lines.append("粘贴这段（每段都用同一份，只按上表调整动作阶段）：")
    lines.append("")
    lines.append("```text")
    lines.append(compile_video_prompt(shot, silent=True, refs=refs))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Grok 画布手动任务单（Gate D/E）")
    p.add_argument("--prod", required=True, help="productions/<slug>")
    p.add_argument("--only", nargs="*", help="镜号，如 SH001 SH003")
    p.add_argument("--out", help="写到文件，默认打到 stdout")
    args = p.parse_args()

    prod = Path(args.prod).resolve()
    shots = load_shots(prod)
    sets = load_sets(prod)
    by_id = {s["id"]: s for s in shots}
    want = set(args.only or [])
    selected = [s for s in shots if not want or s["id"] in want]
    if want and not selected:
        raise SystemExit(f"没有匹配的镜号：{sorted(want)}")

    total = sum(int(s.get("seconds") or 0) for s in shots)
    long_shots = [s["id"] for s in shots if int(s.get("seconds") or 0) > CANVAS_CLIP_CAP]

    head = [
        f"# Grok 画布任务单 · {prod.name}",
        "",
        f"{len(shots)} 镜 / {total} 秒。本单 {len(selected)} 镜。",
        "",
        "读 `GROK-CANVAS.md` 再动手。三条最容易踩的：",
        "",
        "1. 不用 Agent 自动拆 panel，画布当手动节点图。",
        "2. 续镜一律 image-to-video 锁首帧；reference-to-video 不锁首帧。",
        "3. 不用画布 stitch 出成片；单镜下载回 `.director/inbox/`。",
        "",
    ]
    if long_shots:
        head += [
            f"超 {CANVAS_CLIP_CAP} 秒需拆段的镜：{'、'.join(long_shots)}。"
            "拆的是生成单元不是剪辑点，见 `GROK-CANVAS.md` 第三节。",
            "",
        ]
    head.append("---")
    head.append("")

    cards = []
    for shot in selected:
        prev = by_id.get(shot.get("from")) if shot.get("from") else None
        cards.append(render_card(prod, shot, prev, sets))

    text = "\n".join(head) + "\n---\n\n".join(cards)
    if args.out:
        dest = Path(args.out)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote {dest}")
    else:
        print(text)


if __name__ == "__main__":
    main()
