"""QC → model notes: what this video model does well and where it breaks.

Every verdict on a rendered shot is recorded twice: in the production's own
`.pipeline/model_feedback.json` (audit trail) and in the repo-wide
`knowledge/model-notes/<profile_id>.json`, from which `<profile_id>.md` is
regenerated. `video_profiles.profile_brief` reads the md back as `experience`,
so the next design / critic call sees "close + hands → 漂" without anyone
retyping it.

The md also carries one hand-written section, `## 种子`: a 现象 / 原因 / 处理
table of known failure modes (`seed_notes`). Regeneration keeps it, and its
rows lead the `experience` list.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from .paths import ROOT

FEEDBACK_FILE = "model_feedback.json"
FEEDBACK_SCHEMA = "model-feedback-v1"
NOTES_SCHEMA = "model-notes-v1"
VERDICTS = ("pass", "fail")
MAX_BULLETS = 40
MAX_EXPERIENCE = 12
DEFAULT_NOTES_DIR = ROOT / "knowledge" / "model-notes"
SEED_HEADING = "## 种子"
SEED_COLUMNS = ("symptom", "cause", "fix")
SEED_COLUMNS_ZH = ("现象", "原因", "处理")
_TAG_SPLIT = re.compile(r"[、,，;；/\s+]+")


def _t(value: Any) -> str:
    return str(value or "").strip()


def notes_dir(create: bool = False) -> Path:
    """`knowledge/model-notes/` unless DIRECTOR_MODEL_NOTES_DIR points elsewhere (tests do that)."""
    override = os.environ.get("DIRECTOR_MODEL_NOTES_DIR", "").strip()
    path = Path(override) if override else DEFAULT_NOTES_DIR
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_key(profile_id: str) -> str:
    key = re.sub(r"[^0-9A-Za-z_.-]+", "_", _t(profile_id)).strip("._-")
    return key or "unknown"


def normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        tags = _TAG_SPLIT.split(tags)
    out: list[str] = []
    for tag in tags or []:
        word = _t(tag).lower()
        if word and word not in out:
            out.append(word)
    return out


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(default))
    return data if isinstance(data, dict) else json.loads(json.dumps(default))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_profile(prod: Path, profile_id: Optional[str]) -> str:
    if _t(profile_id):
        from .video_profiles import get_profile

        return get_profile(profile_id)["id"]
    from .pipeline import read_artifact
    from .video_profiles import resolve_target_model

    table = read_artifact(prod, "shot_list.json")
    return resolve_target_model(prod, _t(table.get("target_model")) or None)


def _shot_tags(prod: Path, shot_id: str) -> list[str]:
    """Design facts about the shot that are worth learning from: scale, move, coverage, hands, seconds bucket."""
    from .pipeline import read_artifact

    table = read_artifact(prod, "shot_list.json")
    shot = next((s for s in table.get("shots") or [] if _t(s.get("shot_id")) == shot_id), None)
    if not shot:
        return []
    tags = [_t(shot.get("scale")), _t(shot.get("move_type") or "static"), _t(shot.get("coverage_type"))]
    blob = _t(shot.get("one_action")) + _t(shot.get("shot_job"))
    if any(word in blob for word in ("手", "指", "握", "抹", "递", "拧")):
        tags.append("hands")
    if shot.get("internal_cuts"):
        tags.append("internal_cut")
    if shot.get("dialogue_ref") and _t(shot.get("dialogue_delivery")) == "on_camera":
        tags.append("on_camera")
    try:
        seconds = int(shot.get("duration_sec") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds >= 10:
        tags.append("long")
    return normalize_tags(tags)


def read_feedback(prod: Path) -> dict:
    from .pipeline import artifact_path

    return _load_json(artifact_path(prod, FEEDBACK_FILE), {"schema": FEEDBACK_SCHEMA, "items": []})


def record_outcome(
    prod: Path,
    shot_id: str,
    verdict: str,
    tags: Any = None,
    note: str = "",
    profile_id: Optional[str] = None,
    *,
    model: str = "",
    task_kind: str = "",
    language: str = "",
    take_id: str = "",
    attempt_id: str = "",
    request_hash: str = "",
    in_sec: Any = None,
    out_sec: Any = None,
    cost: Any = None,
    evidence: str = "",
) -> dict:
    """Append one QC outcome and regenerate the model's notes page. Returns the stored item + page path."""
    from .pipeline import artifact_path, pipeline_dir

    shot_id = _t(shot_id)
    if not shot_id:
        raise ValueError("缺 shot_id")
    verdict = _t(verdict).lower()
    if verdict not in VERDICTS:
        raise ValueError("verdict 只能是 pass / fail")
    tag_list = normalize_tags(tags)
    if not tag_list:
        tag_list = _shot_tags(prod, shot_id)
    if not tag_list:
        raise ValueError("至少给一个标签（如 close、hands、push），或先有镜头表让机器读出来")
    profile = _resolve_profile(prod, profile_id)
    item = {
        "at": int(time.time()),
        "production": prod.name,
        "shot_id": shot_id,
        "verdict": verdict,
        "tags": tag_list,
        "note": _t(note),
        "profile_id": profile,
        "model": _t(model),
        "task_kind": _t(task_kind),
        "language": _t(language),
        "take_id": _t(take_id),
        "attempt_id": _t(attempt_id),
        "request_hash": _t(request_hash),
        "in_sec": in_sec,
        "out_sec": out_sec,
        "cost": cost,
        "evidence": _t(evidence),
    }
    pipeline_dir(prod, create=True)
    feedback = read_feedback(prod)
    items = [i for i in feedback.get("items") or [] if isinstance(i, dict)]
    items.append(item)
    feedback = {"schema": FEEDBACK_SCHEMA, "project_id": prod.name, "items": items}
    _write_json(artifact_path(prod, FEEDBACK_FILE), feedback)

    folder = notes_dir(create=True)
    key = _profile_key(profile)
    store_path = folder / f"{key}.json"
    store = _load_json(store_path, {"schema": NOTES_SCHEMA, "profile_id": profile, "items": []})
    store_items = [i for i in store.get("items") or [] if isinstance(i, dict)]
    store_items.append(item)
    store = {"schema": NOTES_SCHEMA, "profile_id": profile, "items": store_items[-400:]}
    _write_json(store_path, store)
    md_path = folder / f"{key}.md"
    md_path.write_text(render_notes_md(profile, store["items"], seeds=read_seeds(profile)), encoding="utf-8")
    return {"ok": True, "item": item, "notes_md": str(md_path), "feedback": f".pipeline/{FEEDBACK_FILE}", "count": len(items)}


def _seed_row(row: Any) -> Optional[dict]:
    """{"symptom","cause","fix"} / {"现象","原因","处理"} / a 3-sequence → normalized row; None when a cell is empty."""
    if isinstance(row, dict):
        cells = [_t(row.get(en) or row.get(zh)) for en, zh in zip(SEED_COLUMNS, SEED_COLUMNS_ZH)]
    else:
        cells = [_t(x) for x in list(row or [])[:3]]
    if len(cells) != 3 or not all(cells):
        return None
    return dict(zip(SEED_COLUMNS, cells))


def parse_seeds(md_text: str) -> list[dict]:
    """Rows of the hand-written `## 种子` table; header and rule lines are skipped."""
    out: list[dict] = []
    inside = False
    for line in str(md_text or "").splitlines():
        raw = line.strip()
        if raw.startswith("## "):
            inside = raw == SEED_HEADING
            continue
        if not inside or not raw.startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == SEED_COLUMNS_ZH[0] or set(cells[0]) <= set(":-"):
            continue
        row = _seed_row(cells[:3])
        if row and row not in out:
            out.append(row)
    return out


def read_seeds(profile_id: str) -> list[dict]:
    path = notes_dir() / f"{_profile_key(profile_id)}.md"
    return parse_seeds(path.read_text(encoding="utf-8")) if path.exists() else []


def seed_line(row: dict) -> str:
    return " → ".join(_t(row.get(key)) for key in SEED_COLUMNS)


def seed_notes(profile_id: str, rows: list, *, replace: bool = False) -> dict:
    """Write hand-curated failure modes (现象 / 原因 / 处理) into the model's notes page.

    Merged by 现象: a repeated 现象 replaces the earlier row. QC bullets on the same page are kept.
    """
    from .video_profiles import get_profile

    profile = get_profile(profile_id)["id"]
    clean = [row for row in (_seed_row(item) for item in rows or []) if row]
    if not clean:
        raise ValueError("种子每行要有 现象 / 原因 / 处理 三格")
    merged = [] if replace else read_seeds(profile)
    for row in clean:
        merged = [item for item in merged if item["symptom"] != row["symptom"]]
        merged.append(row)
    folder = notes_dir(create=True)
    key = _profile_key(profile)
    store = _load_json(folder / f"{key}.json", {"schema": NOTES_SCHEMA, "profile_id": profile, "items": []})
    items = [item for item in store.get("items") or [] if isinstance(item, dict)]
    md_path = folder / f"{key}.md"
    md_path.write_text(render_notes_md(profile, items, seeds=merged), encoding="utf-8")
    return {"ok": True, "profile_id": profile, "seeds": merged, "notes_md": str(md_path)}


def bullet_for(item: dict) -> str:
    tags = " + ".join(item.get("tags") or [])
    outcome = _t(item.get("note")) or ("稳" if item.get("verdict") == "pass" else "崩")
    where = " ".join(x for x in (_t(item.get("production")), _t(item.get("shot_id"))) if x)
    return f"{tags} → {outcome}（{where}，{_t(item.get('verdict'))}）"


def render_notes_md(profile_id: str, items: list[dict], seeds: Optional[list[dict]] = None) -> str:
    """Bullets grouped by tag set, newest first, at most MAX_BULLETS in total. `seeds` is the kept `## 种子` table."""
    from .video_profiles import get_profile

    label = get_profile(profile_id)["label"]
    newest = sorted(items, key=lambda i: int(i.get("at") or 0), reverse=True)[:MAX_BULLETS]
    groups: dict[str, list[dict]] = {}
    for item in newest:
        groups.setdefault(" + ".join(item.get("tags") or []) or "其他", []).append(item)
    lines = [f"# 模型经验 · {label}", ""]
    lines.append(f"QC 回写自动生成；只有 `{SEED_HEADING[3:]}` 一节手写，回写时保留。每条：标签 → 结果（项目 镜号，判定）。最新在前，最多 {MAX_BULLETS} 条。")
    lines.append(f"拆镜 / 评审 Agent 通过 `target_profile.experience` 读到前 {MAX_EXPERIENCE} 条，种子行在前。")
    lines.append("")
    fails = sum(1 for i in newest if i.get("verdict") == "fail")
    lines.append(f"- 记录 {len(items)} 条；近 {len(newest)} 条里 {fails} 条崩，{len(newest) - fails} 条稳。")
    lines.append("")
    if seeds:
        lines.append(SEED_HEADING)
        lines.append("")
        lines.append("三列：现象 / 原因 / 处理。跨模型的已知坏法，先于 QC 记录。")
        lines.append("")
        lines.append("| " + " | ".join(SEED_COLUMNS_ZH) + " |")
        lines.append("|---|---|---|")
        for row in seeds:
            lines.append("| " + " | ".join(_t(row.get(key)).replace("|", "／") for key in SEED_COLUMNS) + " |")
        lines.append("")
    # fail-heavy groups first: that is what the designer must avoid
    ordered = sorted(groups.items(), key=lambda kv: (-sum(1 for i in kv[1] if i.get("verdict") == "fail"), -int(kv[1][0].get("at") or 0)))
    for tags, members in ordered:
        lines.append(f"## {tags}")
        lines.append("")
        for item in members:
            lines.append(f"- {bullet_for(item)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def experience_for(profile_id: str, limit: int = MAX_EXPERIENCE) -> list[str]:
    """Up to `limit` lines from the model's notes page: `## 种子` rows first, then QC bullets. Empty when no page."""
    path = notes_dir() / f"{_profile_key(profile_id)}.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out: list[str] = [seed_line(row) for row in parse_seeds(text)][:limit]
    for line in text.splitlines():
        if len(out) >= limit:
            break
        raw = line.strip()
        if raw.startswith("- ") and "→" in raw:
            out.append(raw[2:].strip())
    return out


def search_outcomes(
    prod: Path,
    *,
    verdict: str = "",
    shot_id: str = "",
    tag: str = "",
    model: str = "",
    task_kind: str = "",
) -> list[dict]:
    """Filter recorded accept/reject evidence. Does not invent blanket rules."""
    items = [item for item in (read_feedback(prod).get("items") or []) if isinstance(item, dict)]
    want_verdict = _t(verdict).lower()
    want_shot = _t(shot_id)
    want_tag = _t(tag).lower()
    want_model = _t(model)
    want_kind = _t(task_kind)
    out = []
    for item in items:
        if want_verdict and _t(item.get("verdict")).lower() != want_verdict:
            continue
        if want_shot and _t(item.get("shot_id")) != want_shot:
            continue
        if want_tag and want_tag not in normalize_tags(item.get("tags")):
            continue
        if want_model and want_model not in {_t(item.get("model")), _t(item.get("profile_id"))}:
            continue
        if want_kind and _t(item.get("task_kind")) != want_kind:
            continue
        out.append(item)
    return out


def snapshot_feedback(prod: Path, profile_id: Optional[str] = None) -> dict:
    profile = _resolve_profile(prod, profile_id)
    feedback = read_feedback(prod)
    return {
        "profile_id": profile,
        "items": list(feedback.get("items") or [])[-50:],
        "experience": experience_for(profile),
        "notes_md": f"knowledge/model-notes/{_profile_key(profile)}.md",
    }
