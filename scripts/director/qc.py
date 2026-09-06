"""Gate F QC report. Scripts decide pass; models may comment. Optional Blender note only."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .review_contract import evaluate_review_contract, load_contract
from .reviewer import load_review
from .sound_contract import build_sound_contract

BLENDER_NOTE = (
    "默认仍用 sets.json + blocking.jpg。"
    "仅当三人以上、跨空间走位、复杂机位或道具交接时，才可选 Blender 白模预演。"
)


def build_qc_report(prod: Path, *, evaluate: bool = False) -> dict:
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
    dest = prod / "08-qc"
    dest.mkdir(parents=True, exist_ok=True)
    report = build_qc_report(prod, evaluate=True)
    (dest / "report.draft.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "report.draft.md").write_text(_report_md(report), encoding="utf-8")
    return snapshot_qc(prod)


def promote_qc_drafts(prod: Path) -> None:
    dest = prod / "08-qc"
    for src_name, official in (("report.draft.json", "report.json"), ("report.draft.md", "report.md")):
        src = dest / src_name
        if src.exists() and src.stat().st_size > 0:
            (dest / official).write_bytes(src.read_bytes())


def snapshot_qc(prod: Path) -> dict:
    dest = prod / "08-qc"
    live = build_qc_report(prod, evaluate=False)
    official = dest / "report.json"
    draft = dest / "report.draft.json"
    return {
        "live": live,
        "official": json.loads(official.read_text(encoding="utf-8")) if official.exists() else None,
        "draft": json.loads(draft.read_text(encoding="utf-8")) if draft.exists() else None,
        "blender": BLENDER_NOTE,
        "export_exists": (prod / "06-export" / "ep01.mp4").exists(),
    }
