"""Multi-candidate shot design + director critic.

Every scene is designed N ways (coverage / point-of-view / long-take), each version
passes the same machine validation, then a critic scores them against the scene
card and picks one. Humans can swap the pick later; nothing is thrown away.
"""

from __future__ import annotations

from typing import Any, Optional

from .direction import candidate_metrics, normalize_scene_card

STYLES: list[dict[str, str]] = [
    {
        "id": "coverage",
        "label": "覆盖派",
        "brief": "常规覆盖：先 master 交代地理，再正反打，每句对白后给反应。稳，不冒险。",
        "temperature": "0.3",
    },
    {
        "id": "pov",
        "label": "主观派",
        "brief": "以主视点人物的眼睛拆：多 POV 与她看见的东西，少客观反打；观众只知道她知道的。揭示顺序按场卡逐字执行。",
        "temperature": "0.45",
    },
    {
        "id": "long_take",
        "label": "少切派",
        "brief": "刀少一半：靠机位内的调度和一次运镜完成转折；只在场卡的翻转点和那一颗处开新镜。默认不片内切。对模型更险，每镜写清为什么不切。",
        "temperature": "0.4",
    },
]

RUBRIC: dict[str, str] = {
    "reveal_order": "揭示顺序是否和场卡一致：观众先看见什么、后看见什么",
    "the_shot": "场卡说的那一颗有没有落地，且是全场最紧、最慢、最清楚的一颗",
    "rhythm": "景别曲线有起伏，不平线，高潮后有回落",
    "silence": "静音看一遍，这场的变化仍在画面里",
    "card_fit": "距离策略、光的动机、色彩变化是否被镜头承接",
    "continuity": "左右、视线、状态机、道具跨度没有破绽",
    "model_risk": "对目标视频模型的风险：长镜多手部动作、一镜换机位/片内切（默认不允许）、运镜超能力档",
}
RUBRIC_KEYS = tuple(RUBRIC)


def _t(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def styles_for(count: int) -> list[dict[str, str]]:
    count = max(1, int(count or 1))
    if count <= len(STYLES):
        return [dict(s) for s in STYLES[:count]]
    out = [dict(s) for s in STYLES]
    for extra in range(len(STYLES), count):
        out.append({"id": f"variant_{extra + 1}", "label": f"变体 {extra + 1}", "brief": "自由拆法，但仍服从场卡。", "temperature": "0.5"})
    return out


def candidate_summary(candidate: dict, card: Optional[dict]) -> dict:
    """What the critic and the compare page see about one candidate; no prompts, no files."""
    shots = list(candidate.get("shots") or [])
    metrics = candidate_metrics(shots, card, candidate.get("warnings") or [])
    return {
        "index": candidate.get("index"),
        "style": candidate.get("style"),
        "label": candidate.get("label"),
        "metrics": metrics,
        "warnings": list(candidate.get("warnings") or [])[:12],
        "shots": [
            {
                "shot_id": s.get("shot_id"),
                "beat": s.get("beat"),
                "shot_job": s.get("shot_job"),
                "coverage_type": s.get("coverage_type"),
                "scale": s.get("scale"),
                "angle": s.get("angle"),
                "lens": s.get("lens"),
                "move_type": s.get("move_type"),
                "move_reason": s.get("move_reason"),
                "left": s.get("left"),
                "right": s.get("right"),
                "eyeline": s.get("eyeline"),
                "one_action": s.get("one_action"),
                "duration_sec": s.get("duration_sec"),
                "dialogue_ref": s.get("dialogue_ref"),
                "in_from": s.get("in_from"),
                "out_to": s.get("out_to"),
                "visual_turn": s.get("visual_turn"),
                "hardest": s.get("hardest"),
                "emotion_level": s.get("emotion_level"),
                "evidence": s.get("evidence"),
                "state_note": ((s.get("state") or {}).get("note") if isinstance(s.get("state"), dict) else ""),
            }
            for s in shots
        ],
    }


def deterministic_pick(candidates: list[dict], card: Optional[dict]) -> int:
    """No critic available: fewest warnings, then the shot landed & tightest, then the widest scale span."""
    if not candidates:
        return 0

    def key(item: dict) -> tuple:
        metrics = candidate_metrics(list(item.get("shots") or []), card, item.get("warnings") or [])
        return (
            len(item.get("warnings") or []),
            0 if metrics.get("the_shot_landed") else 1,
            0 if metrics.get("the_shot_tightest") else 1,
            -int(metrics.get("scale_span") or 0),
            -int(metrics.get("reactions_after_dialogue") or 0),
        )

    best = min(range(len(candidates)), key=lambda i: key(candidates[i]))
    return best


def critic_errors(verdict: Any, count: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(verdict, dict):
        return ["critic must return an object"]
    scores = verdict.get("scores")
    if not isinstance(scores, list) or len(scores) != count:
        errors.append(f"critic scores must list all {count} candidates")
        return errors
    seen: set[int] = set()
    for item in scores:
        if not isinstance(item, dict):
            errors.append("score entry must be an object")
            continue
        idx = item.get("candidate")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            errors.append("score.candidate must be an index")
            continue
        if idx < 0 or idx >= count or idx in seen:
            errors.append(f"score.candidate {idx} out of range or duplicated")
        seen.add(idx)
        dims = item.get("dims") if isinstance(item.get("dims"), dict) else {}
        for key in RUBRIC_KEYS:
            value = dims.get(key)
            if value is None:
                errors.append(f"candidate {idx} missing dims.{key}")
            elif _num(value, -1) < 0 or _num(value, 11) > 10:
                errors.append(f"candidate {idx} dims.{key} must be 0–10")
        if not _t(item.get("notes")):
            errors.append(f"candidate {idx} needs notes: what works, what breaks")
    pick = verdict.get("pick")
    try:
        pick = int(pick)
    except (TypeError, ValueError):
        errors.append("critic pick must be an index")
        return errors
    if pick < 0 or pick >= count:
        errors.append("critic pick out of range")
    if not _t(verdict.get("why")):
        errors.append("critic must say why it picked")
    return errors


def normalize_verdict(verdict: dict, count: int) -> dict:
    scores = []
    for item in verdict.get("scores") or []:
        dims = {key: round(_num((item.get("dims") or {}).get(key)), 1) for key in RUBRIC_KEYS}
        scores.append({
            "candidate": int(item.get("candidate")),
            "total": round(sum(dims.values()), 1),
            "dims": dims,
            "notes": _t(item.get("notes")),
            "fixes": [_t(f) for f in (item.get("fixes") or []) if _t(f)],
        })
    scores.sort(key=lambda s: s["candidate"])
    return {
        "pick": int(verdict.get("pick")),
        "why": _t(verdict.get("why")),
        "merge": _t(verdict.get("merge")),
        "scores": scores,
        "source": "critic",
    }


def fallback_verdict(candidates: list[dict], card: Optional[dict], reason: str) -> dict:
    pick = deterministic_pick(candidates, card)
    return {
        "pick": pick,
        "why": f"机器兜底：{reason}。按警告数、那一颗是否落地、景别跨度挑了第 {pick + 1} 版。",
        "merge": "",
        "scores": [],
        "source": "deterministic",
    }


def render_candidates_md(scene_rows: list[dict], title: str = "") -> str:
    """Side-by-side compare page: one block per scene, one column per candidate, critic verdict under it."""
    lines: list[str] = [f"# 拆镜候选对比 · {title or '第 01 集'}", ""]
    lines.append("每场 N 版并排。机器校验都过；评审 Agent 打分并挑一版，人可以改选。正式表只收被选的那版。")
    lines.append("")
    for row in scene_rows:
        sid = _t(row.get("scene_id"))
        card = normalize_scene_card(row.get("scene_card")) if row.get("scene_card") else None
        candidates = list(row.get("candidates") or [])
        verdict = row.get("verdict") or {}
        pick = int(verdict.get("pick", row.get("pick", 0)) or 0)
        lines.append(f"## {sid}")
        lines.append("")
        if card:
            lines.append(f"- 那一颗：{card['the_shot']['moment']}（{card['the_shot']['scale'] or '—'}）")
            lines.append(f"- 揭示顺序：{' → '.join(card['reveal_order'])}")
            lines.append("")
        header = ["项"] + [f"{'★ ' if i == pick else ''}{i + 1} {_t(c.get('label') or c.get('style'))}" for i, c in enumerate(candidates)]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        metric_rows = (
            ("镜数", "shots"),
            ("总秒", "total_sec"),
            ("景别曲线", "scale_curve"),
            ("最紧", "tightest"),
            ("静止比", "static_ratio"),
            ("对白后反应", "reactions_after_dialogue"),
            ("那一颗落地", "the_shot_landed"),
            ("那一颗最紧", "the_shot_tightest"),
            ("警告数", "warnings"),
        )
        metrics = [candidate_metrics(list(c.get("shots") or []), card, c.get("warnings") or []) for c in candidates]
        for label, key in metric_rows:
            cells = []
            for m in metrics:
                value = m.get(key)
                if value is None:
                    cells.append("—")
                elif isinstance(value, bool):
                    cells.append("是" if value else "否")
                else:
                    cells.append(str(value))
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        scores = {int(s.get("candidate")): s for s in (verdict.get("scores") or []) if isinstance(s, dict)}
        if scores:
            for key in RUBRIC_KEYS:
                lines.append(f"| 评审·{key} | " + " | ".join(str((scores.get(i) or {}).get("dims", {}).get(key, "—")) for i in range(len(candidates))) + " |")
            lines.append("| 评审·总分 | " + " | ".join(str((scores.get(i) or {}).get("total", "—")) for i in range(len(candidates))) + " |")
        lines.append("")
        if verdict:
            lines.append(f"**评审选第 {pick + 1} 版**（{_t(verdict.get('source')) or 'critic'}）：{_t(verdict.get('why'))}")
            if _t(verdict.get("merge")):
                lines.append(f"合并建议：{_t(verdict.get('merge'))}")
            lines.append("")
        for i, cand in enumerate(candidates):
            lines.append(f"### 第 {i + 1} 版 · {_t(cand.get('label') or cand.get('style'))}{' ★' if i == pick else ''}")
            lines.append("")
            note = scores.get(i)
            if note:
                lines.append(f"评审：{_t(note.get('notes'))}")
                if note.get("fixes"):
                    lines.append("修法：" + "；".join(note["fixes"]))
                lines.append("")
            lines.append("| 镜 | 秒 | 覆盖 | 景别 | 焦段 | 运镜 | 左/右 | 一个动作 | 对白 |")
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for s in cand.get("shots") or []:
                dialogue = " / ".join(_t(d.get("line")) for d in (s.get("dialogue_ref") or []) if isinstance(d, dict))
                move = _t(s.get("move_type") or "static")
                sides = f"{_t(s.get('left')) or '—'}/{_t(s.get('right')) or '—'}"
                lines.append(
                    f"| {_t(s.get('shot_id'))} | {_t(s.get('duration_sec'))} | {_t(s.get('coverage_type'))} | {_t(s.get('scale'))} | {_t(s.get('lens'))} | {move} | {sides} | {_t(s.get('one_action')).replace('|', '／')} | {dialogue.replace('|', '／') or '—'} |"
                )
            if cand.get("warnings"):
                lines.append("")
                lines.append("警告：" + "；".join(_t(w) for w in cand["warnings"][:8]))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
