#!/usr/bin/env python3
"""Build a local HTML review page: locked shot table + 04-frames stills.

Writes productions/<slug>/REVIEW.html with relative image paths so it opens
as a file. Does not write shots.json or start video.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import productions_root
from director.pipeline import episode_artifact_name, read_artifact
from place_codex_frame import episode_frame_dir, read_sidecar

SCENE_LABELS = {
    "009-siem-reap": {
        "EP01_SC01": "暴雨河道",
        "EP01_SC02": "古浅滩",
        "EP01_SC03": "粮栈夜",
    },
    "010-gongpai": {
        "EP01_SC01": "厂门门房",
        "EP01_SC02": "后排杂物间",
        "EP01_SC03": "七线车间",
    },
}


def _t(value) -> str:
    return str(value or "").strip()


def _esc(value) -> str:
    return html.escape(_t(value), quote=True)


def _dialogue(shot: dict) -> str:
    parts = []
    for item in shot.get("dialogue_ref") or []:
        if not isinstance(item, dict):
            continue
        who = _t(item.get("character"))
        line = _t(item.get("line"))
        if not line:
            continue
        parts.append(f"{who}：{line}" if who else line)
    return " / ".join(parts)


def _cuts(shot: dict) -> str:
    bits = []
    for cut in shot.get("internal_cuts") or []:
        if not isinstance(cut, dict):
            continue
        at = cut.get("at_sec")
        action = _t(cut.get("one_action"))
        if action:
            bits.append(f"{at}s {action}" if at is not None else action)
    return "；".join(bits)


def _row(label: str, value: str) -> str:
    if not _t(value):
        return ""
    return f"<div class='kv'><span>{_esc(label)}</span><b>{_esc(value)}</b></div>"


def _img(rel: str, caption: str, missing: bool) -> str:
    if missing:
        return (
            f"<figure class='miss'><div class='ph'>缺 {_esc(rel)}</div>"
            f"<figcaption>{_esc(caption)}</figcaption></figure>"
        )
    return (
        f"<figure><img src='{_esc(rel)}' alt='{_esc(caption)}' loading='lazy'>"
        f"<figcaption>{_esc(caption)}</figcaption></figure>"
    )


def _scene_label(prod: Path, scene: str, location_id: str) -> str:
    return (SCENE_LABELS.get(prod.name) or {}).get(scene) or _t(location_id) or scene


def _lock_line(value) -> str:
    try:
        from director.shot_table import lock_display
    except ImportError:
        return _t(value)
    return lock_display(value)


def _review_title(prod: Path, episode: int = 1) -> str:
    try:
        from director.production import _title
    except ImportError:
        return f"{prod.name} · 第 {int(episode):02d} 集"
    return f"{_title(prod)} · 第 {int(episode):02d} 集"


def _parent_of(prod: Path, rel: str) -> str:
    """Parent image recorded by place_codex_frame.py, if the landing left a sidecar."""
    try:
        from place_codex_frame import read_sidecar
    except ImportError:
        return ""
    return _t(read_sidecar(prod, rel).get("parent")) if rel else ""


def render(prod: Path, episode: int = 1) -> str:
    from director.shot_table import state_sentence

    folder = episode_frame_dir(episode)
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
    packages = {p.get("shot_id"): p for p in (read_artifact(prod, episode_artifact_name("gen_packages.json", episode)).get("packages") or [])}
    kf_data = read_artifact(prod, episode_artifact_name("keyframes.json", episode))
    frames = {k.get("shot_id"): k for k in (kf_data.get("keyframes") or [])}
    shots = list(table.get("shots") or [])
    locks = table.get("left_right_lock") or {}
    bible = table.get("continuity_bible") if isinstance(table.get("continuity_bible"), dict) else {}
    nits = [s.get("shot_id") for s in frames.values() if (s.get("qc") or {}).get("notes") and (s.get("qc") or {}).get("status") == "pass"]
    fails = [s.get("shot_id") for s in frames.values() if (s.get("qc") or {}).get("status") == "fail"]
    hardest = [s.get("shot_id") for s in shots if s.get("hardest")]
    title = _review_title(prod, episode)
    total = int(sum(float(s.get("duration_sec") or 0) for s in shots))
    kf_status = _t(kf_data.get("status")) or "未写"
    reviewed_by = _t(kf_data.get("reviewed_by")) or "无人签名"

    nav = []
    body = []
    last_scene = None
    prev_in_scene = None
    for shot in shots:
        sid = _t(shot.get("shot_id"))
        scene = _t(shot.get("scene_id"))
        pkg = packages.get(sid) or {}
        kf = frames.get(sid) or {}
        qc = kf.get("qc") or {}
        note = _t(qc.get("notes"))
        status = _t(qc.get("status")) or "待审"
        is_fail = status == "fail"
        first_rel = _t(kf.get("first_frame_file")) or f"{folder}/{sid}.jpg"
        last_rel = _t(kf.get("last_frame_file")) or (f"{folder}/{sid}-last.jpg" if _t(pkg.get("keyframe_plan")) == "first_last" else "")
        first_miss = not (prod / first_rel).exists()
        last_miss = bool(last_rel) and not (prod / last_rel).exists()
        sidecar = read_sidecar(prod, first_rel) if first_rel else {}
        parent_rel = _t(sidecar.get("parent")) or _parent_of(prod, first_rel)
        gate = _t(sidecar.get("identity_gate"))
        flags = []
        if shot.get("hardest"):
            flags.append("最难")
        if shot.get("evidence"):
            flags.append("证据")
        if gate == "awaiting_user":
            flags.append("待你审")
        if gate == "fail" or is_fail:
            flags.append("fail")
        elif note:
            flags.append("nit")
        if parent_rel and not (prod / parent_rel).exists():
            flags.append("缺父图")
        elif first_rel and (prod / first_rel).exists() and not parent_rel:
            flags.append("缺父图")
        plan = _t(pkg.get("keyframe_plan") or pkg.get("gen_mode"))
        chip_cls = " fail" if (gate == "fail" or is_fail) else (" wait" if gate == "awaiting_user" else (" nit" if note else ""))
        nav.append(
            f"<a href='#{_esc(sid)}' class='chip{chip_cls}{' hard' if shot.get('hardest') else ''}' "
            f"data-shot='{_esc(sid)}' data-nit='{1 if note else 0}' data-fail='{1 if (gate == 'fail' or is_fail) else 0}' data-wait='{1 if gate == 'awaiting_user' else 0}' data-hard='{1 if shot.get('hardest') else 0}'>{_esc(sid)}</a>"
        )
        if scene != last_scene:
            lock = _lock_line(locks.get(scene) if isinstance(locks, dict) else locks)
            body.append(
                f"<section class='scene' id='{_esc(scene)}'><h2>{_esc(scene)} · {_esc(_scene_label(prod, scene, shot.get('location_id')))}</h2>"
                f"<p class='dim'>{_esc(lock)}</p></section>"
            )
            last_scene = scene
            prev_in_scene = None
        badges = "".join(f"<em class='{'bad' if x == 'fail' else ''}'>{_esc(x)}</em>" for x in flags)
        light = shot.get("light") or {}
        light_s = " · ".join(filter(None, [_t(light.get("day_night")), _t(light.get("key_dir")), _t(light.get("quality")), _t(light.get("color"))]))
        sfx = "、".join(_t(x) for x in (shot.get("key_sfx") or []) if _t(x))
        cuts = _cuts(shot)
        stills = []
        if prev_in_scene:
            prev_sid = _t(prev_in_scene.get("shot_id"))
            prev_last = f"{folder}/{prev_sid}.jpg"
            if not (prod / prev_last).exists():
                prev_kf = frames.get(prev_sid) or {}
                prev_last = _t(prev_kf.get("first_frame_file")) or f"{folder}/{prev_sid}.jpg"
                cap = f"{prev_sid} 上镜首"
            else:
                cap = f"{prev_sid} 上镜首"
            stills.append(
                f"<div class='bridge'>"
                f"{_img(prev_last, cap, not (prod / prev_last).exists())}"
                f"{_img(first_rel, f'{sid} 本镜首', first_miss)}"
                f"</div>"
                f"<p class='join'>{_esc(prev_in_scene.get('out_to'))} → {_esc(shot.get('in_from'))}</p>"
            )
        if parent_rel:
            stills.append(_img(parent_rel, f"父图 {parent_rel}", not (prod / parent_rel).exists()))
        stills.append(_img(first_rel, f"{sid} 起幅", first_miss))
        if last_rel:
            stills.append(_img(last_rel, f"{sid} 落幅", last_miss))
        nit_html = f"<p class='{'bad' if is_fail else 'warn'}'>{_esc(status)}：{_esc(note)}</p>" if note else f"<p class='dim'>QC：{_esc(status)}</p>"
        state_line = state_sentence(shot.get("state"), bible) if isinstance(shot.get("state"), dict) else ""
        changes = "、".join(_t(c) for c in (shot.get("state_changes") or []) if _t(c))
        body.append(
            f"<article class='shot' id='{_esc(sid)}' data-nit='{1 if note else 0}' data-fail='{1 if is_fail else 0}' data-hard='{1 if shot.get('hardest') else 0}'>"
            f"<header><h3>{_esc(sid)} · {int(shot.get('duration_sec') or 0)}s · {_esc(shot.get('coverage_type'))} / {_esc(shot.get('scale'))}</h3>"
            f"<div class='badges'>{badges}<span class='dim'>{_esc(plan)}</span></div></header>"
            f"<div class='pair'><div class='stills'>{''.join(stills)}</div><div class='copy'>"
            f"{_row('状态', state_line + (f'（变：{changes}）' if changes else ''))}"
            f"{_row('任务', shot.get('shot_job'))}"
            f"{_row('一个动作', shot.get('one_action'))}"
            f"{_row('入', shot.get('in_from'))}"
            f"{_row('出', shot.get('out_to'))}"
            f"{_row('左', shot.get('left'))}"
            f"{_row('右', shot.get('right'))}"
            f"{_row('视线', shot.get('eyeline'))}"
            f"{_row('运镜', (shot.get('move_type') or '') + ('：' + _t(shot.get('move_reason')) if _t(shot.get('move_reason')) else ''))}"
            f"{_row('几何', ' · '.join(filter(None, [_t(shot.get('lens')), _t(shot.get('angle')), _t(shot.get('height'))])))}"
            f"{_row('光', light_s)}"
            f"{_row('对白', _dialogue(shot))}"
            f"{_row('音效', sfx)}"
            f"{_row('片内切', cuts)}"
            f"{_row('服装', (pkg.get('continuity') or {}).get('costume_state_id'))}"
            f"{nit_html}"
            f"</div></div></article>"
        )
        prev_in_scene = shot

    nit_line = "、".join(nits) if nits else "无"
    fail_line = "、".join(fails) if fails else "无"
    hard_line = "、".join(hardest) if hardest else "—"
    return f"""<!doctype html>
<html lang="zh">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · 关键帧审阅</title>
<style>
:root {{ --bg:#111; --card:#1c1c1c; --fg:#f3f1ea; --dim:#9a9588; --acc:#d4a44a; --warn:#e8b87a; --line:#2a2a2a; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:15px/1.45 -apple-system,BlinkMacSystemFont,sans-serif; background:var(--bg); color:var(--fg); }}
a {{ color:var(--acc); text-decoration:none; }}
.top {{ position:sticky; top:0; z-index:5; background:#111f; backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:16px 20px; }}
h1 {{ font-size:26px; font-weight:650; margin:0 0 6px; }}
h2 {{ font-size:18px; margin:8px 0 6px; color:var(--acc); }}
h3 {{ font-size:18px; margin:0; }}
.dim {{ color:var(--dim); }}
.warn {{ color:var(--warn); margin:10px 0 0; }}
.nav {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }}
.chip {{ display:inline-block; padding:4px 8px; border:1px solid var(--line); border-radius:8px; color:var(--fg); font-size:12px; }}
.chip.nit {{ border-color:var(--warn); color:var(--warn); }}
.chip.fail {{ border-color:#e06c5a; color:#e06c5a; }}
.chip.wait {{ border-color:#e8b87a; color:#e8b87a; }}
.chip.hard {{ border-color:var(--acc); }}
.bad {{ color:#e06c5a; }}
.badges em.bad {{ border-color:#e06c5a; color:#e06c5a; }}
.chip.on {{ background:var(--acc); color:#111; border-color:var(--acc); }}
.filters {{ display:flex; gap:8px; margin-top:10px; font-size:13px; }}
.filters button {{ background:transparent; color:var(--dim); border:1px solid var(--line); border-radius:8px; padding:4px 10px; cursor:pointer; }}
.filters button.on {{ color:var(--fg); border-color:var(--acc); }}
.scene {{ padding:28px 0 0; }}
.shot {{ background:var(--card); border-radius:12px; padding:16px; margin:16px 0 28px; }}
.shot header {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:12px; flex-wrap:wrap; }}
.badges {{ display:flex; gap:8px; align-items:center; font-size:12px; }}
.badges em {{ font-style:normal; border:1px solid var(--acc); color:var(--acc); padding:1px 6px; border-radius:6px; }}
.pair {{ display:grid; grid-template-columns:minmax(0,1.15fr) minmax(280px,0.85fr); gap:16px; }}
.stills {{ display:grid; gap:10px; }}
.bridge {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.join {{ color:var(--dim); font-size:13px; margin:0; }}
figure {{ margin:0; background:#000; border-radius:8px; overflow:hidden; }}
img {{ width:100%; aspect-ratio:16/9; object-fit:contain; display:block; background:#000; cursor:zoom-in; }}
figcaption {{ padding:6px 10px 10px; font-size:12px; color:var(--dim); background:var(--card); }}
.ph {{ aspect-ratio:16/9; display:flex; align-items:center; justify-content:center; color:var(--warn); }}
.kv {{ display:grid; grid-template-columns:4.5em 1fr; gap:8px; padding:5px 0; border-bottom:1px solid var(--line); font-size:13px; }}
.kv span {{ color:var(--dim); }}
.kv b {{ font-weight:500; }}
.lightbox {{ display:none; position:fixed; inset:0; background:#000d; z-index:9; align-items:center; justify-content:center; padding:24px; }}
.lightbox.on {{ display:flex; }}
.lightbox img {{ max-width:100%; max-height:100%; width:auto; height:auto; aspect-ratio:auto; cursor:zoom-out; }}
@media (max-width:900px) {{ .pair {{ grid-template-columns:1fr; }} }}
body.filter-nit .shot:not([data-nit="1"]) {{ display:none; }}
body.filter-fail .shot:not([data-fail="1"]) {{ display:none; }}
body.filter-hard .shot:not([data-hard="1"]) {{ display:none; }}
</style>
<body>
<div class="top"><div class="wrap">
  <p class="dim">{_esc(prod.name)} · {len(shots)} 镜 / {total} 秒 · 16:9 · Seedance 2.0 · 未出视频 · keyframes.json {_esc(kf_status)} · 审核人 {_esc(reviewed_by)}</p>
  <h1>{_esc(title)}</h1>
  <p>同场衔接：上镜尾｜本镜首，并写出 → 入。其下是父图 → 起幅 → 落幅。右侧是镜头表。「状态」一行是这一帧必须照做的连戏。最难：{_esc(hard_line)}。待重出：{_esc(fail_line)}。放过的 nits：{_esc(nit_line)}。</p>
  <div class="filters">
    <button class="on" data-filter="all">全部</button>
    <button data-filter="fail">待重出</button>
    <button data-filter="nit">放过的 nits</button>
    <button data-filter="hard">最难三镜</button>
  </div>
  <nav class="nav">{''.join(nav)}</nav>
</div></div>
<main class="wrap">
{''.join(body)}
</main>
<div class="lightbox" id="lb"><img alt=""></div>
<script>
const lb = document.getElementById('lb');
document.querySelectorAll('.stills img').forEach(img => {{
  img.addEventListener('click', () => {{ lb.querySelector('img').src = img.src; lb.classList.add('on'); }});
}});
lb.addEventListener('click', () => lb.classList.remove('on'));
document.querySelectorAll('.filters button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filters button').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    document.body.classList.remove('filter-nit', 'filter-fail', 'filter-hard');
    if (btn.dataset.filter === 'nit') document.body.classList.add('filter-nit');
    if (btn.dataset.filter === 'fail') document.body.classList.add('filter-fail');
    if (btn.dataset.filter === 'hard') document.body.classList.add('filter-hard');
  }});
}});
const shots = [...document.querySelectorAll('article.shot')];
function visibleShots() {{
  return shots.filter(el => getComputedStyle(el).display !== 'none');
}}
document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') lb.classList.remove('on');
  if (e.key !== 'j' && e.key !== 'k') return;
  const vis = visibleShots();
  const here = vis.findIndex(el => el.getBoundingClientRect().top >= 80);
  const idx = Math.max(0, here);
  const next = e.key === 'j' ? vis[Math.min(vis.length - 1, idx + (vis[idx] && vis[idx].getBoundingClientRect().top < 120 ? 1 : 0))] : vis[Math.max(0, idx - 1)];
  next?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
}});
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", default="productions/009-siem-reap", help="production path or slug (default still 009)")
    parser.add_argument("--episode", type=int, default=1)
    args = parser.parse_args()
    prod_arg = Path(args.prod).expanduser()
    prod = prod_arg if prod_arg.exists() else productions_root() / args.prod
    prod = prod.resolve()
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")
    dest = prod / ("REVIEW.html" if int(args.episode) == 1 else f"REVIEW.ep{int(args.episode):02d}.html")
    dest.write_text(render(prod, args.episode), encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
