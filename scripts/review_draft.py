#!/usr/bin/env python3
"""QC evidence and a review page for a draft pass (review-only: no takes, no EDL, no Ark calls).

    python3 scripts/review_draft.py --prod productions/012-khleang-moeung --episode 1
    python3 scripts/review_draft.py --prod ... --episode 1 --dir 05-shots/draft-480p --step 0.25

Per clip in the draft folder: `qc/<SH>-strip.jpg` (a frame every --step seconds), `qc/<SH>-last.jpg`, and a
local transcript compared with the shot's on-camera line (whisper-cli, if installed). `review.html` lays out
first frame | clip | plan | lines | transcript | reviewer notes (`notes.json`, written by the reviewer after
looking at the strips). Never call an action missing from a handful of thumbnails: open the strip.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director.context import context_for, using_context  # noqa: E402
from director.draft_review import dense_strip, last_frame, probe_seconds, similarity, transcribe  # noqa: E402
from director.lines import read_lines  # noqa: E402
from director.pipeline import episode_artifact_name, read_artifact  # noqa: E402

TAGS = {"pipeline": ("流水线问题", "#c0392b"), "model": ("疑似模型能力", "#d68910"), "ok": ("没问题", "#1e8449"),
        "check": ("请你看/听", "#2e86c1")}
LOW_MATCH = 0.6


def default_dir(ctx) -> str:
    return f"{ctx.shot_dir()}/draft-480p"


def build(prod: Path, episode, folder: Path, *, step: float, asr: bool) -> dict:
    ctx = context_for(prod, episode)
    with using_context(ctx):
        table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
        lines = read_lines(prod, episode)
    by_line = {row.get("line_id"): row for row in (lines or {}).get("lines") or []}
    qc = folder / "qc"
    report: dict = {"episode": str(episode), "dir": str(folder.relative_to(prod)), "step_sec": step, "shots": {}}
    for shot in table.get("shots") or []:
        sid = shot["shot_id"]
        clip = folder / f"{sid}.mp4"
        if not clip.is_file():
            report["shots"][sid] = {"missing": True}
            continue
        entry: dict = {"clip_sec": round(probe_seconds(clip), 3), "paper_sec": shot.get("duration_sec"),
                       "delivery": shot.get("dialogue_delivery") or "none"}
        entry["strip"] = str(dense_strip(clip, qc / f"{sid}-strip.jpg", step=step).relative_to(folder))
        entry["last"] = str(last_frame(clip, qc / f"{sid}-last.jpg").relative_to(folder))
        expected = "".join(_line(ref, by_line) for ref in shot.get("dialogue_ref") or [])
        entry["expected"] = expected if entry["delivery"] == "on_camera" else ""
        if asr:
            heard = transcribe(clip, qc)
            if heard is not None:
                entry["heard"] = heard["text"]
                entry["segments"] = heard["segments"]
                if entry["expected"]:
                    entry["match"] = similarity(entry["expected"], heard["text"])
        report["shots"][sid] = entry
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    write_page(prod, folder, table, lines, report)
    return report


def _line(ref: dict, by_line: dict) -> str:
    row = by_line.get(ref.get("line_id")) or {}
    return str(ref.get("line") or row.get("zh") or "")


def write_page(prod: Path, folder: Path, table: dict, lines: dict, report: dict) -> Path:
    by_line = {row.get("line_id"): row for row in (lines or {}).get("lines") or []}
    notes_path = folder / "notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
    frame_rel = Path("..")
    # first frames live in the episode frame folder; draft lives under the shot folder
    rel_up = "/".join([".."] * len(folder.relative_to(prod).parts))
    rows = []
    for shot in table.get("shots") or []:
        sid = shot["shot_id"]
        entry = report["shots"].get(sid) or {}
        held = shot.get("held_action") or {}
        lines_html = "".join(
            f"<div class=ln><b>{html.escape(str(ref.get('character') or ''))}</b> {html.escape(_line(ref, by_line))}"
            f"<div class=km>{html.escape(str((by_line.get(ref.get('line_id')) or {}).get('km') or ''))}</div></div>"
            for ref in shot.get("dialogue_ref") or [])
        heard = ""
        if entry.get("heard") is not None:
            score = entry.get("match")
            flag = " low" if score is not None and score < LOW_MATCH else ""
            heard = (f"<div class='heard{flag}'>听写：{html.escape(entry['heard'] or '（无人声）')}"
                     + (f"<span class=score>{score:.2f}</span>" if score is not None else "") + "</div>")
        note = notes.get(sid) or {}
        tags = "".join(f"<span class=tag style='background:{TAGS[c][1]}'>{TAGS[c][0]}</span>" for c in note.get("tags", []) if c in TAGS)
        items = "".join(f"<li>{html.escape(x)}</li>" for x in note.get("items", []))
        video = (f"<video src='{sid}.mp4' controls preload=metadata playsinline></video>"
                 f"<a class=strip href='{entry.get('strip', '')}' target=_blank>逐帧（每 {report['step_sec']}s）</a>"
                 if not entry.get("missing") else "<div class=miss>还没出</div>")
        frame = f"{rel_up}/{shot.get('first_frame') or ''}" if shot.get("first_frame") else f"{rel_up}/04-frames/{sid}.jpg"
        hold = (f"<div class=sub><b>停在</b> {html.escape(held.get('stop_at', ''))}（不完成：{html.escape(held.get('unfinished', ''))}）</div>"
                if held else "")
        rows.append(
            f"<tr id={sid}><td class=id>{sid}<div class=dur>{shot.get('duration_sec')}s · {html.escape(str(shot.get('dialogue_delivery') or 'none'))}</div></td>"
            f"<td><img src='{frame}' loading=lazy></td><td>{video}</td>"
            f"<td class=plan><div><b>动作</b> {html.escape(str(shot.get('one_action') or ''))}</div>"
            f"<div class=sub><b>起</b> {html.escape(str(shot.get('in_from') or ''))}</div>"
            f"<div class=sub><b>落</b> {html.escape(str(shot.get('out_to') or ''))}</div>{hold}{lines_html}{heard}</td>"
            f"<td class=notes>{tags}<ul>{items}</ul></td></tr>"
        )
    cut = next(iter(sorted(folder.glob("*-review.mp4"))), None)
    cut_html = (f"<h2>整集审片版</h2><video class=cut src='{cut.name}' controls preload=metadata playsinline></video>"
                "<p class=meta>中文字幕只为审片，成片不带；（画外）（内心）的句子草稿里没有声音，是后期配音。</p>") if cut else ""
    summary = notes.get("_summary", "")
    done = sum(1 for e in report["shots"].values() if not e.get("missing"))
    page = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>草稿审片</title><style>
:root{{--bg:#fafaf7;--fg:#1b1b1b;--muted:#666;--line:#ddd;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333;--card:#1f1f1f}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"PingFang SC",sans-serif;margin:0;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:17px}} .meta{{color:var(--muted);margin-bottom:12px}}
table{{border-collapse:collapse;width:100%;background:var(--card)}} td{{border-top:1px solid var(--line);padding:8px;vertical-align:top}}
td.id{{font-weight:700;white-space:nowrap}} .dur{{font-weight:400;color:var(--muted);font-size:12px}}
img,video{{width:300px;max-width:30vw;border-radius:4px;display:block}} video.cut{{width:100%;max-width:960px}}
.plan{{min-width:220px}} .sub{{color:var(--muted);font-size:13px}} a.strip{{font-size:12px}}
.ln{{margin-top:6px;padding:4px 6px;border-left:3px solid #888}} .km{{font-family:"Khmer Sangam MN","Noto Sans Khmer",sans-serif;color:var(--muted)}}
.heard{{margin-top:6px;font-size:13px;color:var(--muted)}} .heard.low{{color:#c0392b}} .score{{margin-left:6px;font-weight:700}}
.notes{{min-width:220px}} .tag{{color:#fff;border-radius:3px;padding:1px 6px;font-size:12px;margin-right:4px}} ul{{margin:6px 0 0 18px;padding:0}}
.miss{{color:var(--muted)}} .sum{{background:var(--card);border:1px solid var(--line);padding:10px 14px;border-radius:6px;margin-bottom:12px;white-space:pre-wrap}}
</style></head><body><h1>草稿审片 · {html.escape(report['dir'])}</h1>
<div class=meta>{done}/{len(report['shots'])} 镜已出 · 左起：设计首帧｜草稿视频（附逐帧）｜分镜计划、台词与听写｜审片意见。低清晰度看不清脸，脸像不像留到正式清晰度再判。</div>
{f'<div class=sum>{html.escape(summary)}</div>' if summary else ''}{cut_html}
<table>{''.join(rows)}</table></body></html>"""
    out = folder / "review.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prod", required=True, type=Path)
    parser.add_argument("--episode", default="1")
    parser.add_argument("--dir", default="", help="draft folder under the production (default: <shot dir>/draft-480p)")
    parser.add_argument("--step", type=float, default=0.25, help="seconds between strip frames")
    parser.add_argument("--no-asr", action="store_true", help="skip the local transcript")
    args = parser.parse_args()
    prod = (args.prod if args.prod.is_absolute() else ROOT / args.prod).resolve()
    ctx = context_for(prod, args.episode)
    folder = prod / (args.dir or default_dir(ctx))
    if not folder.is_dir():
        raise SystemExit(f"no draft folder {folder}")
    report = build(prod, args.episode, folder, step=args.step, asr=not args.no_asr)
    low = [sid for sid, e in report["shots"].items() if e.get("match") is not None and e["match"] < LOW_MATCH]
    missing = [sid for sid, e in report["shots"].items() if e.get("missing")]
    print(f"wrote {(folder / 'review.html').relative_to(prod)}; {len(report['shots']) - len(missing)} clips")
    if missing:
        print("missing:", ", ".join(missing))
    if low:
        print(f"line match < {LOW_MATCH} (listen):", ", ".join(low))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
