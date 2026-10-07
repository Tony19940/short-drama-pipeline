"""Gate F QC report. Scripts decide pass; models may comment. Optional Blender note only."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .context import context_for
from .paths import safe_under
from .review_contract import evaluate_review_contract, load_contract
from .reviewer import load_review
from .sound_contract import build_sound_contract

BLENDER_NOTE = (
    "默认仍用 sets.json + blocking.jpg。"
    "仅当三人以上、跨空间走位、复杂机位或道具交接时，才可选 Blender 白模预演。"
)


def build_qc_report(prod: Path, *, evaluate: bool = False) -> dict:
    ctx = context_for(prod)
    if ctx.mode == "registered":
        return _registered_report(ctx)
    contract = load_contract(prod) or {}
    evaluated = dict(contract)
    if evaluate:
        try:
            evaluated = evaluate_review_contract(prod)
        except Exception as exc:
            evaluated = dict(contract)
            evaluated["error"] = str(exc)
    review = load_review(prod)
    sound = build_sound_contract(prod)
    export = prod / "06-export" / "ep01.mp4"
    failures = list(evaluated.get("failures") or [])
    shot_verdicts = list(evaluated.get("shot_verdicts") or review.get("shots") or [])
    rework = []
    for item in shot_verdicts:
        reasons = list(item.get("s0") or []) + list(item.get("s1") or []) + list(item.get("s2") or [])
        if item.get("grade") in {"fail", "s0", "s1"} or reasons:
            rework.append({"id": item.get("id"), "reasons": reasons or [item.get("grade") or "fail"]})
    required = evaluated.get("required") or ("fail" if failures else "pass")
    visual = evaluated.get("visual") or "inconclusive"
    if required == "fail":
        verdict = "fail"
    elif not export.exists():
        verdict = "fail"
        failures.append("缺 06-export/ep01.mp4")
    else:
        verdict = visual if visual != "pass" else "pass"
        if visual == "inconclusive":
            verdict = "inconclusive"
    report = {
        "at": int(time.time()),
        "verdict": verdict,
        "required": required,
        "visual": visual,
        "s0": [item for item in shot_verdicts if item.get("s0")],
        "s1": [item for item in shot_verdicts if item.get("s1")],
        "s2": [item for item in shot_verdicts if item.get("s2")],
        "failures": failures,
        "rework": rework,
        "export": "06-export/ep01.mp4" if export.exists() else "",
        "sound_kinds": sound.get("kinds") or [],
        "blender": BLENDER_NOTE,
        "note": "脚本判过关。视觉层无模型时标 inconclusive，不算 pass。",
    }
    return report


def _registered_report(ctx) -> dict:
    """Summarize current evidence without adopting an old review or issuing a pass."""
    from .narrative import inspect_narrative

    prod = ctx.prod
    cut = ctx.read_artifact("cut.json")
    failures = [] if cut else [f"缺当前剪辑表 {ctx.cut_rel()}"]
    export = str(cut.get("final_file") or "")
    export_exists = False
    if export:
        try:
            export_exists = safe_under(prod, export).is_file()
        except ValueError as exc:
            failures.append(str(exc))
    if not export_exists:
        failures.append("缺当前剪辑表指定的成片")
    narrative = inspect_narrative(prod, ctx.episode_token, ctx.revision_id, cut)
    failures.extend(narrative.get("errors") or [])
    pending = list(narrative.get("pending") or [])
    return {
        "schema": "revision-qc-summary-v1", "at": int(time.time()),
        "context": ctx.to_dict(), "source": ctx.source_report(),
        "verdict": "fail" if failures else "inconclusive",
        "required": "fail" if failures else narrative.get("status") or "pending",
        "visual": "inconclusive", "s0": [], "s1": [], "s2": [],
        "failures": failures, "pending": pending, "rework": [],
        "export": export if export_exists else "", "export_exists": export_exists,
        "sound_kinds": [], "narrative": narrative, "blender": BLENDER_NOTE,
        "note": "登记版本仅汇总当前剪辑与段落证据；完整声画质量由新版段落审核及 Gate F 确认，此摘要不授予 pass。",
    }


def _qc_dir(prod: Path) -> Path:
    ctx = context_for(prod)
    return prod / "08-qc" / str(ctx.episode_token) if ctx.mode == "registered" else prod / "08-qc"


def _report_md(report: dict) -> str:
    lines = [
        "# 审片报告",
        "",
        f"- 结论：{report.get('verdict')}",
        f"- 脚本关：{report.get('required')}",
        f"- 画面关：{report.get('visual')}",
        f"- 成片：{report.get('export') or '缺'}",
        "",
        "## 返工单",
        "",
    ]
    if report.get("rework"):
        for item in report["rework"]:
            lines.append(f"- {item['id']}：{'；'.join(item['reasons'])}")
    else:
        lines.append("- 无脚本返工项。画面对错仍要人看。")
    lines.extend(["", "## Blender", "", report.get("blender") or BLENDER_NOTE, ""])
    return "\n".join(lines)


def write_qc_draft(prod: Path) -> dict:
    dest = _qc_dir(prod)
    dest.mkdir(parents=True, exist_ok=True)
    report = build_qc_report(prod, evaluate=True)
    (dest / "report.draft.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "report.draft.md").write_text(_report_md(report), encoding="utf-8")
    return snapshot_qc(prod)


def promote_qc_drafts(prod: Path) -> None:
    dest = _qc_dir(prod)
    for src_name, official in (("report.draft.json", "report.json"), ("report.draft.md", "report.md")):
        src = dest / src_name
        if src.exists() and src.stat().st_size > 0:
            (dest / official).write_bytes(src.read_bytes())


def snapshot_qc(prod: Path) -> dict:
    dest = _qc_dir(prod)
    ctx = context_for(prod)
    live = build_qc_report(prod, evaluate=False)
    official = dest / "report.json"
    draft = dest / "report.draft.json"
    return {
        "live": live,
        "official": json.loads(official.read_text(encoding="utf-8")) if official.exists() else None,
        "draft": json.loads(draft.read_text(encoding="utf-8")) if draft.exists() else None,
        "blender": BLENDER_NOTE,
        "export_exists": (prod / "06-export" / "ep01.mp4").exists() if ctx.mode == "legacy" else bool(live.get("export_exists")),
    }
