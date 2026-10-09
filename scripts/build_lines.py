#!/usr/bin/env python3
"""Dialogue gate (台词关 L): build the lines table, write Khmer through Gemini, time it, review it.

    python3 scripts/build_lines.py --prod productions/012-khleang-moeung --episode 2 --khmer --html
    python3 scripts/build_lines.py --prod ... --episode 1 --stamp          # storyboard carries Khmer seconds
    python3 scripts/build_lines.py --prod ... --episode 1 --apply --retime # after the human approves proposals
    python3 scripts/build_lines.py --prod ... --episode 1 --sign Tony      # record the human sign-off
    python3 scripts/build_lines.py --prod ... --episode 1 --listen         # blind-listening script (Chinese)

Khmer comes from Gemini through the local `agy` CLI. The model never signs the review.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director.lines import (  # noqa: E402
    CAPTION,
    DEFAULT_KM_MODEL,
    KIND_ZH,
    apply_revisions,
    build_lines,
    effective_kind,
    effective_zh,
    fill_khmer,
    human_signer,
    load_glossary,
    lines_artifact_name,
    pending_change,
    refresh,
    retime_shots,
    shot_fit,
    stamp_line_timing,
    sync_chinese,
    tighten_khmer,
    tighten_targets,
    validate_lines,
)
from director.pipeline import episode_artifact_name, read_artifact, write_artifact  # noqa: E402
from director.production import read_text  # noqa: E402
from director.speech import CHARACTERS_MD, parse_character_cards  # noqa: E402

REVIEW_PAGE = "01-bible/lines-review.html"


def _t(value) -> str:
    return str(value or "").strip()


def load_episode(prod: Path, episode: int) -> tuple[dict, dict, dict]:
    writer = read_artifact(prod, episode_artifact_name("writer.json", episode))
    if not writer.get("scenes"):
        raise SystemExit(f"{episode_artifact_name('writer.json', episode)} has no scenes; write the script first")
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
    previous = read_artifact(prod, lines_artifact_name(episode))
    return writer, table, previous


def names_of(writer: dict, cards: dict) -> dict[str, str]:
    out = {cid: _t(card.get("name")) for cid, card in cards.items()}
    for char in (writer.get("series_bible") or {}).get("characters") or []:
        if isinstance(char, dict) and _t(char.get("id")) and _t(char.get("id")) not in out:
            out[_t(char.get("id"))] = _t(char.get("name"))
    return out


def listening_script(writer: dict, data: dict, cards: dict) -> list[str]:
    """What a viewer hears and reads, in order, with the scene's key sounds. Chinese, no pictures."""
    names = names_of(writer, cards)
    rows_by_scene: dict[str, list[dict]] = {}
    for row in data.get("lines") or []:
        if not row.get("drop"):
            rows_by_scene.setdefault(_t(row.get("scene_id")), []).append(row)
    out: list[str] = []
    for scene in writer.get("scenes") or []:
        sid = _t(scene.get("scene_id"))
        out.append(f"【{_t(scene.get('heading')) or sid}】")
        sounds = [_t(s) for s in scene.get("key_sounds") or [] if _t(s)]
        if sounds:
            out.append("（声音：" + "；".join(sounds) + "）")
        for row in rows_by_scene.get(sid) or []:
            kind = effective_kind(row)
            text = effective_zh(row)
            if kind == CAPTION:
                out.append(f"［字幕］{text}")
                continue
            who = names.get(_t(row.get("speaker")), _t(row.get("speaker"))) or "旁白"
            tag = "" if kind == "dialogue" else f"（{KIND_ZH.get(kind, kind)}）"
            how = f"（{_t(row.get('parenthetical'))}）" if _t(row.get("parenthetical")) else ""
            out.append(f"{who}{tag}{how}：{text}")
        out.append("")
    return out


# --- review page ---------------------------------------------------------------------------

CSS = """
:root{--bg:#f7f5f0;--card:#fff;--ink:#1d1b18;--mute:#6b6458;--line:#e2ddd2;--accent:#8a4b12;
--warn:#b45309;--warnbg:#fff4e0;--bad:#b42318;--badbg:#fdecea;--ok:#2f6f3e;--okbg:#e8f4ea;--new:#1f4fa3;--newbg:#e8eefb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171513;--card:#211e1b;--ink:#ece6dc;--mute:#a59d90;
--line:#3a352f;--accent:#e0a060;--warn:#f0b35a;--warnbg:#3a2a12;--bad:#f2867b;--badbg:#3b1d1a;--ok:#86c99a;--okbg:#18301f;--new:#9db8f2;--newbg:#1b2540}}
:root[data-theme="dark"]{--bg:#171513;--card:#211e1b;--ink:#ece6dc;--mute:#a59d90;--line:#3a352f;--accent:#e0a060;
--warn:#f0b35a;--warnbg:#3a2a12;--bad:#f2867b;--badbg:#3b1d1a;--ok:#86c99a;--okbg:#18301f;--new:#9db8f2;--newbg:#1b2540}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans SC",sans-serif}
main{max-width:1400px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:20px;margin:36px 0 8px}
h3{font-size:16px;margin:20px 0 8px}.sub{color:var(--mute);margin:0 0 16px}.how{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.how li{margin:2px 0}.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 12px}.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:2px 12px;font-size:13px}
.chip.bad{background:var(--badbg);color:var(--bad);border-color:transparent}.chip.warn{background:var(--warnbg);color:var(--warn);border-color:transparent}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}table{border-collapse:collapse;width:100%;min-width:1340px;table-layout:fixed}
table.fit{min-width:900px}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;vertical-align:top;text-align:left}th{font-size:13px;color:var(--mute);font-weight:600;background:var(--card);position:sticky;top:0}
td.n{color:var(--mute);font-size:12px;white-space:nowrap}.who{white-space:nowrap}.kind{font-size:12px;color:var(--mute)}
.km{font-family:"Khmer Sangam MN","Khmer MN","Noto Sans Khmer","Leelawadee UI",sans-serif;font-size:17px;line-height:1.9}
.back{color:var(--mute)}.old{text-decoration:line-through;color:var(--mute)}.newtext{font-weight:600}
.tag{display:inline-block;font-size:12px;border-radius:6px;padding:0 6px;margin:0 4px 4px 0}.tag.new{background:var(--newbg);color:var(--new)}
.tag.warn{background:var(--warnbg);color:var(--warn)}.tag.bad{background:var(--badbg);color:var(--bad)}.tag.ok{background:var(--okbg);color:var(--ok)}
.why{font-size:13px;color:var(--accent)}.note{font-size:13px;color:var(--mute)}.sec{white-space:nowrap;font-variant-numeric:tabular-nums}
.over{color:var(--bad);font-weight:600}pre.listen{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;font:14px/1.8 inherit}
details summary{cursor:pointer;color:var(--accent);margin:8px 0}nav.eps{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
nav.eps a{color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:8px;padding:2px 10px;background:var(--card)}
"""


def esc(value) -> str:
    return html.escape(_t(value))


def _tags(flags: list[dict]) -> str:
    out = []
    for flag in flags or []:
        level = "bad" if flag.get("level") == "error" else ("warn" if flag.get("level") == "warn" else "")
        out.append(f'<span class="tag {level}" title="{esc(flag.get("msg"))}">{esc(flag.get("code"))}</span><span class="note">{esc(flag.get("msg"))}</span><br>')
    return "".join(out)


def _zh_cell(row: dict) -> str:
    change = pending_change(row)
    why = f'<div class="why">{esc(row.get("why"))}</div>' if _t(row.get("why")) else ""
    if change == "add":
        return f'<span class="tag new">新增</span><div class="newtext">{esc(effective_zh(row))}</div>{why}'
    if change == "drop":
        return f'<span class="tag bad">删掉</span><div class="old">{esc(row.get("zh"))}</div>{why}'
    if change == "revise":
        return f'<div class="old">{esc(row.get("zh"))}</div><div class="newtext">→ {esc(effective_zh(row))}</div>{why}'
    if change == "kind":
        return f'<span class="tag new">改为{esc(KIND_ZH.get(effective_kind(row), ""))}</span><div>{esc(row.get("zh"))}</div>{why}'
    return f"<div>{esc(row.get('zh'))}</div>"


def episode_section(prod: Path, episode: int, cards: dict) -> str:
    writer, table, data = load_episode(prod, episode)
    if not data:
        return ""
    refresh(data, table or None)
    errors, warnings = validate_lines(data, writer, table or None)
    names = names_of(writer, cards)
    rows = data.get("lines") or []
    fits = data.get("shots") or []
    headings = {_t(s.get("scene_id")): _t(s.get("heading")) for s in writer.get("scenes") or []}
    shot_of: dict[str, list[str]] = {}
    for fit in fits:
        for ref in fit.get("lines") or []:
            shot_of.setdefault(ref["line_id"], []).append(fit["shot_id"])
    live = [r for r in rows if not r.get("drop")]
    spoken = [r for r in live if effective_kind(r) != CAPTION]
    zh_total = round(sum(float(r.get("zh_sec") or 0) for r in spoken), 1)
    km_total = round(sum(float(r.get("km_sec") or 0) for r in spoken), 1)
    counts = {k: sum(1 for r in live if effective_kind(r) == k) for k in ("dialogue", "inner", "narration", "intro", CAPTION)}
    ai_flags = sum(1 for r in live for f in r.get("flags") or [] if f.get("level") == "warn")
    overflow = [f for f in fits if not f.get("fits")]
    pending = [r for r in rows if pending_change(r)]
    chips = [
        f'<span class="chip">{len(spoken)} 句要念 · ' + " / ".join(f"{KIND_ZH[k]} {n}" for k, n in counts.items() if n) + "</span>",
        f'<span class="chip">中文约 {zh_total}s · 高棉语约 {km_total}s（估算）</span>',
        f'<span class="chip {"warn" if ai_flags else ""}">AI 腔 / 变长提示 {ai_flags} 处</span>',
    ]
    if table:
        chips.append(f'<span class="chip {"bad" if overflow else ""}">镜头装不下 {len(overflow)} 个</span>')
    if pending:
        chips.append(f'<span class="chip warn">待写回剧本的改稿 {len(pending)} 处</span>')
    body = []
    for index, row in enumerate(rows, start=1):
        kind = effective_kind(row)
        sid = _t(row.get("scene_id"))
        where = esc(sid.split("_")[-1] if "_" in sid else sid)
        shots = shot_of.get(_t(row.get("line_id"))) or []
        if shots:
            where += "<br>" + esc("、".join(dict.fromkeys(shots)))
        speaker = names.get(_t(row.get("speaker")), _t(row.get("speaker")))
        listener = names.get(_t(row.get("to")), _t(row.get("to")))
        who = esc(speaker or "—") + (f" → {esc(listener)}" if listener else "")
        how = f'<div class="kind">{esc(row.get("parenthetical"))}</div>' if _t(row.get("parenthetical")) else ""
        if row.get("drop"):
            sec = "—"
        elif kind == CAPTION:
            sec = f'读 {row.get("read_sec", 0)}s'
        else:
            sec = f'中 {row.get("zh_sec", 0)}s<br>高 {row.get("km_sec", 0)}s'
        units = row.get("units") or []
        km = "<br>".join(esc(u.get("km")) for u in units) or '<span class="tag bad">缺</span>'
        back = "<br>".join(esc(u.get("back_zh")) for u in units)
        note = f'<div class="note">Gemini：{esc(row.get("km_note"))}</div>' if _t(row.get("km_note")) else ""
        body.append(
            "<tr>"
            f'<td class="n">{index}<br>{where}</td>'
            f'<td class="who">{who}<div class="kind">{esc(KIND_ZH.get(kind, kind))}</div>{how}</td>'
            f'<td>{esc(row.get("purpose"))}</td>'
            f"<td>{_zh_cell(row)}</td>"
            f'<td class="km">{km}</td>'
            f'<td class="back">{back}</td>'
            f'<td class="sec">{sec}</td>'
            f"<td>{_tags(row.get('flags'))}{_tags(row.get('km_flags'))}{note}</td>"
            "</tr>"
        )
    fit_rows = []
    for fit in fits:
        cls = "" if fit["fits"] else "over"
        said = "；".join(f'{esc(names.get(r["speaker"], r["speaker"]))}{"（" + KIND_ZH.get(r["kind"], "") + "）" if r["kind"] != "dialogue" else ""}：{esc(r["line"])}' for r in fit["lines"]) or "（不再有台词）"
        mouth = esc(fit["delivery"]) if fit["delivery"] == fit["delivery_after"] else f'{esc(fit["delivery"])} → <b>{esc(fit["delivery_after"])}</b>'
        fit_rows.append(
            f'<tr><td class="n">{esc(fit["shot_id"])}</td><td>{said}</td><td class="sec">{fit["duration_sec"]}s</td>'
            f'<td class="sec">中 {fit["zh_need_sec"]}s · 含高棉语 {fit["need_sec"]}s</td>'
            f'<td class="sec {cls}">{"够" if fit["fits"] else "改成 " + str(fit["suggest_sec"]) + "s"}</td><td>{mouth}</td></tr>'
        )
    fit_html = ""
    if fit_rows:
        fit_html = (
            "<h3>每个镜头装不装得下</h3>"
            '<div class="wrap"><table class="fit"><colgroup><col style="width:70px"><col><col style="width:70px"><col style="width:190px"><col style="width:100px"><col style="width:150px"></colgroup>'
            '<tr><th>镜号</th><th>这一镜说什么（按改稿后）</th><th>现在</th><th>需要</th><th>结论</th><th>口型</th></tr>'
            + "".join(fit_rows)
            + "</table></div>"
        )
    issues = ""
    if errors:
        issues = "<details><summary>锁定前还要处理（" + str(len(errors)) + "）</summary><ul>" + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></details>"
    listen = "\n".join(listening_script(writer, data, cards))
    outline = [o for o in writer.get("episode_outline") or [] if isinstance(o, dict)]
    title = _t(next((o.get("title") for o in outline if int(o.get("episode_no") or 0) == episode), ""))
    return (
        f'<section id="ep{episode:02d}"><h2>第 {episode} 集{(" · " + esc(title)) if title else ""}</h2>'
        f'<div class="chips">{"".join(chips)}</div>{issues}'
        f"<details><summary>盲听稿：只读这一段，不看画面，能不能跟上故事</summary><pre class=\"listen\">{esc(listen)}</pre></details>"
        '<div class="wrap"><table><colgroup><col style="width:72px"><col style="width:120px"><col style="width:150px"><col style="width:250px">'
        '<col style="width:250px"><col style="width:200px"><col style="width:78px"><col style="width:220px"></colgroup>'
        '<tr><th>#／场／镜</th><th>谁 → 谁</th><th>这句干什么</th><th>中文工作稿</th><th>高棉语（成片）</th><th>高棉语逐字回译</th><th>时长</th><th>提示</th></tr>'
        + "".join(body)
        + "</table></div>"
        + fit_html
        + "</section>"
    )


def render_review(prod: Path, episodes: list[int]) -> Path:
    cards = parse_character_cards(read_text(prod, CHARACTERS_MD))
    sections = [episode_section(prod, ep, cards) for ep in episodes]
    sections = [s for s in sections if s]
    nav = "".join(f'<a href="#ep{ep:02d}">第 {ep} 集</a>' for ep in episodes)
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>台词表 · {esc(prod.name)}</title><style>{CSS}</style></head><body><main>
<h1>台词表</h1><p class="sub">{esc(prod.name)} · 生成于 {time.strftime("%Y-%m-%d %H:%M")}</p>
<div class="how"><b>怎么审</b><ul>
<li>先打开“盲听稿”，不看画面读一遍：能不能跟上故事、哪里掉线。</li>
<li>看“中文工作稿”和“高棉语逐字回译”：意思有没有跑偏。回译读起来别扭没关系，那是高棉语语序。</li>
<li>“提示”里黄色是 AI 腔或会变长的地方，红色必须改；“Gemini”是写高棉语时发现的问题。</li>
<li>时长：中 = 中文原声，高 = 高棉语配音（按实测语速估算）。镜头要装得下较长的那个。</li>
<li>划线的是原句，→ 后面是建议改成的样子；你同意后我再写回剧本和分镜。</li>
</ul></div>
<nav class="eps">{nav}</nav>
{"".join(sections)}
</main></body></html>
"""
    path = prod / REVIEW_PAGE
    path.write_text(page, encoding="utf-8")
    return path


# --- main ----------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prod", required=True, type=Path)
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--khmer", action="store_true", help="write missing Khmer through Gemini (agy)")
    parser.add_argument("--force-khmer", action="store_true", help="rewrite all Khmer through Gemini")
    parser.add_argument("--model", default=DEFAULT_KM_MODEL)
    parser.add_argument("--tighten", action="store_true", help="ask Gemini to shorten on-camera Khmer that outruns the Chinese mouth")
    parser.add_argument("--stamp", action="store_true", help="write Khmer seconds into the shot table")
    parser.add_argument("--apply", action="store_true", help="write approved proposals into writer + shot table")
    parser.add_argument("--retime", action="store_true", help="lengthen shots that cannot hold their lines")
    parser.add_argument("--sign", default="", help="human reviewer name; marks the lines table reviewed")
    parser.add_argument("--listen", action="store_true", help="print the blind-listening script")
    parser.add_argument("--html", action="store_true", help="render 01-bible/lines-review.html")
    parser.add_argument("--html-episodes", default="", help="comma list of episodes for the page (default: this one)")
    args = parser.parse_args()
    prod = args.prod if args.prod.is_absolute() else (ROOT / args.prod)
    prod = prod.resolve()
    episode = args.episode
    writer, table, previous = load_episode(prod, episode)
    cards = parse_character_cards(read_text(prod, CHARACTERS_MD))
    data = build_lines(writer, previous=previous, table=table or None, episode_no=episode)
    if not data.get("glossary"):
        data["glossary"] = load_glossary(prod)
    if args.khmer or args.force_khmer:
        missing = fill_khmer(data, writer=writer, cards=cards, model=args.model, force=args.force_khmer)
        refresh(data, table or None)
        if missing:
            print("Gemini left these without Khmer:", ", ".join(missing), file=sys.stderr)
    if args.tighten:
        targets = tighten_targets(data, table or None)
        if targets:
            result = tighten_khmer(data, targets, writer=writer, cards=cards, model=args.model)
            refresh(data, table or None)
            for lid, (before, after) in result.items():
                print(f"tighten {lid}: {before}s → {after}s (mouth target {targets[lid]}s)")
            still = list(tighten_targets(data, table or None))
            if still:
                for lid, change in sync_chinese(data, still, writer=writer, cards=cards, model=args.model).items():
                    print(f"zh follows km {lid}: {change}")
                refresh(data, table or None)
        else:
            print("tighten: no on-camera line outruns its mouth")
    if args.apply:
        log = apply_revisions(writer, data, table or None)
        write_artifact(prod, episode_artifact_name("writer.json", episode), writer)
        print("\n".join(log) or "no proposals")
    if args.retime and table:
        for line in retime_shots(table, data):
            print("retime", line)
    if (args.stamp or args.apply or args.retime) and table:
        touched = stamp_line_timing(table, data)
        write_artifact(prod, episode_artifact_name("shot_list.json", episode), table)
        print("stamped Khmer seconds:", ", ".join(touched) or "none changed")
    if args.sign:
        if not human_signer(args.sign):
            raise SystemExit("--sign takes the human reviewer's name, not a model")
        errors, _warnings = validate_lines(data, writer, table or None)
        if errors:
            raise SystemExit("cannot sign: " + errors[0])
        data["status"] = "reviewed"
        data["reviewed_by"] = args.sign
        data["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    elif previous and _t(previous.get("status")) == "reviewed" and _t(previous.get("writer_digest")) == data["writer_digest"]:
        same = json.dumps([r.get("units") for r in previous.get("lines") or []], ensure_ascii=False) == json.dumps([r.get("units") for r in data.get("lines") or []], ensure_ascii=False)
        if same:
            data["status"], data["reviewed_by"], data["reviewed_at"] = "reviewed", previous.get("reviewed_by"), previous.get("reviewed_at")
    write_artifact(prod, lines_artifact_name(episode), data)
    errors, warnings = validate_lines(data, writer, table or None)
    print(f"{lines_artifact_name(episode)}: {len(data['lines'])} rows, {len(errors)} errors, {len(warnings)} warnings")
    for line in errors[:12]:
        print("  ERROR", line)
    for line in warnings[:30]:
        print("  warn ", line)
    if args.listen:
        print("\n".join(listening_script(writer, data, cards)))
    if args.html:
        episodes = [int(x) for x in args.html_episodes.split(",") if x.strip()] or [episode]
        print("review page:", render_review(prod, episodes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
