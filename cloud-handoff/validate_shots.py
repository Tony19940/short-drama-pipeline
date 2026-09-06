#!/usr/bin/env python3
"""云端分镜合同校验器 · 单文件、零依赖、可直接放进云端流程。

为什么需要它：80 集 × 约 10 镜 = 约 800 镜。人工逐镜过关卡在这个量级上不可能，
所以「导演层规则」必须能被机器执行，否则规则只是文档里的愿望。

它一次报出全部问题（不是遇错即停），因为无人守流程需要一轮修完。

  python3 validate_shots.py --sets sets.json --shots Episode1_shots.json
  python3 validate_shots.py --sets sets.json --shots ep01.json --warn-as-error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SETUPS = {"master", "close", "ots", "insert", "single"}
MOVES = {"static", "push", "pull", "pan", "track"}
AXES = {"left", "right", "center"}
SCALES = {"wide", "full", "med", "close", "insert"}
CUTS = {"continue", "hard"}
LINE_KINDS = {"narration", "dialogue", "sms"}
FRAME_SOURCES = {"blocking", "designed_frame", "last_frame"}
LENS_RE = re.compile(r"^\d{2,3}mm$")

REQUIRED = (
    "id", "scene", "seconds", "setup", "scale", "move", "axis", "lens",
    "cut", "from", "derived_from", "first_frame_source", "characters",
    "new_info", "line", "line_kind", "caption", "camera", "action", "look",
    "video_prompt", "negatives",
)

MOVE_TERMS = {
    "static": ("static", "locked off", "locked-off", "locked camera", "fixed",
               "no camera move", "handheld breath", "faint handheld", "hold still"),
    "push": ("push in", "push-in", "slow push", "dolly in"),
    "pull": ("pull out", "pull-out", "slow pull", "dolly out", "pull back"),
    "pan": ("pan left", "pan right", "pan across", "pan "),
    "track": ("track", "tracking", "lateral dolly", "follow"),
}
BANNED_CAMERA = ("orbit", "circle around", "around the subject", "crash zoom",
                 "whip pan", "crosses the 180", "crossing the 180", "break the 180")
# 每镜 negatives 必须至少覆盖这几类，缺一类就是给模型留了默认行为的口子
REQUIRED_NEGATIVES = {
    "orbit": ("orbit",),
    "crash zoom": ("crash zoom",),
    "face drift": ("face drift",),
    "clothing change": ("clothing change", "outfit change"),
    "captions": ("caption", "subtitle", "text"),
}
LIGHT_WORDS = (
    # look 两边都可能用中文写，所以中英都要认，否则校验器会误杀
    "light", "lit", "lamp", "fluorescent", "sodium", "neon", "daylight",
    "backlit", "silhouette", "shadow", "glow", "candle", "moonlight",
    "sunlight", "tungsten", "practical", "kelvin", "overcast",
    "光", "灯", "荧光", "钠灯", "暖黄", "冷白", "逆光", "剪影", "阴影",
    "色温", "烛", "月光", "日光", "阳光", "反光",
)

PUSH_SHARE_CAP = 0.40
# 已锁定的单集规格（2026-08-24）。80 集必须一致，否则总时长和成本失控。
EPISODE_SECONDS = (60, 75)
EPISODE_SHOTS = (8, 10)


# 旧字段 → 新字段。迁移问题和导演层问题必须分开报，
# 否则几百条改名噪声会把真正的结构缺陷淹掉。
ALIASES = {"duration": "seconds"}

CATEGORIES = ("MIGRATION", "SCHEMA", "ASSET", "GRAPH", "PROMPT", "RHYTHM")


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str, str]] = []  # (level, category, where, msg)

    def err(self, where: str, msg: str, cat: str = "SCHEMA") -> None:
        self.items.append(("ERROR", cat, where, msg))

    def warn(self, where: str, msg: str, cat: str = "SCHEMA") -> None:
        self.items.append(("WARN", cat, where, msg))

    def count(self, level: str) -> int:
        return sum(1 for lv, _, _, _ in self.items if lv == level)

    def render(self) -> str:
        out: list[str] = []
        for level in ("ERROR", "WARN"):
            rows = [it for it in self.items if it[0] == level]
            if not rows:
                continue
            label = "ERROR（必须修）" if level == "ERROR" else "WARN（建议修）"
            out.append(f"\n=== {label} ===")
            for cat in CATEGORIES:
                cat_rows = [it for it in rows if it[1] == cat]
                if not cat_rows:
                    continue
                out.append(f"\n  [{cat}]")
                # 同一条信息命中多镜时折叠成一行，可读性远好于逐镜重复
                grouped: dict[str, list[str]] = {}
                order: list[str] = []
                for _, _, where, msg in cat_rows:
                    if msg not in grouped:
                        grouped[msg] = []
                        order.append(msg)
                    grouped[msg].append(where)
                for msg in order:
                    wheres = grouped[msg]
                    if len(wheres) > 3:
                        tag = f"{wheres[0]}…{wheres[-1]}（{len(wheres)} 镜）"
                    else:
                        tag = "、".join(wheres)
                    mark = "✗" if level == "ERROR" else "!"
                    out.append(f"    {mark} {tag}: {msg}")
        return "\n".join(out)


def normalize(shot: dict, rep: Report) -> dict:
    """把已知旧字段名迁移过来，迁移动作单独记账。"""
    sid = str(shot.get("id") or "?")
    out = dict(shot)
    for old, new in ALIASES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
            rep.err(sid, f"字段 `{old}` 应改名为 `{new}`", cat="MIGRATION")
    return out


def _blob(shot: dict) -> str:
    return " ".join(
        str(shot.get(k) or "") for k in ("camera", "video_prompt")
    ).lower()


def _has(text: str, terms) -> bool:
    return any(t in text for t in terms)


def _has_unnegated(text: str, terms) -> bool:
    """命中且前面没有 no/not/without —— 用来区分「禁止环绕」和「要环绕」。"""
    padded = " " + text + " "
    for term in terms:
        start = 0
        while True:
            i = padded.find(term, start)
            if i < 0:
                break
            if not re.search(r"\b(no|not|without|avoid)\s+$", padded[max(0, i - 10):i]):
                return True
            start = i + len(term)
    return False


def negatives_text(shot: dict) -> str:
    neg = shot.get("negatives")
    if isinstance(neg, list):
        return ", ".join(str(x) for x in neg).lower()
    return str(neg or "").lower()


def check_shot_fields(shot: dict, sets: dict, rep: Report) -> None:
    sid = str(shot.get("id") or "?")
    for field in REQUIRED:
        if field not in shot:
            rep.err(sid, f"缺字段 `{field}`")

    if shot.get("setup") not in SETUPS:
        rep.err(sid, f"setup={shot.get('setup')!r} 必须是 {sorted(SETUPS)}（枚举，不是自由文本）")
    if shot.get("move") not in MOVES:
        rep.err(sid, f"move={shot.get('move')!r} 必须是 {sorted(MOVES)} 之一，且只能一个（一镜一个运动）")
    if shot.get("axis") not in AXES:
        rep.err(sid, f"axis={shot.get('axis')!r} 必须是 {sorted(AXES)}。轴线是机位在 180 度线哪一侧，不是镜头微偏")
    if shot.get("scale") not in SCALES:
        rep.err(sid, f"scale={shot.get('scale')!r} 必须是 {sorted(SCALES)}")
    if shot.get("cut") not in CUTS:
        rep.err(sid, f"cut={shot.get('cut')!r} 必须是 {sorted(CUTS)}")
    if shot.get("line_kind") not in LINE_KINDS:
        rep.err(sid, f"line_kind={shot.get('line_kind')!r} 必须是 {sorted(LINE_KINDS)}")
    if shot.get("first_frame_source") not in FRAME_SOURCES:
        rep.err(sid, f"first_frame_source={shot.get('first_frame_source')!r} 必须是 {sorted(FRAME_SOURCES)}")
    if not LENS_RE.match(str(shot.get("lens") or "")):
        rep.err(sid, f"lens={shot.get('lens')!r} 必须形如 35mm / 50mm / 85mm")

    scene = str(shot.get("scene") or "")
    if scene and scene not in sets:
        rep.err(sid, f"scene={scene!r} 不在 sets 注册表里；没有舞台不准写镜头")

    secs = shot.get("seconds")
    if not isinstance(secs, int) or not (1 <= secs <= 15):
        rep.err(sid, f"seconds={secs!r} 必须是 1–15 的整数")
    else:
        segs = shot.get("segments") or []
        if secs > 6 and not segs:
            rep.err(sid, f"{secs}s 超过画布 6s 上限，必须给 segments 拆同轴续段")
        if secs <= 6 and segs:
            rep.err(sid, f"{secs}s 不需要拆段，segments 应为空（拆段只为绕开 6s 上限）")
        if segs:
            total = sum(int(s.get("seconds") or 0) for s in segs)
            if total != secs:
                rep.err(sid, f"segments 合计 {total}s ≠ seconds {secs}s")
            for s in segs:
                for f in ("lens", "axis", "setup", "move", "look"):
                    if f in s and str(s[f]) != str(shot.get(f)):
                        rep.err(sid, f"段 {s.get('id')} 的 {f} 与母镜不一致；拆的是生成单元不是剪辑点")

    if not (shot.get("characters") is None or isinstance(shot.get("characters"), list)):
        rep.err(sid, "characters 必须是数组")

    if not str(shot.get("new_info") or "").strip():
        rep.err(sid, "new_info 为空：这几秒观众新知道的一件事必须写出来，否则无法判断剧情有没有推进")

    look = str(shot.get("look") or "").lower()
    if look and not _has(look, LIGHT_WORDS):
        rep.err(sid, "look 里没有任何光线描述。look 是物理连续性（光位/景深/站位），不是情绪形容词；"
                     "光位不写死，同场相邻镜就会变色温", cat="PROMPT")

    vp = str(shot.get("video_prompt") or "")
    if len(vp.strip()) < 80:
        rep.err(sid, f"video_prompt 只有 {len(vp.strip())} 字符，太薄，指导不了视频模型", cat="PROMPT")

    neg = negatives_text(shot)
    missing = [k for k, terms in REQUIRED_NEGATIVES.items() if not _has(neg, terms)]
    if missing:
        rep.err(sid, "negatives 缺少必禁项：" + "、".join(missing), cat="PROMPT")

    blob = _blob(shot)
    if _has_unnegated(blob, BANNED_CAMERA):
        rep.err(sid, "camera/video_prompt 里出现环绕或跳轴动作", cat="PROMPT")

    move = shot.get("move")
    if move in MOVES:
        if not _has(blob, MOVE_TERMS[move]):
            rep.err(sid, f"move={move} 但 camera/video_prompt 里没有对应运镜措辞", cat="PROMPT")
        if move == "static":
            others = [m for m in ("push", "pull", "pan", "track") if _has_unnegated(blob, MOVE_TERMS[m])]
            if others:
                rep.err(sid, f"move=static 但措辞里含 {'/'.join(others)} 运动", cat="PROMPT")

    line = str(shot.get("line") or "").strip()
    if line:
        norm = re.sub(r"[\s\"'.,!?;:]", "", line).lower()
        for field in ("video_prompt", "action"):
            target = re.sub(r"[\s\"'.,!?;:]", "", str(shot.get(field) or "")).lower()
            if len(norm) > 8 and norm in target:
                rep.err(sid, f"台词泄漏进 {field}；对白只能待在 line/caption，"
                             "否则一边叫模型说话一边禁 lip-sync，自相矛盾", cat="PROMPT")


def check_graph(shots: list[dict], sets: dict, rep: Report) -> None:
    by_id = {s.get("id"): s for s in shots}
    seen: list[str] = []
    scene_setups: dict[str, set] = {}

    for idx, shot in enumerate(shots):
        sid = str(shot.get("id") or f"#{idx}")
        scene = str(shot.get("scene") or "")
        prev = shots[idx - 1] if idx > 0 else None
        prev_scene = str((prev or {}).get("scene") or "")
        cut = shot.get("cut")
        frm = shot.get("from")
        derived = str(shot.get("derived_from") or "")
        src = shot.get("first_frame_source")

        scene_setups.setdefault(scene, set()).add(shot.get("setup"))

        # 换场必须硬切
        if prev is not None and scene != prev_scene and cut != "hard":
            rep.err(sid, f"从 {prev_scene} 换到 {scene} 却写 cut={cut}；换场必须硬切。"
                         "跨场用末帧续等于让模型凭一张无关的脸凭空造出新空间", cat="GRAPH")
        if prev is not None and scene == prev_scene and cut == "hard":
            rep.warn(sid, f"同场 {scene} 内用了硬切；硬切原则上只用于换场", cat="GRAPH")

        if cut == "hard":
            if frm not in (None, ""):
                rep.err(sid, f"cut=hard 不该有 from（现在是 {frm!r}）", cat="GRAPH")
            want = f"{scene}.blocking"
            if derived != want:
                rep.err(sid, f"cut=hard 时 derived_from 必须是 {want!r}，现在是 {derived!r}", cat="GRAPH")
            if src != "blocking":
                rep.err(sid, f"cut=hard 时 first_frame_source 必须是 blocking，现在是 {src!r}", cat="GRAPH")
        elif cut == "continue":
            if not frm:
                rep.err(sid, "cut=continue 必须写 from", cat="GRAPH")
            elif frm not in by_id:
                rep.err(sid, f"from={frm!r} 不存在", cat="GRAPH")
            elif frm not in seen:
                rep.err(sid, f"from={frm!r} 不在本镜之前，图有环或顺序错", cat="GRAPH")
            else:
                parent = by_id[frm]
                if str(parent.get("scene") or "") != scene:
                    rep.err(sid, f"from={frm} 在 {parent.get('scene')}，本镜在 {scene}；"
                                 "continue 的父镜必须同场")
                # 判据是「本镜首帧需要的人，父镜末帧里有没有」。
                # 不是「有没有交集」—— 交集非空但缺了某个人，那个人一样会被凭空造出来。
                # `enters` 里的人在本镜过程中入画，首帧不需要有他们。
                here = set(shot.get("characters") or [])
                enters = set(shot.get("enters") or [])
                there = set(parent.get("characters") or [])
                needed = here - enters
                missing = needed - there
                if missing and src == "last_frame":
                    rep.err(sid, f"首帧需要 {sorted(needed)}，但父镜 {frm} 的末帧里没有 {sorted(missing)} —— "
                                 "吃末帧只能让模型凭空造脸，这正是角色漂移的来源。"
                                 f"改用 designed_frame；若 {sorted(missing)} 是在本镜过程中入画，"
                                 "请写进 `enters`", cat="GRAPH")
                if not missing and src == "designed_frame":
                    rep.warn(sid, f"父镜 {frm} 末帧已含首帧所需的人，本可吃末帧却用了设计首帧；"
                                  "连续性会略差。确认是有意为之（比如要换构图）再保留", cat="GRAPH")
                if derived not in (frm, f"{scene}.blocking"):
                    rep.err(sid, f"derived_from={derived!r} 应是 {frm!r} 或 {scene}.blocking", cat="GRAPH")

        # 同场同 setup+scale+朝向 连排
        if prev is not None and scene == prev_scene:
            same = all(
                shot.get(k) == prev.get(k) for k in ("setup", "scale", "facing")
            )
            if same:
                rep.err(sid, f"与 {prev.get('id')} 同场同 setup/scale/facing 连排，等于同一张海报连播两次", cat="GRAPH")

        seen.append(sid)

    for scene, setups in scene_setups.items():
        if "master" not in setups:
            rep.err(f"scene:{scene}", "这一场没有 master：观众不知道谁在哪，地理没建立", cat="GRAPH")
        if setups <= {"master"}:
            rep.err(f"scene:{scene}", "这一场只有 master，没有更紧的机位打情绪", cat="GRAPH")

    if shots:
        first = shots[0]
        if not (first.get("characters") or []):
            rep.err(str(first.get("id")), "开场镜没有人物。竖屏短剧前 3 秒决定留存，"
                                          "不能用空景建立镜头开场；且后一镜无法从无人的末帧续出人")


def check_rhythm(shots: list[dict], rep: Report) -> None:
    if not shots:
        return
    n = len(shots)
    pushes = [s for s in shots if s.get("move") == "push"]
    share = len(pushes) / n
    if share > PUSH_SHARE_CAP:
        rep.err("rhythm", f"{len(pushes)}/{n} 镜是 push（{share:.0%}），超过上限 {PUSH_SHARE_CAP:.0%}。"
                          "整集一直在慢推 = 没有节奏对比，这是继环绕之后第二明显的 AI 味。"
                          "改法：把一部分推镜换成固定长镜或拉镜")
    if not any(s.get("move") == "pull" for s in shots):
        longest = max(int(s.get("seconds") or 0) for s in shots)
        if longest < 8:
            rep.warn("rhythm", "全集既没有拉镜，也没有 ≥8s 的长镜；观众没有一次换气的地方", cat="RHYTHM")

    by_scene: dict[str, list[dict]] = {}
    for s in shots:
        by_scene.setdefault(str(s.get("scene") or ""), []).append(s)
    for scene, group in by_scene.items():
        if not any(s.get("move") == "static" for s in group):
            rep.warn(f"scene:{scene}", "这一场没有一个真正固定的镜头；镜头永远在动，观众无处落眼", cat="RHYTHM")

    total = sum(int(s.get("seconds") or 0) for s in shots)
    lo, hi = EPISODE_SECONDS
    if not (lo <= total <= hi):
        rep.err("rhythm", f"全集 {total}s，超出已锁定的 {lo}–{hi}s。"
                          f"{'太短装不下「一场冲突 + 一个钩子」的完整节拍' if total < lo else '竖屏留存不友好，且 80 集成本翻倍'}",
                cat="RHYTHM")
    slo, shi = EPISODE_SHOTS
    if not (slo <= n <= shi):
        rep.err("rhythm", f"{n} 镜，超出已锁定的 {slo}–{shi} 镜。"
                          f"{'覆盖不够，观众看不清谁在哪' if n < slo else '切得太碎；每一刀都是一次让模型重新想象场景的机会'}",
                cat="RHYTHM")
    durs = [int(s.get("seconds") or 0) for s in shots]
    if durs and max(durs) - min(durs) <= 2:
        rep.warn("rhythm", f"镜长全挤在 {min(durs)}–{max(durs)}s，长短没有交错，剪辑会显得机械均分", cat="RHYTHM")


def check_assets(shots: list[dict], assets: dict, rep: Report) -> None:
    """分镜 ↔ 资产注册表交叉校验。

    80 集独立生产最怕的是分镜引用了不存在的资产：脚本不会报错，模型会默默
    凭空造一个人或一个空间，等成片出来才发现。这一层把它变成开工前的硬错误。
    """
    chars = assets.get("characters") or {}
    scenes = assets.get("scenes") or {}

    # 每个角色能不能取到「脸」参考。画布编辑节点上限 3 张、脸优先，
    # 所以近景必须有专门的脸图，用全身图顶替会让脸糊。
    def face_of(slug: str) -> str:
        c = chars.get(slug) or {}
        for key in ("root_face", "face", "root", "root_full", "master"):
            if c.get(key):
                return key
        return ""

    used_chars: set[str] = set()
    for shot in shots:
        sid = str(shot.get("id") or "?")
        for slug in list(shot.get("characters") or []) + list(shot.get("enters") or []):
            used_chars.add(slug)
            if slug not in chars:
                rep.err(sid, f"角色 {slug!r} 不在资产注册表里；模型会凭空造一个人", cat="ASSET")
            elif not face_of(slug):
                rep.err(sid, f"角色 {slug!r} 在注册表里但没有任何可用主图", cat="ASSET")
            elif shot.get("setup") in ("close", "ots") and face_of(slug) not in ("root_face", "face"):
                rep.warn(sid, f"{setup_label(shot)}用到 {slug!r}，但它只有 {face_of(slug)} 没有专门的脸图；"
                              "近景用全身图当参考，脸会糊", cat="ASSET")

        scene = str(shot.get("scene") or "")
        if scene and scene not in scenes:
            rep.err(sid, f"场景 {scene!r} 不在资产注册表里", cat="ASSET")
        elif scene:
            entry = scenes.get(scene) or {}
            if not entry.get("blocking"):
                rep.err(f"scene:{scene}", "注册表里这一场没有 blocking —— "
                                          "没有舞台不准写镜头，首帧也无处派生", cat="ASSET")
            if not entry.get("master"):
                rep.err(f"scene:{scene}", "注册表里这一场没有空镜 master", cat="ASSET")

    # 双人以上同框必须有身高图，模型不会自己记住谁高
    if not (assets.get("scale") or assets.get("scales")):
        pairs = {
            tuple(sorted(set(s.get("characters") or [])))
            for s in shots
            if len(set(s.get("characters") or [])) > 1
        }
        if pairs:
            listed = "；".join("+".join(p) for p in sorted(pairs))
            rep.err("assets", f"有 {len(pairs)} 组双人以上同框（{listed}），"
                              "但注册表没有 scale 身高图。相对身高必须先锁，"
                              "否则同一集里人物身高会跳", cat="ASSET")

    # 脸图和全身图不能是同一张：近景要紧脸裁切，全身要管服装和身形
    same = [s for s, c in chars.items()
            if c.get("root_face") and c.get("root_face") == c.get("root_full")]
    if same:
        rep.warn("assets", f"{'、'.join(same)} 的 root_face 和 root_full 是同一个 UUID。"
                           "近景要的是紧脸裁切，全身要管服装和身形，一张顶两用会两头都弱",
                 cat="ASSET")

    # 键名不统一会让「取脸参考」这一步无法自动化
    no_face_key = sorted(s for s in chars if not (chars[s].get("root_face") or chars[s].get("face")))
    if no_face_key:
        rep.warn("assets", f"{len(no_face_key)} 个角色没有 root_face 键（只有 root）："
                           f"{'、'.join(no_face_key)}。键名不统一，"
                           "「脸优先挂参考图」这一步无法自动化", cat="ASSET")

    # 全剧核心道具必须锁资产，否则每集长得都不一样
    props = assets.get("props") or {}
    if not props:
        rep.err("assets", "注册表没有 props。银铃是贯穿 80 集的身份信物"
                          "（第 12 集要两半合上、断口严丝合缝），不锁成资产做不到", cat="ASSET")


def setup_label(shot: dict) -> str:
    return {"close": "近景", "ots": "过肩"}.get(str(shot.get("setup")), "本镜")


def main() -> None:
    p = argparse.ArgumentParser(description="云端分镜合同校验（Gate C2 等价物）")
    p.add_argument("--shots", required=True)
    p.add_argument("--sets", help="sets 注册表；缺省则跳过舞台校验")
    p.add_argument("--assets", help="资产注册表；给了才做分镜↔资产交叉校验")
    p.add_argument("--warn-as-error", action="store_true")
    args = p.parse_args()

    data = json.loads(Path(args.shots).read_text(encoding="utf-8"))
    shots = data.get("shots") or []
    sets: dict = {}
    if args.sets and Path(args.sets).exists():
        raw = json.loads(Path(args.sets).read_text(encoding="utf-8"))
        sets = {s["id"]: s for s in raw.get("sets", [])}

    rep = Report()
    # 自报总长必须和逐镜合计一致。声明和事实不符会让节奏检查失去意义。
    declared = data.get("seconds_total")
    if declared is not None:
        actual = sum(int(s.get("seconds") or s.get("duration") or 0) for s in shots)
        if int(declared) != actual:
            rep.err("meta", f"seconds_total 声明 {declared}s，逐镜合计 {actual}s，差 {int(declared) - actual}s。"
                            "以逐镜为准", cat="SCHEMA")
    if not sets:
        rep.err("sets", "没有 sets 注册表。一场一条轴、每场一张 blocking 是分镜的前提；"
                        "没有舞台，axis 和换场硬切都无法校验", cat="GRAPH")

    shots = [normalize(s, rep) for s in shots]
    for shot in shots:
        check_shot_fields(shot, sets, rep)
    check_graph(shots, sets, rep)
    check_rhythm(shots, rep)
    if args.assets and Path(args.assets).exists():
        check_assets(shots, json.loads(Path(args.assets).read_text(encoding="utf-8")), rep)

    total = sum(int(s.get("seconds") or 0) for s in shots)
    moves: dict[str, int] = {}
    for s in shots:
        moves[str(s.get("move"))] = moves.get(str(s.get("move")), 0) + 1
    print(f"镜头 {len(shots)} 个，总长 {total}s")
    print("运镜配比：" + "、".join(f"{k}×{v}" for k, v in sorted(moves.items(), key=lambda x: -x[1])))
    print(f"ERROR {rep.count('ERROR')} 条 / WARN {rep.count('WARN')} 条")
    body = rep.render()
    if body:
        print(body)
    else:
        print("\n全部通过。")

    bad = rep.count("ERROR") or (rep.count("WARN") and args.warn_as_error)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
