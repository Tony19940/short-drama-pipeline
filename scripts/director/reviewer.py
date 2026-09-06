"""Optional storyboard review. Writes findings only; never edits shots.json."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .production import load_json, read_text, write_text

HAN = re.compile(r"[\u3400-\u9fff]")
TEMPLATE_ACTION = re.compile(r"one body beat", re.I)
REVIEW_PATH = "03-storyboard/review.draft.md"


def _shots_payload(prod: Path, source: str = "draft") -> tuple[dict, str]:
    if source == "official":
        return load_json(prod, "03-storyboard/shots.json", {"shots": []}), "正式合同 shots.json"
    data = load_json(prod, "03-storyboard/shots.draft.json", {"shots": []})
    if data.get("shots"):
        return data, "分镜草稿 shots.draft.json"
    official = load_json(prod, "03-storyboard/shots.json", {"shots": []})
    if official.get("shots"):
        return official, "正式合同 shots.json（无草稿）"
    return data, "分镜草稿 shots.draft.json"


def _sets(prod: Path) -> dict[str, dict]:
    data = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    return {item["id"]: item for item in (data.get("sets") or []) if item.get("id")}


def _mark_ids(sets: dict[str, dict], scene: str) -> set[str]:
    marks = (sets.get(scene) or {}).get("marks") or []
    ids = {str(item.get("id") or "") for item in marks if item.get("id")}
    if "guard" in ids:
        ids.add("bodyguard")
    if "bodyguard" in ids:
        ids.add("guard")
    return ids


def review_storyboard(prod: Path, source: str = "draft") -> dict:
    episode = read_text(prod, "01-bible/ep01.md")
    coverage = read_text(prod, "03-storyboard/coverage.md")
    data, source_label = _shots_payload(prod, source)
    shots = list(data.get("shots") or [])
    sets = _sets(prod)
    findings: list[dict] = []
    per_shot: list[dict] = []

    if not episode.strip():
        findings.append({"level": "blocker", "shot": "", "grade": "S0", "text": "缺 01-bible/ep01.md"})
    if not coverage.strip():
        findings.append({"level": "blocker", "shot": "", "grade": "S0", "text": "缺 03-storyboard/coverage.md"})
    if not shots:
        findings.append({"level": "blocker", "shot": "", "grade": "S0", "text": "没有可审镜头"})

    for shot in shots:
        sid = str(shot.get("id") or "?")
        scene = str(shot.get("scene") or "")
        people = [str(item) for item in (shot.get("characters") or []) if item]
        line = str(shot.get("line") or "").strip()
        caption = str(shot.get("caption") or "").strip()
        action = str(shot.get("action") or "")
        look = str(shot.get("look") or "")
        camera = str(shot.get("camera") or "")
        video_prompt = str(shot.get("video_prompt") or "")
        s0: list[str] = []
        s1: list[str] = []
        s2: list[str] = []

        if not line or not caption:
            s0.append("台词或字幕空")
        kind = str(shot.get("line_kind") or "")
        speaker = str(shot.get("speaker") or "").strip()
        if kind in {"dialogue", "inner"} and speaker and people and speaker not in people:
            s0.append(f"说话人 {speaker} 不在本镜")
        if kind in {"narration", "intro", "sms"} and speaker:
            s0.append(f"{kind} 不该填说话人")
        marks = _mark_ids(sets, scene)
        if scene and scene not in sets:
            s0.append(f"场景 {scene} 不在 sets.json")
        elif marks:
            missing_people = [name for name in people if name not in marks]
            if missing_people:
                s0.append("站位对不上 blocking marks：" + ", ".join(missing_people))

        for field, value in (("camera", camera), ("action", action), ("look", look), ("video_prompt", video_prompt)):
            if HAN.search(value):
                s0.append(f"{field} 含中文，出片说明书必须英文")
        if TEMPLATE_ACTION.search(action):
            s0.append("action 仍是 one body beat 模板句")
        if line and line in video_prompt:
            s0.append("对白原文进了 video_prompt")

        for slug in people:
            folder = prod / "02-assets" / "characters" / slug
            if not (folder / "master.jpg").exists() and not (folder / "face.jpg").exists():
                s1.append(f"{slug} 缺 master/face")
            if not (folder / "sheet.jpg").exists():
                s1.append(f"{slug} 缺 sheet.jpg（新首帧不能锁）")
        scene_dir = prod / "02-assets" / "scenes" / scene if scene else None
        if scene_dir and not (scene_dir / "master.jpg").exists():
            s1.append(f"{scene} 缺空镜 master")
        if scene_dir and not (scene_dir / "blocking.jpg").exists():
            s1.append(f"{scene} 缺 blocking.jpg")
        blob = " ".join([look, video_prompt, line]).lower()
        if shot.get("setup") == "insert" and "bell" not in blob and "银铃" not in line:
            s1.append("insert 未写银铃")
        if scene == "factory-office" and "glass" not in blob and "玻璃" not in look:
            s1.append("走廊镜未锁玻璃")

        if str(shot.get("expression") or "") in {"", "held"}:
            s2.append("表情仍是 held，力度可再写一层")

        grade = "S0" if s0 else "S1" if s1 else "S2" if s2 else "ok"
        if s0:
            findings.append({"level": "blocker", "shot": sid, "grade": "S0", "text": "；".join(s0)})
        if s1:
            findings.append({"level": "major", "shot": sid, "grade": "S1", "text": "；".join(s1)})
        if s2:
            findings.append({"level": "note", "shot": sid, "grade": "S2", "text": "；".join(s2)})
        per_shot.append({"id": sid, "grade": grade, "s0": s0, "s1": s1, "s2": s2})

    if any(item["level"] in {"blocker", "major"} for item in findings):
        verdict = "REVISE"
    elif findings:
        verdict = "APPROVE_WITH_NOTES"
    else:
        verdict = "APPROVE"

    written_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# 分镜审查 · {prod.name}",
        "",
        f"- 范围：{source_label}、ep01.md、coverage.md、sets.json",
        f"- 结论：{verdict}",
        "- 复核方式：本机确定性审查（不改 shots.json）",
        f"- 时间：{written_at}",
        "",
        "审查不挡「接受草稿进正式表」。REVISE 时仍可接受，后果由人锁 Gate C 承担。",
        "",
    ]
    if not findings:
        lines.append("没有阻断或备注。")
    for index, item in enumerate(findings, start=1):
        loc = item["shot"] or "全集"
        lines += [
            f"## {item['level'].upper()} · REV-{index:03d} · {item['grade']} · {loc}",
            f"- 证据：{item['text']}",
            "- 修订结果：由人改草稿后可再点审查。审查器不改来源。",
            "",
        ]
    lines.append("## 按镜")
    for item in per_shot:
        extra = []
        if item["s0"]:
            extra.append(f"S0 {len(item['s0'])}")
        if item["s1"]:
            extra.append(f"S1 {len(item['s1'])}")
        if item["s2"]:
            extra.append(f"S2 {len(item['s2'])}")
        suffix = " / ".join(extra)
        lines.append(f"- {item['id']}: {item['grade']}" + (f" / {suffix}" if suffix else ""))
    write_text(prod, REVIEW_PATH, "\n".join(lines) + "\n")
    return {
        "ok": True,
        "verdict": verdict,
        "path": REVIEW_PATH,
        "source": source_label,
        "findings": findings,
        "shots": per_shot,
        "markdown": read_text(prod, REVIEW_PATH),
    }


def load_review(prod: Path) -> dict:
    text = read_text(prod, REVIEW_PATH)
    verdict = ""
    for line in text.splitlines():
        if line.startswith("- 结论："):
            verdict = line.split("：", 1)[-1].strip()
            break
    return {"path": REVIEW_PATH, "exists": bool(text.strip()), "verdict": verdict, "markdown": text}
