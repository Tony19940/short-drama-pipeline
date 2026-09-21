"""11-station handover. Media stays in 02-assets / 04-frames / 05-shots; JSON lives in .pipeline/."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from .production import load_json, save_json
from .store import load_approvals, save_approvals

logger = logging.getLogger(__name__)

PIPELINE = ".pipeline"

STATIONS = [
    {"id": "0", "label": "小说", "tab": "story", "agent": "novel"},
    {"id": "A", "label": "编剧", "tab": "writer", "agent": "writer"},
    {"id": "B", "label": "资产", "tab": "art", "agent": "assets"},
    {"id": "C", "label": "分镜", "tab": "design", "agent": "design"},
    {"id": "C1", "label": "说明书", "tab": "spec", "agent": "spec"},
    {"id": "C2", "label": "生成包", "tab": "package", "agent": "package"},
    {"id": "D", "label": "关键帧", "tab": "frames", "agent": "keyframes"},
    {"id": "E", "label": "视频", "tab": "render", "agent": "video"},
    {"id": "E+", "label": "声音", "tab": "sound", "agent": "sound"},
    {"id": "F", "label": "剪辑", "tab": "edit", "agent": "edit"},
]
STATION_IDS = [item["id"] for item in STATIONS]
REJECT_TARGETS = list(STATION_IDS)
CAMERA_IN_WRITER = re.compile(r"景别|运镜|焦段|机位|镜头推进")
DESIGN_FORBIDDEN = {"prompt", "video_prompt", "asset_id", "image_file", "image_prompt", "motion_prompt"}
SPEC_FORBIDDEN = {"prompt", "asset_id", "keyframe_file", "image_prompt", "motion_prompt"}
COVERAGE_TYPES = {"master", "otc", "ots", "reverse", "reaction", "insert", "empty", "continuous", "close", "single", "pov", "follow"}
SHOT_TABLE_SCHEMA = "shot-table-v2"
GEN_MODES = {"i2v_first", "flf2v", "video_extend", "r2v", "edit"}
MODELS_ZH = {
    "seedance_2_5",
    "seedance",
    "seedance_2_0",
    "seedance_2_0_mini",
    "doubao-seedance-2-0-mini",
    "dreamina-seedance-2-0-260128",
    "wan_3",
    "wan",
}
MODELS_EN = {"minimax_h3", "google_veo", "veo"}
DEFAULT_ANTI_PLASTIC = "皮肤有轻微深浅和自然纹理，不要磨皮，不要塑料感；高光哑光到半哑光，不要大片镜面油光；边缘不要过锐。"

def pipeline_dir(prod: Path, create: bool = False) -> Path:
    path = prod / PIPELINE
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path

def artifact_path(prod: Path, name: str) -> Path:
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("bad pipeline file: " + name)
    return pipeline_dir(prod) / name

def uses_pipeline(prod: Path) -> bool:
    folder = pipeline_dir(prod)
    if not folder.exists():
        return False
    return any(p.suffix == ".json" and p.stat().st_size > 2 for p in folder.glob("*.json"))

def read_artifact(prod: Path, name: str, default: Optional[dict] = None) -> dict:
    path = artifact_path(prod, name)
    if not path.exists():
        return {} if default is None else json.loads(json.dumps(default))
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}

def write_artifact(prod: Path, name: str, data: dict) -> dict:
    pipeline_dir(prod, create=True)
    payload = dict(data)
    payload.setdefault("project_id", prod.name)
    payload.setdefault("agent", Path(name).stem)
    payload.setdefault("version", payload.get("version") or 1)
    payload.setdefault("status", payload.get("status") or "draft")
    save_json(prod, f"{PIPELINE}/{name}", payload)
    return payload

def _text(value: Any) -> str:
    return str(value or "").strip()

def _lines_from_writer(writer: dict) -> list[str]:
    lines = []
    for scene in writer.get("scenes") or []:
        for item in scene.get("dialogue") or []:
            line = _text(item.get("line"))
            if line:
                lines.append(line)
        for item in scene.get("narration") or []:
            line = _text(item.get("line"))
            if line:
                lines.append(line)
    return lines

def raise_if(errors: list[str]) -> None:
    if errors:
        raise PermissionError(" / ".join(errors[:8]))

def validate_novel(data: dict) -> list[str]:
    errors = []
    if not _text(data.get("title")):
        errors.append("novel missing title")
    if len(_text(data.get("body"))) < 80:
        errors.append("novel body too short")
    if not data.get("characters"):
        errors.append("novel missing characters")
    blob = json.dumps(data, ensure_ascii=False)
    if "scene_heading" in data or "shot_size" in data or "image_assets" in data:
        errors.append("novel cannot carry shots or assets")
    if CAMERA_IN_WRITER.search(blob):
        errors.append("novel cannot describe camera")
    return errors

def validate_writer(data: dict) -> list[str]:
    errors = []
    bible = data.get("series_bible") or {}
    if not _text(bible.get("logline")):
        errors.append("writer missing logline")
    if not bible.get("characters"):
        errors.append("writer missing characters")
    if not bible.get("locations"):
        errors.append("writer missing locations")
    if not (data.get("episode_outline") or []):
        errors.append("writer missing episode_outline")
    scenes = data.get("scenes") or []
    if not scenes:
        errors.append("writer missing scenes")
    for scene in scenes:
        sid = scene.get("scene_id") or "?"
        for key in ("heading", "location_id", "time_of_day", "int_ext", "present_cast", "scene_job", "whose_scene", "start_state", "end_state", "action"):
            if not scene.get(key) and scene.get(key) != []:
                errors.append(f"{sid} missing {key}")
        if CAMERA_IN_WRITER.search(_text(scene.get("action"))):
            errors.append(f"{sid} action has camera language")
        if scene.get("unfilmable_check") == "fail":
            errors.append(f"{sid} unfilmable_check=fail")
        if scene.get("mute_test") != "pass":
            errors.append(f"{sid} mute_test not pass")
        if scene.get("preach_check") == "fail":
            errors.append(f"{sid} preach_check=fail")
        if scene.get("dialogue") is None:
            errors.append(f"{sid} missing dialogue list")
    return errors

def validate_assets(data: dict, prod: Optional[Path] = None) -> list[str]:
    errors = []
    assets = data.get("assets") or []
    if not assets:
        errors.append("assets table empty")
    ids = []
    for item in assets:
        aid = _text(item.get("asset_id"))
        if not aid:
            errors.append("asset missing asset_id")
            continue
        ids.append(aid)
        if item.get("type") not in {"character", "costume_state", "location", "prop", "creature", "style"}:
            errors.append(f"{aid} bad type")
        if not _text(item.get("what_it_locks")):
            errors.append(f"{aid} missing what_it_locks")
        rel = _text(item.get("file"))
        if not rel:
            errors.append(f"{aid} missing file")
        elif prod is not None and not (prod / rel).exists():
            errors.append(f"{aid} file missing: {rel}")
        if CAMERA_IN_WRITER.search(_text(item.get("image_prompt"))):
            errors.append(f"{aid} image_prompt looks like a shot")
        for field in item.get("lock_card") or []:
            if field.get("source") == "inferred_empty" and _text(field.get("value")):
                errors.append(f"{aid} inferred_empty filled")
    if len(ids) != len(set(ids)):
        errors.append("duplicate asset_id")
    return errors

def validate_shot_list(data: dict, **context: Any) -> list[str]:
    """Legacy shape check. A `shot-table-v2` list also runs the filmability rules in shot_table.py."""
    if _text(data.get("schema")) == SHOT_TABLE_SCHEMA:
        from .shot_table import validate_shot_table

        errors, _warnings = validate_shot_table(data, **context)
        return errors
    errors = []
    shots = data.get("shots") or []
    if not shots:
        errors.append("shot_list empty")
    if data.get("visible_change_without_dialogue") == "fail":
        errors.append("no visible change without dialogue")
    steps = data.get("design_steps_done")
    if steps not in (None, [1, 2, 3, 4, 5, 6, 7]) and steps != [1, 2, 3, 4, 5, 6, 7]:
        errors.append("design must finish 7 steps")
    if not data.get("left_right_lock") and not data.get("continuity_bible"):
        errors.append("missing left_right_lock")
    for shot in shots:
        sid = shot.get("shot_id") or shot.get("id") or "?"
        if not _text(shot.get("beat")):
            errors.append(f"{sid} missing beat")
        job = _text(shot.get("shot_job"))
        if not job:
            errors.append(f"{sid} missing shot_job")
        coverage = _text(shot.get("coverage_type") or shot.get("setup"))
        if coverage and coverage not in COVERAGE_TYPES:
            errors.append(f"{sid} bad coverage_type")
        if coverage == "reaction" and len(job) < 8:
            errors.append(f"{sid} empty reaction has no shot_job")
        if coverage == "reaction" and re.search(r"holds the look|after SH\d+", job + " " + _text(shot.get("action")), re.I) and len(job) < 12:
            errors.append(f"{sid} empty reaction has no shot_job")
        move_needed = _text(shot.get("move_needed") or ("static" if shot.get("move") == "static" else "move"))
        if move_needed == "move" and not _text(shot.get("move_reason")):
            errors.append(f"{sid} move needs a reason")
        for key in DESIGN_FORBIDDEN:
            if key in shot and _text(shot.get(key)):
                errors.append(f"{sid} design cannot carry {key}")
    return errors

def validate_shot_specs(data: dict, writer: Optional[dict] = None) -> list[str]:
    errors = []
    specs = data.get("shot_specs") or data.get("specs") or []
    if not specs:
        errors.append("shot specs empty")
    allowed_lines = set(_lines_from_writer(writer or {}))
    required = (
        "subject", "action_now", "shot_size", "angle", "height", "focal_length",
        "aspect_ratio", "move_type", "move_detail", "move_reason", "intensity",
        "left", "right", "eyeline", "day_night", "key_light_dir",
        "quality", "color_mood", "duration_sec", "axis_side", "in_from", "out_to",
    )
    for spec in specs:
        sid = spec.get("shot_id") or spec.get("id") or "?"
        no_people = _text(spec.get("shot_size")) in {"insert", "pov"}
        for key in required:
            if no_people and key in ("left", "right", "eyeline"):
                continue
            if spec.get(key) in (None, ""):
                errors.append(f"{sid} spec missing {key}")
                break
        for key in SPEC_FORBIDDEN:
            if key in spec and _text(spec.get(key)):
                errors.append(f"{sid} spec cannot carry {key}")
        line = _text(spec.get("dialogue_line"))
        if line and allowed_lines and line not in allowed_lines:
            errors.append(f"{sid} dialogue is not the writer line")
        move = _text(spec.get("move_type")).lower()
        if move == "static" and int(spec.get("intensity") or 0) != 0:
            errors.append(f"{sid} static intensity must be 0")
        if re.search(r"cinematic|movie-like", _text(spec.get("move_reason")), re.I):
            errors.append(f"{sid} move reason is empty garnish")
        try:
            if float(spec.get("duration_sec")) <= 0:
                errors.append(f"{sid} duration_sec must be > 0")
        except (TypeError, ValueError):
            errors.append(f"{sid} duration_sec invalid")
    return errors

def validate_packages(data: dict, assets: Optional[dict] = None, specs: Optional[dict] = None, prod: Optional[Path] = None) -> list[str]:
    errors = []
    packages = data.get("packages") or data.get("gen_packages") or []
    if not packages:
        errors.append("packages empty")
    known = {_text(item.get("asset_id")) for item in (assets or {}).get("assets") or [] if item.get("asset_id")}
    spec_lines = {_text(item.get("shot_id") or item.get("id")): _text(item.get("dialogue_line")) for item in (specs or {}).get("shot_specs") or (specs or {}).get("specs") or []}
    episode_model = _text(data.get("episode_target_model") or (packages[0].get("episode_target_model") if packages else ""))
    for pkg in packages:
        sid = pkg.get("shot_id") or "?"
        if pkg.get("keyframe_files"):
            errors.append(f"{sid} package cannot name keyframe files")
        if pkg.get("gen_mode") not in GEN_MODES:
            errors.append(f"{sid} gen_mode must be i2v_first/flf2v/video_extend/r2v/edit")
        if _text(pkg.get("gen_mode")) == "t2v":
            errors.append(f"{sid} t2v cannot be the finish path")
        if not pkg.get("asset_refs"):
            errors.append(f"{sid} missing asset_refs")
        if known:
            missing = [ref for ref in pkg.get("asset_refs") or [] if ref not in known]
            if missing:
                errors.append(f"{sid} unknown assets: " + ", ".join(missing))
        if not _text(pkg.get("image_prompt")):
            errors.append(f"{sid} missing image_prompt")
        if not _text(pkg.get("motion_prompt")):
            errors.append(f"{sid} missing motion_prompt")
        if pkg.get("confirmed") not in {True, False}:
            errors.append(f"{sid} missing confirmed")
        model = _text(pkg.get("target_model"))
        lang = _text(pkg.get("prompt_language"))
        try:
            from .video_profiles import get_profile as _get_profile

            capability = _text((_get_profile(pkg.get("capability_profile_id") or model) or {}).get("id"))
        except Exception:
            capability = _text(pkg.get("capability_profile_id") or model)
        if (model in MODELS_ZH or capability in MODELS_ZH) and lang != "zh":
            errors.append(f"{sid} Wan/Seedance prompts must be zh")
        if (model in MODELS_EN or capability in MODELS_EN) and lang != "en":
            errors.append(f"{sid} H3/Veo control language must be en")
        if episode_model and model and model != episode_model:
            errors.append(f"{sid} model differs from episode_target_model")
        line = _text(pkg.get("dialogue_line"))
        spec_line = spec_lines.get(sid)
        if spec_line and line and line != spec_line:
            errors.append(f"{sid} package line is not the spec line")
        if prod is not None:
            from .codex_stills import missing_costume_state_files

            for msg in missing_costume_state_files(prod, pkg.get("asset_refs") or [], assets or {}):
                errors.append(f"{sid} {msg}")
            still_files = pkg.get("still_ref_files") or []
            if still_files and len(still_files) > 5:
                errors.append(f"{sid} still_ref_files exceed Codex 5-cap: {len(still_files)}")
    return errors

def packages_confirmed(data: dict) -> bool:
    packages = data.get("packages") or data.get("gen_packages") or []
    if not packages:
        return False
    return all(bool(item.get("confirmed")) for item in packages)

KEYFRAME_QC_KEYS = ("status", "face", "costume", "location", "left_right", "composition", "aspect_ratio", "light_matches_spec", "state_match")
KEYFRAME_TIGHT_QC_KEYS = ("plastic_face", "anatomy")
KEYFRAME_QC_VALUES = {"pass", "fail", "n/a"}
KEYFRAME_QC_TEXT_KEYS = {"status", "notes", "waived_by"}


def keyframe_context(prod: Path, episode: int = 1) -> dict:
    """Everything validate_keyframes needs beyond the file itself."""
    return {
        "packages": read_artifact(prod, episode_artifact_name("gen_packages.json", episode)),
        "specs": read_artifact(prod, episode_artifact_name("shot_specs.json", episode)),
        "table": read_artifact(prod, episode_artifact_name("shot_list.json", episode)),
        "prod": prod,
    }


def validate_keyframes(
    data: dict,
    *,
    packages: Optional[dict] = None,
    specs: Optional[dict] = None,
    table: Optional[dict] = None,
    prod: Optional[Path] = None,
) -> list[str]:
    """6.1 gate. A nit is a fail unless a named human waives it; a first_last plan needs its last frame;
    tight shots need plastic_face and anatomy; every frame must match the shot state; a human signs the file."""
    from .shot_table import TIGHT_SCALES

    errors = []
    frames = data.get("keyframes") or data.get("frames") or []
    if not frames:
        errors.append("keyframes empty")
        return errors
    if not _text(data.get("reviewed_by")):
        errors.append("keyframes need reviewed_by: a human name, not an agent")
    pkg_rows = (packages or {}).get("packages") or (packages or {}).get("gen_packages") or []
    plans = {_text(p.get("shot_id")): _text(p.get("keyframe_plan")) for p in pkg_rows}
    gen_modes = {_text(p.get("shot_id")): _text(p.get("gen_mode")) for p in pkg_rows}
    tight: set[str] = set()
    for shot in (table or {}).get("shots") or []:
        sid = _text(shot.get("shot_id"))
        if _text(shot.get("scale")) in TIGHT_SCALES or _text(shot.get("coverage_type")) in {"close", "reaction"}:
            tight.add(sid)
    for spec in (specs or {}).get("shot_specs") or []:
        if _text(spec.get("shot_size")) in TIGHT_SCALES:
            tight.add(_text(spec.get("shot_id")))
    for item in frames:
        sid = _text(item.get("shot_id")) or "?"
        qc = item.get("qc") or {}
        first = _text(item.get("first_frame_file"))
        last = _text(item.get("last_frame_file"))
        needs_first = gen_modes.get(sid, "i2v_first") not in {"r2v", "video_extend", "edit"}
        if needs_first and not first:
            errors.append(f"{sid} missing first_frame_file")
        for key in KEYFRAME_QC_KEYS:
            if not qc.get(key):
                errors.append(f"{sid} keyframe qc missing {key}")
        if plans.get(sid) == "first_last":
            if not last:
                errors.append(f"{sid} keyframe_plan first_last but no last_frame_file")
            if not qc.get("out_to_readable"):
                errors.append(f"{sid} first_last needs qc.out_to_readable: can a stranger see the out_to change between first and last")
        if sid in tight:
            for key in KEYFRAME_TIGHT_QC_KEYS:
                if not qc.get(key):
                    errors.append(f"{sid} tight shot needs qc.{key}")
        for key, value in qc.items():
            if key in KEYFRAME_QC_TEXT_KEYS:
                continue
            if _text(value) not in KEYFRAME_QC_VALUES:
                errors.append(f"{sid} qc.{key} must be pass / fail / n/a")
        failed_items = [key for key, value in qc.items() if key not in KEYFRAME_QC_TEXT_KEYS and _text(value) == "fail"]
        if failed_items and qc.get("status") == "pass":
            errors.append(f"{sid} has fail items ({', '.join(failed_items)}) but status pass")
        if _text(qc.get("notes")) and qc.get("status") == "pass" and not _text(qc.get("waived_by")):
            errors.append(f"{sid} passes with notes but no waived_by; a nit is a fail unless a human waives it")
        if prod is not None:
            for rel in (first, last):
                if rel and not (Path(prod) / rel).exists():
                    errors.append(f"{sid} frame file missing on disk: {rel}")
        if qc.get("status") != "pass":
            errors.append(f"{sid} keyframe not passed")
    return errors

def validate_clips(data: dict) -> list[str]:
    errors = []
    clips = data.get("clips") or []
    if not clips:
        errors.append("clips empty")
    for item in clips:
        sid = item.get("shot_id") or "?"
        qc = item.get("qc") or {}
        if not _text(item.get("video_file")):
            errors.append(f"{sid} missing video_file")
        if qc.get("status") != "pass":
            errors.append(f"{sid} clip not passed")
        attempts = int(item.get("attempt_no") or 0)
        budget = int((item.get("generation_budget") or {}).get("max_attempts") or 8)
        if attempts >= budget and qc.get("status") != "pass":
            errors.append(f"{sid} hit max_attempts; send back to design")
    return errors

def validate_audio(data: dict, writer: Optional[dict] = None, prod: Optional[Path] = None) -> list[str]:
    errors = []
    allowed = set(_lines_from_writer(writer or {}))
    for take in data.get("dialogue_takes") or []:
        line = _text(take.get("line"))
        if allowed and line not in allowed:
            errors.append("audio has a line not in the script")
    if prod is not None:
        for key in ("ambience_file", "sfx_file", "music_file", "mix_file"):
            rel = _text(data.get(key))
            if rel and not (prod / rel).exists():
                errors.append(f"{key} missing on disk")
    return errors

def validate_cut(data: dict) -> list[str]:
    errors = []
    if not (data.get("timeline") or []):
        errors.append("cut missing timeline")
    if "dropped_shot_ids" not in data:
        errors.append("cut missing dropped_shot_ids")
    if not _text(data.get("final_file")):
        errors.append("cut missing final_file")
    return errors

def snapshot_pipeline(prod: Path) -> dict:
    names = {
        "novel": "novel.json",
        "writer": "writer.json",
        "assets": "assets.json",
        "scene_cards": "scene_cards.json",
        "shot_list": "shot_list.json",
        "shot_specs": "shot_specs.json",
        "frame_descriptions": "frame_descriptions.json",
        "packages": "gen_packages.json",
        "keyframes": "keyframes.json",
        "clips": "clips.json",
        "audio": "audio.json",
        "cut": "cut.json",
        "tickets": "tickets.json",
    }
    out = {"uses_pipeline": uses_pipeline(prod), "artifacts": {}}
    for key, name in names.items():
        data = read_artifact(prod, name)
        count_src = data.get("shots") or data.get("shot_specs") or data.get("packages") or data.get("gen_packages") or data.get("keyframes") or data.get("clips") or data.get("assets") or data.get("scenes") or data.get("scene_cards") or data.get("items") or data.get("timeline") or []
        out["artifacts"][key] = {
            "exists": bool(data),
            "status": data.get("status"),
            "confirmed": packages_confirmed(data) if key == "packages" else None,
            "count": len(count_src) if isinstance(count_src, list) else 0,
        }
    out["tickets"] = (read_artifact(prod, "tickets.json").get("tickets") or [])[-12:]
    return out

def compile_shot_list_from_legacy(prod: Path) -> dict:
    shots = list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])
    rows = []
    for shot in shots:
        coverage = shot.get("setup") or "master"
        coverage_type = "otc" if coverage == "ots" else coverage
        move = _text(shot.get("move") or "static")
        rows.append({
            "shot_id": shot.get("id"),
            "beat": shot.get("new_info") or shot.get("story_function") or shot.get("id"),
            "shot_job": shot.get("shot_job") or shot.get("action") or shot.get("new_info"),
            "coverage_type": coverage_type,
            "dialogue_ref": [shot.get("line")] if shot.get("line") else [],
            "action_ref": shot.get("action"),
            "prev_relation": shot.get("cut"),
            "move_needed": "static" if move == "static" else "move",
            "move_reason": shot.get("move_reason") or shot.get("camera") or "",
            "visual_turn": bool(shot.get("setup") == "insert"),
            "hardest": False,
        })
    return {
        "scene_id": "EP01",
        "shots": rows,
        "left_right_lock": "inherit blocking",
        "whose_pov": "",
        "continuity_bible": {"source": "legacy-shots.json"},
        "visible_change_without_dialogue": "pass",
        "dropped_shots": [],
        "design_steps_done": [1, 2, 3, 4, 5, 6, 7],
        "status": "draft",
        "origin": "legacy-shots",
    }

def compile_specs_from_legacy(prod: Path) -> dict:
    data = load_json(prod, "03-storyboard/shots.json", {"shots": []})
    shots = list(data.get("shots") or [])
    look = ""
    look_path = prod / "02-assets" / "LOOK.md"
    if look_path.exists():
        look = look_path.read_text(encoding="utf-8")[:400]
    aspect = _text(data.get("aspect") or "16:9")
    specs = []
    for i, shot in enumerate(shots):
        prev = shots[i - 1] if i else {}
        nxt = shots[i + 1] if i + 1 < len(shots) else {}
        chars = shot.get("characters") or [""]
        specs.append({
            "shot_id": shot.get("id"),
            "subject": ", ".join(shot.get("characters") or []) or shot.get("setup"),
            "action_now": shot.get("start") or shot.get("action"),
            "dialogue_line": shot.get("line") or "",
            "shot_size": shot.get("scale") or shot.get("setup"),
            "angle": "eye",
            "height": "eye",
            "focal_length": shot.get("lens") or "50mm",
            "aspect_ratio": aspect,
            "move_type": shot.get("move") or "static",
            "move_detail": shot.get("camera") or "",
            "move_reason": shot.get("move_reason") or shot.get("camera") or "hold",
            "intensity": 0 if shot.get("move") == "static" else 3,
            "left": chars[0] if shot.get("axis") == "left" else "",
            "right": chars[-1] if shot.get("axis") == "right" else "",
            "eyeline": shot.get("facing") or "",
            "body_facing": shot.get("facing") or "",
            "hands": shot.get("start") or "",
            "props": shot.get("look") or "",
            "day_night": "dusk" if "dusk" in look.lower() else "day",
            "key_light_dir": "side",
            "quality": "soft",
            "color_mood": look[:80],
            "duration_sec": int(shot.get("seconds") or 4),
            "dialogue_start_sec": 0 if shot.get("line") else None,
            "key_sfx": shot.get("sfx") or "",
            "axis_side": shot.get("axis") or "center",
            "in_from": prev.get("id") or "open",
            "out_to": nxt.get("id") or "hold",
            "costume_state_id": "",
            "location_state_id": shot.get("scene") or "",
        })
    return {"shot_specs": specs, "status": "draft", "origin": "legacy-shots"}

def _asset_file(item: dict) -> str:
    return str(item.get("file") or "").replace("\\", "/").lower()


def _asset_is_face(item: dict) -> bool:
    return _asset_file(item).endswith("face.jpg") or "face" in str(item.get("asset_id") or "").lower()


def _asset_is_night(item: dict) -> bool:
    blob = _asset_file(item) + " " + str(item.get("asset_id") or "").lower()
    return "night" in blob


def _asset_is_wet(item: dict) -> bool:
    blob = _asset_file(item) + " " + str(item.get("asset_id") or "").lower()
    return "wet" in blob or str(item.get("type") or "") == "costume_state"


def _shot_blob(spec: dict, shot: dict) -> str:
    parts = [
        spec.get("shot_id"), spec.get("scene_id"), spec.get("content"), spec.get("subject"),
        spec.get("action_now"), spec.get("left"), spec.get("right"), spec.get("eyeline"),
        spec.get("in_from"), spec.get("out_to"), spec.get("location_state_id"),
        shot.get("shot_id"), shot.get("one_action"), shot.get("shot_job"), shot.get("beat"),
        shot.get("location_id"),
    ]
    for cut in spec.get("internal_cuts") or shot.get("internal_cuts") or []:
        parts.append((cut or {}).get("one_action"))
    return " ".join(_text(part) for part in parts)


def _pick_assets(items: list[dict], bind: str, *, kind: str, night: bool = False, wet: bool = False, faces: bool = False) -> list[str]:
    pool = [item for item in items if _text(item.get("binds_to")) == bind or f"/{bind}/" in _asset_file(item)]
    if kind == "location":
        pool = [item for item in pool if item.get("type") == "location" and _asset_is_night(item) == night]
    elif kind == "character":
        pool = [item for item in pool if item.get("type") in {"character", "costume_state"} and _asset_is_wet(item) == wet]
    elif kind == "prop":
        pool = [item for item in pool if item.get("type") == "prop"]
    masters = [item for item in pool if not _asset_is_face(item)]
    face_items = [item for item in pool if _asset_is_face(item)]
    out = [_text(item.get("asset_id")) for item in masters if item.get("asset_id")]
    if faces:
        out.extend(_text(item.get("asset_id")) for item in face_items if item.get("asset_id"))
    return [item for item in out if item]


def _norm_bind(value: Any) -> str:
    return _text(value).lower().replace("_", "-")


def resolve_cast_bind(cast_id: str, bible: dict, items: list[dict]) -> str:
    """Writer cast id -> assets `binds_to`. Exact, then normalized, then singular, then bible.cast_assets."""
    cast_assets = bible.get("cast_assets") if isinstance(bible.get("cast_assets"), dict) else {}
    if _text(cast_assets.get(cast_id)):
        return _text(cast_assets.get(cast_id))
    binds = {_text(item.get("binds_to")) for item in items}
    for candidate in (cast_id, _norm_bind(cast_id), _norm_bind(cast_id).rstrip("s")):
        if candidate in binds:
            return candidate
    return ""


def _asset_ids(pool: list[dict], *, faces: bool) -> list[str]:
    masters = [item for item in pool if not _asset_is_face(item)]
    face_items = [item for item in pool if _asset_is_face(item)] if faces else []
    return [_text(item.get("asset_id")) for item in masters + face_items if item.get("asset_id")]


def _pick_character_by_state(items: list[dict], bind: str, costume: str, *, faces: bool) -> list[str]:
    """Costume state assets win when one matches the state id; otherwise the base identity assets."""
    from .continuity_hard import costume_aliases

    pool = [item for item in items if _text(item.get("binds_to")) == bind and item.get("type") in {"character", "costume_state"}]
    token = _norm_bind(costume)

    def matches(item: dict) -> bool:
        aliases = costume_aliases(item)
        if aliases:
            return bool(token) and token in aliases
        blob = _norm_bind(_asset_file(item) + " " + _text(item.get("asset_id")))
        return bool(token) and token not in {"base", "default"} and token in blob

    states = [item for item in pool if item.get("type") == "costume_state" or _text(item.get("costume_state") or item.get("costume_state_id"))]
    matched = [item for item in states if matches(item)]
    if matched:
        return _asset_ids(matched, faces=faces)
    base = [item for item in pool if item.get("type") == "character" and not _text(item.get("costume_state") or item.get("costume_state_id"))]
    return _asset_ids(base, faces=faces)


def _pick_location_by_state(items: list[dict], loc_bind: str, variant: str) -> list[str]:
    pool = [
        item for item in items
        if item.get("type") == "location" and (_text(item.get("binds_to")) == loc_bind or f"/{loc_bind}/" in _asset_file(item))
    ]
    if variant:
        token = _norm_bind(variant)
        hit = [item for item in pool if token in _norm_bind(_asset_file(item) + " " + _text(item.get("asset_id")))]
        if hit:
            return _asset_ids(hit, faces=False)
    base = [item for item in pool if f"/{loc_bind}/" in _asset_file(item)]
    return _asset_ids(base or pool, faces=False)


def pov_cast_id(table: dict, writer: Optional[dict]) -> str:
    """`whose_pov` is written as the display name; map it back to the cast id."""
    from .shot_table import cast_names

    pov = _text(table.get("whose_pov"))
    if not pov:
        return ""
    for cid, name in cast_names(writer).items():
        if pov in (cid, name):
            return cid
    return pov


def _refs_from_state(
    spec: dict,
    shot: dict,
    items: list[dict],
    table: dict,
    writer: dict,
    *,
    max_refs: int,
    hard: Optional[dict] = None,
    episode: int = 1,
) -> tuple[list[str], str, str]:
    from .continuity_hard import resolve_costume_token
    from .shot_table import TIGHT_SCALES, bible_prop_index, normalize_state, prop_words

    state = normalize_state(spec.get("state") or shot.get("state")) or {"characters": {}, "props": [], "location": "", "note": ""}
    bible = table.get("continuity_bible") if isinstance(table.get("continuity_bible"), dict) else {}
    prop_index = bible_prop_index(bible)
    pov_id = pov_cast_id(table, writer)
    blob = _shot_blob(spec, shot)
    scale = _text(spec.get("shot_size") or shot.get("scale"))
    coverage = _text(shot.get("coverage_type"))
    tight = scale in TIGHT_SCALES or scale == "pov"
    want_face = (scale or coverage) in {"close", "insert", "otc", "ots", "medium", "med", "reaction", "single"}
    loc = _text(spec.get("location_state_id") or shot.get("location_id"))
    loc_bind = loc.replace("-night", "") if loc else ""
    variant = state["location"] or (loc if loc.endswith("-night") else "")
    refs: list[str] = []

    def add(ids: list[str]) -> None:
        for asset_id in ids:
            if asset_id and asset_id not in refs and len(refs) < max_refs:
                refs.append(asset_id)

    def named(pid: str) -> bool:
        prop = prop_index.get(pid) or {}
        words = prop_words(prop) or [pid]
        return any(word in blob for word in words)

    if loc_bind:
        add(_pick_location_by_state(items, loc_bind, variant))
    pov_bind, pov_costume = "", ""
    for cid, item in state["characters"].items():
        bind = resolve_cast_bind(cid, bible, items)
        if not bind:
            continue
        costume_token = resolve_costume_token(hard, cid, episode, item["costume"])
        if cid == pov_id or (not pov_id and not pov_bind):
            pov_bind, pov_costume = bind, costume_token
        if not item["in_frame"]:
            continue
        add(_pick_character_by_state(items, bind, costume_token, faces=want_face))
        attached = list(item["carrying"]) + ([item["bound_with"]] if item["bound_with"] else [])
        for pid in attached:
            if tight and not named(pid):
                continue
            add(_pick_assets(items, pid, kind="prop"))
    for pid in state["props"]:
        if tight and not named(pid):
            continue
        add(_pick_assets(items, pid, kind="prop"))
    if not pov_bind and state["characters"]:
        first = next(iter(state["characters"].items()))
        pov_bind = resolve_cast_bind(first[0], bible, items)
        pov_costume = resolve_costume_token(hard, first[0], episode, first[1]["costume"])
    costume = f"{pov_bind}-{pov_costume}" if pov_bind and pov_costume else ""
    location_id = variant or loc_bind
    return refs, costume, location_id


def _refs_by_name(spec: dict, shot: dict, items: list[dict], table: dict, writer: dict, *, max_refs: int) -> tuple[list[str], str, str]:
    """No state on the shot: match cast display names and prop words in the text. Emits nothing model-specific."""
    from .shot_table import bible_prop_index, cast_names, prop_words

    bible = table.get("continuity_bible") if isinstance(table.get("continuity_bible"), dict) else {}
    blob = _shot_blob(spec, shot)
    scale = _text(spec.get("shot_size") or shot.get("scale") or shot.get("coverage_type"))
    want_face = scale in {"close", "insert", "otc", "ots", "medium", "med", "reaction", "single"}
    loc = _text(spec.get("location_state_id") or shot.get("location_id"))
    loc_bind = loc.replace("-night", "") if loc else ""
    refs: list[str] = []

    def add(ids: list[str]) -> None:
        for asset_id in ids:
            if asset_id and asset_id not in refs and len(refs) < max_refs:
                refs.append(asset_id)

    if loc_bind:
        add(_pick_location_by_state(items, loc_bind, loc if loc.endswith("-night") else ""))
    for cid, name in cast_names(writer).items():
        if name and name in blob:
            bind = resolve_cast_bind(cid, bible, items)
            if bind:
                add(_pick_character_by_state(items, bind, "", faces=want_face))
    prop_index = bible_prop_index(bible)
    for item in items:
        if item.get("type") != "prop":
            continue
        bind = _text(item.get("binds_to"))
        words = prop_words(prop_index.get(bind) or {}) + [bind, _text(item.get("name"))]
        if any(word and word in blob for word in words):
            add([_text(item.get("asset_id"))])
    return refs, "", loc_bind


def package_ref_files(prod: Path, refs: list[str], assets: dict) -> list[str]:
    """Resolve package asset_ids to on-disk files. Character identity prefers face.jpg when present."""
    by_id = {item.get("asset_id"): item for item in (assets.get("assets") or []) if item.get("asset_id")}
    files: list[str] = []
    seen: set[str] = set()

    def add(rel: str) -> None:
        path = str(rel or "").replace("\\", "/")
        if not path or path in seen:
            return
        if not (prod / path).exists():
            return
        seen.add(path)
        files.append(path)

    for rid in refs:
        item = by_id.get(rid) or {}
        rel = _text(item.get("file"))
        kind = _text(item.get("type"))
        if kind in {"character", "costume_state"} and rel.endswith("master.jpg"):
            face = rel[: -len("master.jpg")] + "face.jpg"
            add(face)
            add(rel)
        else:
            add(rel)
    return files


def compile_packages_for_profiles(
    prod: Path,
    profiles: Optional[list[str]] = None,
    *,
    table: Optional[dict] = None,
    specs: Optional[dict] = None,
) -> dict[str, dict]:
    """Same shot table / specs, one package tree per video profile. Prompts are not rewritten by hand."""
    from .video_profiles import get_profile

    shot_list = table if table is not None else read_artifact(prod, "shot_list.json")
    if specs is None:
        if str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA:
            from .shot_table import compile_specs_from_shot_table

            specs = compile_specs_from_shot_table(shot_list, aspect=shot_list.get("aspect") or "16:9")
        else:
            specs = read_artifact(prod, "shot_specs.json") or compile_specs_from_legacy(prod)
    wanted = [get_profile(name)["id"] for name in (profiles or ["seedance_2_0", "seedance_2_5"])]
    out: dict[str, dict] = {}
    for pid in wanted:
        payload = compile_packages_from_specs(prod, target_model=pid, table=shot_list, specs=specs)
        payload["profile"] = pid
        payload["episode_target_model"] = pid
        out[pid] = payload
    return out


def asset_refs_for_package(
    spec: dict,
    shot: dict,
    assets: dict,
    *,
    max_refs: int = 9,
    table: Optional[dict] = None,
    writer: Optional[dict] = None,
    hard: Optional[dict] = None,
    episode: int = 1,
) -> tuple[list[str], str, str]:
    """(asset_refs, costume_state_id, location_id) for one package.

    With a per-shot `state` this is a lookup, not a guess: characters in frame, their costume state,
    what they carry or are bound with, the props listed, the location plate variant. Without state it
    falls back to matching writer cast names and prop words in the shot text.
    """
    items = [item for item in (assets.get("assets") or []) if item.get("asset_id")]
    table = table or {}
    if isinstance(spec.get("state") or shot.get("state"), dict):
        return _refs_from_state(
            spec, shot, items, table, writer or {}, max_refs=max_refs, hard=hard, episode=episode
        )
    return _refs_by_name(spec, shot, items, table, writer or {}, max_refs=max_refs)


def package_gen_mode(spec: dict, shot: dict, profile: Optional[dict] = None) -> tuple[str, str]:
    planned = _text(shot.get("keyframe_plan") or spec.get("keyframe_plan"))
    if planned in {"first", "first_last"}:
        return ("flf2v" if planned == "first_last" else "i2v_first"), planned
    coverage = _text(shot.get("coverage_type") or spec.get("coverage_type"))
    size = _text(spec.get("shot_size") or shot.get("scale"))
    move = _text(spec.get("move_type") or shot.get("move_type"))
    cuts = spec.get("internal_cuts") or shot.get("internal_cuts") or []
    if size == "insert" and move == "static":
        return "i2v_first", "first"
    from .video_profiles import allows_internal_cuts

    if cuts and allows_internal_cuts(profile):
        return "flf2v", "first_last"
    if coverage == "continuous":
        return "video_extend", "first"
    if coverage in {"reaction", "close"}:
        return "i2v_first", "first"
    if move not in {"", "static"} and _text(spec.get("in_from")) and _text(spec.get("out_to")):
        return "flf2v", "first_last"
    return "i2v_first", "first"


_EPISODE_TOKEN = re.compile(r"^(?:ep)?(\d{1,2})(?:[-_](.+))?$", re.I)
_ARTIFACT_LABEL = re.compile(r"^(?P<stem>.+)\.(?P<label>ep\d{2}(?:-[A-Za-z0-9]+)?)\.json$", re.I)


def parse_episode(episode: Any = 1) -> tuple[int, str]:
    """Return (episode_no, artifact/folder label).

    1 / '1' / 'ep01' → (1, '') so EP01 keeps historical unsuffixed names.
    2 / '2' / 'ep02' → (2, 'ep02')
    'ep01-v2' → (1, 'ep01-v2') — labeled variant, never clobbers the live lock.
    """
    if episode is None or episode == "":
        return 1, ""
    if isinstance(episode, bool):
        raise ValueError("episode 不能是 bool")
    if isinstance(episode, int):
        n = int(episode)
        if n < 1:
            raise ValueError("episode 必须 >= 1")
        return n, "" if n == 1 else f"ep{n:02d}"
    text = _text(episode)
    if text.isdigit():
        n = int(text)
        if n < 1:
            raise ValueError("episode 必须 >= 1")
        return n, "" if n == 1 else f"ep{n:02d}"
    match = _EPISODE_TOKEN.fullmatch(text)
    if not match:
        raise ValueError(f"看不懂的 episode 标签：{text}")
    n = int(match.group(1))
    extra = (match.group(2) or "").strip()
    if extra:
        return n, f"ep{n:02d}-{extra}"
    return n, "" if n == 1 else f"ep{n:02d}"


def episode_number(episode: Any = 1) -> int:
    return parse_episode(episode)[0]


def episode_label(episode: Any = 1) -> str:
    return parse_episode(episode)[1]


def episode_artifact_name(base: str, episode: Any = 1) -> str:
    """EP01 keeps historical filenames; later episodes / labels use `stem.<label>.ext`."""
    label = episode_label(episode)
    if not label:
        return base
    if "." not in base:
        return f"{base}.{label}"
    stem, ext = base.rsplit(".", 1)
    return f"{stem}.{label}.{ext}"


def parse_artifact_filename(name: str) -> tuple[str, Any]:
    """Map `shot_list.ep02.json` / `shot_list.ep01-v2.json` back to (kind, episode token)."""
    raw = _text(name)
    if not raw.endswith(".json"):
        raw = raw + ".json"
    match = _ARTIFACT_LABEL.fullmatch(raw)
    if not match:
        return raw, 1
    return f"{match.group('stem')}.json", match.group("label")


def episode_frame_dir(episode: Any = 1) -> str:
    """EP01 live lock → 04-frames/; EP02 → 04-frames/ep02/; ep01-v2 → 04-frames/ep01-v2/."""
    label = episode_label(episode)
    return "04-frames" if not label else f"04-frames/{label}"


def episode_shot_dir(episode: Any = 1) -> str:
    label = episode_label(episode)
    return "05-shots" if not label else f"05-shots/{label}"


def load_sets_for_episode(prod: Path, episode: Any = 1) -> dict:
    """`03-storyboard/sets.json` for EP01, `sets.epNN.json` for later episodes (falls back to sets.json)."""
    try:
        ep = int(episode or 1)
    except (TypeError, ValueError):
        ep = 1
    if ep != 1:
        data = load_json(prod, f"03-storyboard/sets.ep{ep:02d}.json", {})
        if data.get("sets"):
            return data
    return load_json(prod, "03-storyboard/sets.json", {"sets": []})


def compile_packages_from_specs(
    prod: Path,
    target_model: Optional[str] = None,
    *,
    table: Optional[dict] = None,
    specs: Optional[dict] = None,
    writer: Optional[dict] = None,
    frame_descriptions: Optional[dict] = None,
) -> dict:
    from .prompts import (
        compile_keyframe_prompt_zh,
        compile_reference_roles_zh,
        compile_seedance_motion_from_spec,
        compile_seedance_prompt,
        compile_still_prompt,
        compile_video_prompt,
        has_reference_roles,
        still_refs,
        video_mode,
    )
    from .show_policy import load_show_policy
    from .video_profiles import get_profile

    shot_list = table if table is not None else read_artifact(prod, "shot_list.json")
    from .vendor_request import resolve_package_models

    raw_choice = _text(target_model) or _text(shot_list.get("target_model")) or "minimax_h3"
    profile = get_profile(raw_choice)
    capability_id, paid_model, vendor_model_id = resolve_package_models(raw_choice)
    target_model = paid_model
    min_sec = int(profile.get("min_shot_sec") or 4)
    max_sec = int(profile.get("max_shot_sec") or 15)
    max_refs = int(profile.get("max_ref_images") or 9)
    look_blob = ""
    try:
        from .production import read_text as _read_text

        look_blob = _read_text(prod, "02-assets/LOOK.md") + _read_text(prod, "01-bible/confirm.md")
    except Exception:
        look_blob = ""
    khmerless_plates = "板上无高棉文" in look_blob or "khmerless" in look_blob.lower()
    if specs is None:
        specs = read_artifact(prod, "shot_specs.json")
    if not specs.get("shot_specs"):
        if table is not None:
            from .shot_table import compile_specs_from_shot_table

            specs = compile_specs_from_shot_table(shot_list, aspect=shot_list.get("aspect") or "16:9")
        else:
            specs = compile_specs_from_legacy(prod)
    assets = read_artifact(prod, "assets.json")
    table_shots = {item.get("shot_id"): item for item in shot_list.get("shots") or [] if item.get("shot_id")}
    legacy_shots = {shot.get("id"): shot for shot in (load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])}
    lang = "zh" if capability_id in MODELS_ZH or target_model in MODELS_ZH else "en"
    use_table = str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA
    episode_no = int(shot_list.get("episode_no") or 1)
    from .continuity_hard import hard_items_for_state, load_continuity_hard, package_binding

    hard = load_continuity_hard(prod)
    if writer is None:
        writer = read_artifact(prod, episode_artifact_name("writer.json", episode_no)) or read_artifact(prod, "writer.json")
    from .shot_table import normalize_state, state_sentence

    bible = shot_list.get("continuity_bible") if isinstance(shot_list.get("continuity_bible"), dict) else {}
    from .frame_desc import description_sentence, index_by_shot

    if frame_descriptions is None:
        frame_descriptions = read_artifact(prod, episode_artifact_name("frame_descriptions.json", episode_no)) or read_artifact(prod, "frame_descriptions.json")
    descriptions = index_by_shot(frame_descriptions)
    # Hell Grind grafts: GEO block per set, voice / descriptor cards per character, native speech.
    from .acting import compile_acting_zh, merge_acting, text_acting_warnings
    from .continuity_hard import resolve_costume_token
    from .frame_desc import acting_text_fields, normalize_item as normalize_frame_item

    def frame_item_acting_warnings(item: dict) -> list[str]:
        norm = normalize_frame_item(item)
        return text_acting_warnings(norm["shot_id"], acting_text_fields(norm))
    from .prompts import (
        MAX_ZH_PROMPT_CHARS,
        TRIM_LABEL_ZH,
        compile_seedance_motion_detail,
        geo_layout_for,
        load_ban_dictionary,
        shot_dialogue_items,
    )
    from .shot_table import cast_names
    from .speech import (
        DEFAULT_DIALOGUE_LANGUAGE,
        cards_by_name,
        check_dialogue_language,
        compile_audio_block,
        descriptor_for,
        load_character_cards,
        sound_bed_for,
        speech_mode_for,
        voice_card_for,
    )

    sets = load_sets_for_episode(prod, episode_no)
    cast = cast_names(writer)
    cast_id_by_name = {name: cid for cid, name in cast.items() if name}
    cards = cards_by_name(load_character_cards(prod), cast)
    ban_dictionary = load_ban_dictionary(prod)
    speech_mode = speech_mode_for(shot_list, profile) if lang == "zh" else "post_dub"
    table_language = _text(shot_list.get("dialogue_language")) or DEFAULT_DIALOGUE_LANGUAGE
    geo_warned: set[str] = set()
    warnings: list[str] = []
    compile_errors: list[str] = []
    post_under_native: list[str] = []
    packages = []
    for spec in specs.get("shot_specs") or []:
        sid = spec.get("shot_id")
        table_shot = table_shots.get(sid) or {}
        legacy = legacy_shots.get(sid) or {}
        frame_desc = descriptions.get(sid)
        if use_table or not (legacy.get("start") or legacy.get("video_prompt")):
            state = normalize_state(spec.get("state") or table_shot.get("state"))
            if use_table and state is None:
                warnings.append(f"{sid} has no state; asset refs guessed from names")
            refs, costume, location_id = asset_refs_for_package(
                spec,
                table_shot,
                assets,
                max_refs=max_refs,
                table=shot_list,
                writer=writer,
                hard=hard,
                episode=episode_no,
            )
            gen_mode, plan = package_gen_mode(spec, table_shot, profile)
            raw_dur = spec.get("duration_sec") or table_shot.get("duration_sec") or min_sec
            try:
                paper_sec = float(raw_dur)
            except (TypeError, ValueError):
                paper_sec = float(min_sec)
            if paper_sec > max_sec:
                compile_errors.append(
                    f"{sid} duration {paper_sec:g}s exceeds {target_model} max {max_sec}s; replan, do not clamp"
                )
                render_sec = int(round(paper_sec))
            elif paper_sec < min_sec:
                render_sec = int(min_sec)
            else:
                render_sec = int(round(paper_sec))
            duration_sec = paper_sec if shot_list.get("keep_paper_duration") else render_sec
            # Who is in frame (display names), who speaks, what each looks like.
            in_frame = [_text(name) for name in (table_shot.get("characters") or []) if _text(name)]
            if not in_frame and state:
                in_frame = [cast.get(cid, cid) for cid, item in state["characters"].items() if item.get("in_frame", True)]
            lines = shot_dialogue_items(spec, table_shot)
            if len(lines) > 2:
                warnings.append(
                    f"{sid} has {len(lines)} dialogue lines; Seedance line budget is 2 — replan, do not truncate"
                )
            speakers = [item["character"] for item in lines if item.get("character")]
            # dialogue_delivery is the per-shot switch: on_camera = the model speaks it (native),
            # post = dubbed later. Under a native table a `post` shot opts out to post_dub.
            delivery = _text(table_shot.get("dialogue_delivery")) or ("post" if lines else "none")
            shot_speech_mode = speech_mode
            if lines and speech_mode == "seedance_native" and delivery == "post":
                shot_speech_mode = "post_dub"
                post_under_native.append(_text(sid))
            dialogue_language = _text(table_shot.get("dialogue_language")) or table_language
            dialogue_language = check_dialogue_language(dialogue_language, speech_mode=shot_speech_mode, shot_id=_text(sid))
            if frame_desc:
                warnings.extend(frame_item_acting_warnings(frame_desc))
            descriptors: list[str] = []
            for name in in_frame:
                cid = cast_id_by_name.get(name, name)
                declared = ((state or {}).get("characters") or {}).get(cid, {}).get("costume", "") if state else ""
                sentence = descriptor_for(name, cards, resolve_costume_token(hard, cid, episode_no, declared))
                if sentence:
                    descriptors.append(sentence)
            geo_layout = geo_layout_for(location_id or spec.get("location_state_id"), sets) if lang == "zh" else ""
            loc_key = _text(location_id or spec.get("location_state_id"))
            known_set = any(isinstance(s, dict) and _text(s.get("id")) == loc_key for s in sets.get("sets") or [])
            if lang == "zh" and known_set and not geo_layout and loc_key not in geo_warned:
                geo_warned.add(loc_key)
                warnings.append(f"set {loc_key} has no geo_zh / axis in sets.json; shots there carry no GEO block")
            voice_card = {name: voice_card_for(name, cards) for name in speakers}
            audio_block = ""
            acting_lines: list[str] = []
            if lang == "zh":
                audio_block = compile_audio_block(
                    lines if shot_speech_mode == "seedance_native" else [],
                    cards=cards,
                    in_frame=in_frame,
                    key_sfx=list(spec.get("key_sfx") or table_shot.get("key_sfx") or []),
                    sound_bed=sound_bed_for(loc_key, sets),
                    language=dialogue_language,
                )
                acting_lines = compile_acting_zh(
                    table_shot, spec, in_frame=in_frame, speakers=speakers, override=(frame_desc or {}).get("acting")
                )
            policy = load_show_policy(prod)
            prompt_spec = dict(spec)
            prompt_spec.setdefault("aspect_ratio", shot_list.get("aspect") or policy.aspect)
            prompt_spec.setdefault("art_direction", policy.art_direction)
            if lang == "zh":
                image_prompt = compile_keyframe_prompt_zh(
                    prompt_spec, table_shot, frame_desc=frame_desc, slot="first", geo_layout=geo_layout, descriptors=descriptors
                )
                if len(refs) > 1 and not has_reference_roles(image_prompt):
                    image_prompt += compile_reference_roles_zh(refs, assets)
            else:
                from .still_t0 import first_still_text

                start = _text(spec.get("in_from") or table_shot.get("in_from"))
                still = first_still_text(frame_desc) if frame_desc else ""
                image_prompt = still or start or _text(spec.get("subject"))
                if frame_desc:
                    image_prompt = (image_prompt + " " + description_sentence(frame_desc)).strip()
            if khmerless_plates:
                image_prompt = (
                    image_prompt.rstrip()
                    + "底板无高棉文、无汉字；厂牌拉丁文可留；不要让模型在招牌或工牌上新写高棉文。"
                )
            motion_detail: dict = {}
            if lang == "zh":
                motion_detail = compile_seedance_motion_detail(
                    spec,
                    table_shot,
                    profile,
                    geo_layout=geo_layout,
                    descriptors=descriptors,
                    acting_lines=acting_lines,
                    audio_block=audio_block,
                    speech_mode=shot_speech_mode,
                    render_sec=render_sec,
                    ban_dictionary=ban_dictionary,
                )
                motion = motion_detail["prompt"]
                if motion_detail.get("dropped"):
                    dropped = "、".join(TRIM_LABEL_ZH.get(t, t) for t in motion_detail["dropped"])
                    warnings.append(f"{sid} motion prompt trimmed ({dropped}); now {motion_detail['chars']} chars")
                if motion_detail.get("over_limit"):
                    warnings.append(
                        f"{sid} motion prompt {motion_detail['chars']} chars > {MAX_ZH_PROMPT_CHARS} after trim; "
                        "line / voice card / GEO / timing kept"
                    )
                    logger.warning("%s motion prompt %s chars > %s after trim", sid, motion_detail["chars"], MAX_ZH_PROMPT_CHARS)
            else:
                motion = _text(spec.get("move_detail") or spec.get("action_now"))
            pov_state = None
            if state:
                pov_id = pov_cast_id(shot_list, writer)
                pov_state = state["characters"].get(pov_id) or next(iter(state["characters"].values()), None)
            hard_list = hard_items_for_state(hard, episode_no, state) if state else []
            from .codex_stills import StillPackError, last_still_pack_report, missing_costume_state_files, pack_codex_still_refs
            from .prompts import rewrite_still_prompt

            for msg in missing_costume_state_files(prod, refs, assets):
                compile_errors.append(f"{sid} {msg}")
            loc_file = ""
            by_id = {item.get("asset_id"): item for item in (assets.get("assets") or []) if item.get("asset_id")}
            for rid in refs:
                item = by_id.get(rid) or {}
                if item.get("type") == "location":
                    loc_file = _text(item.get("file")).replace(chr(92), "/")
                    break
            if not loc_file and location_id:
                loc_file = f"02-assets/scenes/{_text(location_id)}/master.jpg"
            still_files: list[str] = []
            if loc_file and not any(item.startswith(f"{sid} ") and "file missing:" in item for item in compile_errors):
                try:
                    still_files = pack_codex_still_refs(
                        prod,
                        parent=loc_file,
                        state=state,
                        assets=assets,
                        table=shot_list,
                        hard=hard,
                        episode=episode_no,
                        strict_existing=False,
                    )
                    report = last_still_pack_report()
                    if report.get("dropped"):
                        warnings.append(f"{sid} {report.get('risk') or 'still-ref over budget'}")
                except StillPackError as exc:
                    compile_errors.append(f"{sid} {exc}")
            still_image_prompt = rewrite_still_prompt(image_prompt, still_files, assets) if still_files else ""
            packages.append({
                "shot_id": sid,
                "target_model": target_model,
                "vendor_model": vendor_model_id,
                "capability_profile_id": capability_id,
                "episode_target_model": target_model,
                "profile": capability_id,
                "asset_refs": refs,
                "ref_files": package_ref_files(prod, refs, assets),
                "still_ref_files": still_files,
                "still_image_prompt": still_image_prompt,
                "keyframe_plan": plan,
                "keyframe_files": [],
                "image_prompt": image_prompt,
                **(
                    {
                        "last_image_prompt": compile_keyframe_prompt_zh(
                            prompt_spec, table_shot, frame_desc=frame_desc, slot="last"
                        )
                    }
                    if lang == "zh" and plan == "first_last"
                    else {}
                ),
                "motion_prompt": motion,
                "prompt_language": lang,
                "gen_mode": gen_mode,
                "duration_sec": duration_sec,
                "aspect_ratio": spec.get("aspect_ratio") or shot_list.get("aspect") or "16:9",
                "continuity": {
                    "left": spec.get("left"),
                    "right": spec.get("right"),
                    "eyeline": spec.get("eyeline"),
                    "costume_state_id": spec.get("costume_state_id") or costume,
                    "location_id": location_id or spec.get("location_state_id"),
                    "binding": package_binding((pov_state or {}).get("binding", ""), hard_list),
                    "bound_with": (pov_state or {}).get("bound_with", ""),
                    "hard_items": hard_list,
                },
                "state": state,
                "state_note": state_sentence(state, bible) if state else "",
                "frame_description": _text((frame_desc or {}).get("one_paragraph")),
                "dialogue_line": spec.get("dialogue_line") or "",
                "dialogue_lines": [item["line"] for item in lines],
                "dialogue_language": dialogue_language,
                "speech_mode": shot_speech_mode,
                "dialogue_delivery": delivery,
                "voice_card": voice_card,
                "audio_block": audio_block,
                "geo_layout": geo_layout,
                "descriptor": descriptors,
                "acting": merge_acting(table_shot.get("acting"), (frame_desc or {}).get("acting")),
                "action_timing": motion_detail.get("beats") or [],
                "motion_prompt_chars": len(motion),
                "motion_prompt_trimmed": motion_detail.get("dropped") or [],
                "parent_hint": _text(table_shot.get("still_parent")),
                "paper_duration_sec": paper_sec,
                "render_duration_sec": render_sec,
                "seedance_min_sec": min_sec,
                "seedance_max_sec": max_sec,
                "confirmed": False,
                "generate_audio": True,
                "ref_exclusivity": (
                    "first_frame_xor_reference_image"
                    if target_model in {"seedance_2_5", "minimax_h3", "wan_3"}
                    else "first_frame_may_include_refs"
                ),
            })
            continue
        refs = still_refs(prod, legacy) if legacy else []
        mode = video_mode(legacy, "designed_frame", refs) if legacy else "i2v"
        gen_mode = "flf2v" if mode == "flf" else "i2v_first"
        image_prompt = compile_still_prompt(legacy) if legacy else _text(spec.get("action_now"))
        if lang == "zh":
            motion = compile_seedance_prompt(legacy, spec)
        else:
            motion = compile_video_prompt(legacy, silent=True, refs=refs)
        packages.append({
            "shot_id": sid,
            "target_model": target_model,
            "vendor_model": vendor_model_id,
            "capability_profile_id": capability_id,
            "episode_target_model": target_model,
            "asset_refs": [_text(item.get("asset_id")) for item in (assets.get("assets") or []) if item.get("asset_id")][:9],
            "keyframe_plan": "first_last" if gen_mode == "flf2v" else "first",
            "keyframe_files": [],
            "image_prompt": image_prompt,
            "motion_prompt": motion,
            "prompt_language": lang,
            "gen_mode": gen_mode,
            "duration_sec": spec.get("duration_sec") or legacy.get("seconds") or 4,
            "aspect_ratio": spec.get("aspect_ratio") or "16:9",
            "continuity": {
                "left": spec.get("left"),
                "right": spec.get("right"),
                "eyeline": spec.get("eyeline"),
                "costume_state_id": spec.get("costume_state_id"),
                "location_id": spec.get("location_state_id") or legacy.get("scene"),
            },
            "dialogue_line": spec.get("dialogue_line") or "",
            "dialogue_language": "zh" if spec.get("dialogue_line") else "",
            "confirmed": False,
        })
    origin = "compiled-from-shot-table" if use_table else "compiled"
    payload = {
        "packages": packages,
        "episode_target_model": target_model,
        "profile": capability_id,
        "vendor_model": vendor_model_id,
        "capability_profile_id": capability_id,
        "status": "draft",
        "confirmed": False,
        "origin": origin,
        "speech_mode": speech_mode,
        "dialogue_language": table_language,
        "prompt_char_limit": MAX_ZH_PROMPT_CHARS,
    }
    if post_under_native:
        warnings.append(
            f"{len(post_under_native)} shots with lines carry dialogue_delivery=post under speech_mode=seedance_native → "
            f"those shots are post_dub (no native line): {', '.join(post_under_native)}. "
            "Write on_camera on the shot (or leave it unset) to have Seedance speak the line."
        )
    if warnings:
        payload["warnings"] = warnings
    if compile_errors:
        payload["errors"] = compile_errors
    return payload

def compile_assets_from_folder(prod: Path) -> dict:
    assets = []
    if (prod / "02-assets" / "LOOK.md").exists():
        assets.append({"asset_id": "STYLE_LOCK_V1", "type": "style", "name": "look", "binds_to": "episode", "file": "02-assets/LOOK.md", "what_it_locks": "look", "version": "v1", "lock_card": [], "image_prompt": "", "quality_layer": DEFAULT_ANTI_PLASTIC, "anti_plastic": DEFAULT_ANTI_PLASTIC})
    char_root = prod / "02-assets" / "characters"
    if char_root.exists():
        for child in sorted(char_root.iterdir()):
            if child.is_dir() and (child / "master.jpg").exists():
                assets.append({"asset_id": f"CHAR_{child.name.upper()}_V1", "type": "character", "name": child.name, "binds_to": child.name, "file": str((child / "master.jpg").relative_to(prod)), "what_it_locks": "identity", "version": "v1", "lock_card": [{"key": "slug", "value": child.name, "source": "script"}], "image_prompt": f"character passport for {child.name}, neutral stance", "quality_layer": DEFAULT_ANTI_PLASTIC})
    scene_root = prod / "02-assets" / "scenes"
    if scene_root.exists():
        for child in sorted(scene_root.iterdir()):
            if child.is_dir() and (child / "master.jpg").exists():
                assets.append({"asset_id": f"LOC_{child.name.upper()}_V1", "type": "location", "name": child.name, "binds_to": child.name, "file": str((child / "master.jpg").relative_to(prod)), "what_it_locks": "space", "version": "v1", "lock_card": [{"key": "location_id", "value": child.name, "source": "script"}], "image_prompt": f"empty location {child.name}"})
    prop_root = prod / "02-assets" / "props"
    if prop_root.exists():
        for child in sorted(prop_root.iterdir()):
            file = child / "master.jpg" if child.is_dir() else child
            if file.exists() and file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                slug = child.name if child.is_dir() else child.stem
                assets.append({"asset_id": f"PROP_{slug.upper()}_V1", "type": "prop", "name": slug, "binds_to": slug, "file": str(file.relative_to(prod)), "what_it_locks": "prop", "version": "v1", "lock_card": [], "image_prompt": f"hero prop {slug}"})
    return {"assets": assets, "status": "draft", "origin": "folder"}

def confirm_packages(prod: Path, confirmed: bool = True) -> dict:
    data = read_artifact(prod, "gen_packages.json")
    if not (data.get("packages") or data.get("gen_packages")):
        data = compile_packages_from_specs(prod)
    packages = data.get("packages") or data.get("gen_packages") or []
    assets = read_artifact(prod, "assets.json")
    specs = read_artifact(prod, "shot_specs.json")
    raise_if(validate_packages({"packages": packages, "episode_target_model": data.get("episode_target_model")}, assets, specs))
    for item in packages:
        item["confirmed"] = bool(confirmed)
    data["packages"] = packages
    data["confirmed"] = bool(confirmed)
    data["status"] = "ready" if confirmed else "draft"
    return write_artifact(prod, "gen_packages.json", data)

def assert_packages_confirmed(prod: Path, episode: Any = 1) -> None:
    if not uses_pipeline(prod):
        return
    data = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    if not data:
        return
    if not packages_confirmed(data):
        raise PermissionError("packages not confirmed")

def assert_keyframes_passed(prod: Path, episode: Any = 1) -> None:
    if not uses_pipeline(prod):
        return
    data = read_artifact(prod, episode_artifact_name("keyframes.json", episode))
    if not data:
        return
    raise_if(validate_keyframes(data, **keyframe_context(prod, episode)))

def assert_clips_passed(prod: Path, episode: Any = 1) -> None:
    if not uses_pipeline(prod):
        return
    data = read_artifact(prod, episode_artifact_name("clips.json", episode))
    if not data:
        return
    raise_if(validate_clips(data))

def record_ticket(prod: Path, ticket: dict) -> dict:
    data = read_artifact(prod, "tickets.json", {"tickets": []})
    tickets = list(data.get("tickets") or [])
    item = {"at": int(time.time()), "type": ticket.get("type") or "reject", "from_agent": ticket.get("from_agent") or "", "send_back_to": ticket.get("send_back_to") or "", "reason": ticket.get("reason") or "", "evidence": ticket.get("evidence") or "", "force_lock": bool(ticket.get("force_lock"))}
    tickets.append(item)
    data["tickets"] = tickets[-50:]
    write_artifact(prod, "tickets.json", data)
    return item

def reject_to(prod: Path, *, from_agent: str, send_back_to: str, reason: str, evidence: str = "", ticket_type: str = "reject") -> dict:
    if send_back_to not in REJECT_TARGETS:
        raise ValueError("cannot reject to " + send_back_to)
    ticket = record_ticket(prod, {"type": ticket_type, "from_agent": from_agent, "send_back_to": send_back_to, "reason": reason, "evidence": evidence})
    from .agents import UNLOCK_DOWNSTREAM
    approvals = load_approvals(prod)
    for later in [send_back_to] + UNLOCK_DOWNSTREAM.get(send_back_to, []):
        (approvals.get("gates") or {}).pop(later, None)
    approvals.setdefault("gates", {})
    save_approvals(prod, approvals)
    return {"ok": True, "ticket": ticket, "reject_to": send_back_to}

def duration_for_shot(prod: Path, shot_id: str, fallback: float) -> float:
    specs = read_artifact(prod, "shot_specs.json")
    for spec in specs.get("shot_specs") or []:
        if spec.get("shot_id") == shot_id:
            try:
                return float(spec.get("duration_sec") or fallback)
            except (TypeError, ValueError):
                return fallback
    cut = read_artifact(prod, "cut.json")
    for item in cut.get("timeline") or []:
        if item.get("shot_id") == shot_id:
            try:
                return max(0.1, float(item.get("out_point") or fallback) - float(item.get("in_point") or 0))
            except (TypeError, ValueError):
                return fallback
    return fallback

def default_cut_from_specs(prod: Path, shot_ids: list[str]) -> dict:
    specs = {item.get("shot_id"): item for item in (read_artifact(prod, "shot_specs.json").get("shot_specs") or [])}
    timeline = []
    for sid in shot_ids:
        spec = specs.get(sid) or {}
        duration = float(spec.get("duration_sec") or 4)
        timeline.append({"shot_id": sid, "in_point": 0, "out_point": duration, "used": True})
    return {"episode_no": 1, "timeline": timeline, "dropped_shot_ids": [], "final_file": "06-export/ep01.mp4", "hook_landed": True, "cliffhanger_landed": True, "status": "draft"}

def seed_pipeline_drafts(prod: Path, force: bool = False) -> dict:
    written = []
    locked_legacy = (prod / "03-storyboard" / "shots.json").exists() and not force and not uses_pipeline(prod)
    if locked_legacy:
        return {"written": [], "pipeline": snapshot_pipeline(prod), "skipped": "legacy-locked"}
    if not read_artifact(prod, "assets.json"):
        write_artifact(prod, "assets.json", compile_assets_from_folder(prod))
        written.append("assets.json")
    if not read_artifact(prod, "shot_list.json") and (prod / "03-storyboard" / "shots.json").exists():
        write_artifact(prod, "shot_list.json", compile_shot_list_from_legacy(prod))
        written.append("shot_list.json")
    if not read_artifact(prod, "shot_specs.json") and (prod / "03-storyboard" / "shots.json").exists():
        write_artifact(prod, "shot_specs.json", compile_specs_from_legacy(prod))
        written.append("shot_specs.json")
    if not read_artifact(prod, "gen_packages.json") and read_artifact(prod, "shot_specs.json"):
        write_artifact(prod, "gen_packages.json", compile_packages_from_specs(prod))
        written.append("gen_packages.json")
    return {"written": written, "pipeline": snapshot_pipeline(prod)}


def preview_artifact(prod: Path, name: str) -> dict:
    data = read_artifact(prod, name)
    if data:
        return data
    if name == "assets.json":
        return compile_assets_from_folder(prod)
    if name == "shot_list.json":
        return compile_shot_list_from_legacy(prod)
    if name == "shot_specs.json":
        return compile_specs_from_legacy(prod)
    if name == "gen_packages.json":
        return compile_packages_from_specs(prod)
    if name == "cut.json":
        shots = list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])
        return default_cut_from_specs(prod, [shot.get("id") for shot in shots if shot.get("id")])
    return {}
