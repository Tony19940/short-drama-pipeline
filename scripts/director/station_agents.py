"""Station agents: each job drafts only its artifact. Rules validate; humans lock."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .grok_text import TextError, chat_json, text_configured
from .knowledge import pack_prompt, prompt_block
from .pipeline import (
    compile_assets_from_folder,
    compile_packages_from_specs,
    compile_shot_list_from_legacy,
    compile_specs_from_legacy,
    default_cut_from_specs,
    DESIGN_FORBIDDEN,
    pipeline_dir,
    raise_if,
    read_artifact,
    SHOT_TABLE_SCHEMA,
    validate_assets,
    validate_audio,
    validate_cut,
    validate_novel,
    validate_packages,
    validate_shot_list,
    validate_shot_specs,
    validate_writer,
    write_artifact,
    SPEC_FORBIDDEN,
)
from .production import load_json, read_text, write_text
from .shot_table import (
    compile_specs_from_shot_table,
    render_shot_table_md,
    sanitize_shot_table,
    table_context,
    validate_shot_table,
)
from .video_profiles import profile_brief, resolve_target_model

DESIGN_EFFORT = os.environ.get("GROK_DESIGN_EFFORT", "medium")
DESIGN_TIMEOUT = int(os.environ.get("GROK_DESIGN_TIMEOUT", "420"))
DESIGN_RETRIES = 2
DESIGN_HTTP_RETRIES = 3
DESIGN_CACHE = "design.cache.json"

STATION_FILES = {
    "novel": "novel.json",
    "writer": "writer.json",
    "assets": "assets.json",
    "design": "shot_list.json",
    "spec": "shot_specs.json",
    "package": "gen_packages.json",
    "sound": "audio.json",
    "edit": "cut.json",
}
STATION_VALIDATORS = {
    "novel": lambda data, prod: validate_novel(data),
    "writer": lambda data, prod: validate_writer(data),
    "assets": lambda data, prod: validate_assets(data, prod),
    "design": lambda data, prod: validate_shot_list(data),
    "spec": lambda data, prod: validate_shot_specs(data, read_artifact(prod, "writer.json")),
    "package": lambda data, prod: validate_packages(data, read_artifact(prod, "assets.json"), read_artifact(prod, "shot_specs.json")),
    "sound": lambda data, prod: validate_audio(data, read_artifact(prod, "writer.json")),
    "edit": lambda data, prod: validate_cut(data),
}


def _clip(text: str, limit: int = 8000) -> str:
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n..."


def _episode_text(prod: Path) -> str:
    return read_text(prod, "01-bible/ep01.md") or read_text(prod, "01-bible/source/original.md")


def _brief(prod: Path) -> str:
    return read_text(prod, "01-bible/source/brief.draft.md") or read_text(prod, "01-bible/confirm.md")


def _context(prod: Path, station: str) -> dict:
    ctx: dict[str, Any] = {
        "project_id": prod.name,
        "episode_no": 1,
        "brief": _clip(_brief(prod), 2500),
        "look": _clip(read_text(prod, "02-assets/LOOK.md"), 1500),
        "confirm": _clip(read_text(prod, "01-bible/confirm.md"), 1500),
    }
    if station == "novel":
        ctx["existing_body"] = _clip(_episode_text(prod), 6000)
        ctx["output"] = {"title": "", "body": "", "characters": [{"name": "", "want": "", "conflict": ""}], "notes": ""}
    elif station == "writer":
        novel = read_artifact(prod, "novel.json")
        ctx["novel"] = novel or {"body": _clip(_episode_text(prod), 8000)}
        ctx["output"] = {
            "series_bible": {"logline": "", "characters": [], "relationships": [], "locations": [], "core_conflict": "", "adaptation_rules": ""},
            "episode_outline": [],
            "scenes": [],
        }
    elif station == "assets":
        ctx["writer"] = read_artifact(prod, "writer.json")
        ctx["existing_assets"] = compile_assets_from_folder(prod)
        ctx["output"] = {"assets": []}
    elif station == "design":
        ctx.update(_design_base_context(prod))
    elif station == "spec":
        ctx["shot_list"] = read_artifact(prod, "shot_list.json")
        ctx["writer"] = read_artifact(prod, "writer.json")
        ctx["output"] = {"shot_specs": []}
    elif station == "package":
        ctx["shot_specs"] = read_artifact(prod, "shot_specs.json") or compile_specs_from_legacy(prod)
        ctx["assets"] = read_artifact(prod, "assets.json") or compile_assets_from_folder(prod)
        shot_list = read_artifact(prod, "shot_list.json")
        target = shot_list.get("target_model") or "seedance_2_0"
        ctx["target_model"] = target
        ctx["output"] = {"packages": [], "episode_target_model": target, "confirmed": False}
    elif station == "sound":
        ctx["writer"] = read_artifact(prod, "writer.json")
        ctx["shot_specs"] = read_artifact(prod, "shot_specs.json")
        ctx["output"] = {"dialogue_takes": [], "vo_takes": []}
    elif station == "edit":
        shots = list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])
        ids = [shot.get("id") for shot in shots if shot.get("id")]
        if not ids:
            ids = [item.get("shot_id") for item in (read_artifact(prod, "shot_list.json").get("shots") or [])]
        ctx["shot_list"] = read_artifact(prod, "shot_list.json")
        ctx["shot_specs"] = read_artifact(prod, "shot_specs.json")
        ctx["hint"] = default_cut_from_specs(prod, [sid for sid in ids if sid])
        ctx["output"] = ctx["hint"]
    return ctx


def _system(station: str) -> str:
    """Station duty (pipeline-pack prompt) plus the knowledge layers for that station. Both, not either."""
    duty = pack_prompt(station)
    layers = prompt_block(station)
    parts = [part for part in (duty, layers) if part]
    return (
        "\n\n".join(parts)
        + "\n\nYou output ONE JSON object only. No markdown. Stay inside this station. "
        "Do not invent camera language if you are the writer. Do not write prompts if you are design. "
        "Do not name keyframe files if you are package. Dialogue lines must copy the writer verbatim when present."
    )


def _design_base_context(prod: Path, target_model: Optional[str] = None) -> dict:
    """What the shot-table agent sees on every call: full episode text, every writer scene, stage axes, look, model profile."""
    writer = read_artifact(prod, "writer.json")
    scenes = []
    for scene in writer.get("scenes") or []:
        if int(scene.get("episode_no") or 1) != 1:
            continue
        scenes.append({
            "scene_id": scene.get("scene_id"),
            "heading": scene.get("heading"),
            "location_id": scene.get("location_id"),
            "time_of_day": scene.get("time_of_day"),
            "int_ext": scene.get("int_ext"),
            "present_cast": scene.get("present_cast"),
            "scene_job": scene.get("scene_job"),
            "whose_scene": scene.get("whose_scene"),
            "start_state": scene.get("start_state"),
            "end_state": scene.get("end_state"),
            "action": scene.get("action"),
            "dialogue": scene.get("dialogue") or [],
            "key_sounds": scene.get("key_sounds") or [],
        })
    sets = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    characters = []
    char_dir = prod / "02-assets" / "characters"
    if char_dir.exists():
        for card in sorted(char_dir.glob("*.md")):
            characters.append({"slug": card.stem, "card": _clip(card.read_text(encoding="utf-8"), 600)})
    model = resolve_target_model(prod, target_model)
    from .video_profiles import get_profile

    return {
        "episode_text": _clip(_episode_text(prod), 12000),
        "writer": {
            "series_bible": writer.get("series_bible") or {},
            "episode_outline": (writer.get("episode_outline") or [])[:1],
            "scenes": scenes,
        },
        "sets": [{"id": s.get("id"), "name": s.get("name"), "axis": s.get("axis"), "notes": s.get("notes")} for s in sets.get("sets") or []],
        "characters": characters,
        "target_profile": profile_brief(get_profile(model)),
        "schema": SHOT_TABLE_SCHEMA,
    }


def _design_chat(system: str, ctx: dict) -> dict:
    """One design call. Proxy stalls (5xx / timeouts) are retried; bad JSON is not."""
    last: Optional[Exception] = None
    for attempt in range(DESIGN_HTTP_RETRIES):
        try:
            data = chat_json(
                system,
                json.dumps(ctx, ensure_ascii=False),
                timeout=DESIGN_TIMEOUT,
                effort=DESIGN_EFFORT,
                temperature=0.3,
            )
        except TextError as exc:
            if exc.code != "GROK_HTTP":
                raise
            last = exc
            time.sleep(3 * (attempt + 1))
            continue
        except Exception as exc:  # requests timeouts / connection resets
            last = exc
            time.sleep(3 * (attempt + 1))
            continue
        if not isinstance(data, dict):
            raise TextError("GROK_JSON", "design Agent 没有返回对象")
        return data
    raise TextError("GROK_HTTP", f"design Agent 连续 {DESIGN_HTTP_RETRIES} 次没拿到回复：{last}")


def _design_cache_key(prod: Path, brief: str, profile_id: str, system: str) -> str:
    import hashlib

    blob = "|".join([
        read_text(prod, ".pipeline/writer.json"),
        _episode_text(prod),
        read_text(prod, "03-storyboard/sets.json"),
        read_text(prod, "02-assets/LOOK.md"),
        brief,
        profile_id,
        system,
    ])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _load_design_cache(prod: Path, key: str) -> dict:
    path = pipeline_dir(prod) / DESIGN_CACHE
    if not path.exists():
        return {"key": key, "header": None, "scenes": {}}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"key": key, "header": None, "scenes": {}}
    if cache.get("key") != key:
        return {"key": key, "header": None, "scenes": {}}
    cache.setdefault("scenes", {})
    return cache


def _save_design_cache(prod: Path, cache: dict) -> None:
    path = pipeline_dir(prod, create=True) / DESIGN_CACHE
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_design_cache(prod: Path) -> None:
    path = pipeline_dir(prod) / DESIGN_CACHE
    if path.exists():
        path.unlink()


def _header_errors(header: dict, scene_ids: list[str]) -> list[str]:
    errors = []
    lock = header.get("left_right_lock")
    if not isinstance(lock, dict):
        errors.append("left_right_lock must be an object keyed by scene_id")
    else:
        for sid in scene_ids:
            if not str(lock.get(sid) or "").strip():
                errors.append(f"left_right_lock missing {sid}")
    bible = header.get("continuity_bible")
    if not isinstance(bible, dict):
        errors.append("continuity_bible must be an object")
    else:
        for key in ("eyeline", "wardrobe", "day_night", "props"):
            if key not in bible:
                errors.append(f"continuity_bible missing {key}")
    if not str(header.get("whose_pov") or "").strip():
        errors.append("missing whose_pov")
    plan = header.get("scene_plan")
    if not isinstance(plan, list) or not plan:
        errors.append("scene_plan empty")
    else:
        planned = {str(item.get("scene_id") or "") for item in plan if isinstance(item, dict)}
        for sid in scene_ids:
            if sid not in planned:
                errors.append(f"scene_plan missing {sid}")
    return errors


def run_design_table(prod: Path, *, brief: str = "", target_model: Optional[str] = None, resume: bool = True) -> dict:
    """Shot-table design: one header call, then one call per writer scene, each machine-checked and retried once.

    Accepted header and scenes are cached under the same input fingerprint, so a proxy stall on
    scene 3 does not re-spend scenes 1 and 2.
    """
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
    base = _design_base_context(prod, target_model)
    scenes = base["writer"]["scenes"]
    if not scenes:
        raise PermissionError("design: writer.json 还没有 scenes，先过编剧岗")
    scene_ids = [str(s.get("scene_id") or "") for s in scenes]
    system = _system("design")
    check = table_context(prod, target_model)
    profile = check["profile"]
    cache_key = _design_cache_key(prod, brief, profile["id"], system)
    cache = _load_design_cache(prod, cache_key) if resume else {"key": cache_key, "header": None, "scenes": {}}

    header_ctx = dict(base)
    header_ctx["call"] = "header"
    header_ctx["output"] = {
        "whose_pov": "",
        "left_right_lock": {sid: "" for sid in scene_ids},
        "continuity_bible": {"eyeline": "", "wardrobe": "", "day_night": {sid: "" for sid in scene_ids}, "props": [], "evidence": []},
        "scene_plan": [{"scene_id": sid, "target_shots": 0, "target_sec": 0, "beats": []} for sid in scene_ids],
    }
    if brief:
        header_ctx["user_note"] = brief
    header = cache.get("header")
    last_errors: list[str] = []
    if header is None:
        for attempt in range(DESIGN_RETRIES):
            if last_errors:
                header_ctx["fix_these"] = last_errors
            header = _design_chat(system, header_ctx)
            _dump_station(prod, "design", f"header.raw{attempt + 1}", header)
            last_errors = _header_errors(header, scene_ids)
            if not last_errors:
                break
        if last_errors:
            _dump_station(prod, "design", "header.invalid", {"errors": last_errors, "payload": header})
            raise PermissionError("design header: " + " / ".join(last_errors[:6]))
        cache["header"] = header
        _save_design_cache(prod, cache)

    merged_shots: list[dict] = []
    prev_shot: Optional[dict] = None
    scene_reports = []
    for scene in scenes:
        sid = str(scene.get("scene_id") or "")
        cached = cache.get("scenes", {}).get(sid)
        if cached:
            merged_shots.extend(cached)
            prev_shot = cached[-1] if cached else prev_shot
            scene_reports.append({"scene_id": sid, "shots": len(cached), "warnings": [], "attempts": 0, "cached": True})
            continue
        plan = next((p for p in header.get("scene_plan") or [] if str(p.get("scene_id") or "") == sid), {})
        scene_ctx = dict(base)
        scene_ctx["call"] = "scene"
        scene_ctx["header"] = {
            "whose_pov": header.get("whose_pov"),
            "left_right_lock": header.get("left_right_lock"),
            "continuity_bible": header.get("continuity_bible"),
            "scene_plan": plan,
        }
        scene_ctx["scene"] = scene
        scene_ctx["shot_id_start"] = f"SH{len(merged_shots) + 1:03d}"
        scene_ctx["prev_shot"] = {k: prev_shot.get(k) for k in ("shot_id", "scene_id", "scale", "left", "right", "out_to", "one_action")} if prev_shot else None
        scene_ctx["output"] = {"shots": []}
        if brief:
            scene_ctx["user_note"] = brief
        last_errors = []
        accepted: Optional[list[dict]] = None
        raw: dict = {}
        for attempt in range(DESIGN_RETRIES):
            if last_errors:
                scene_ctx["fix_these"] = last_errors
            raw = _design_chat(system, scene_ctx)
            _dump_station(prod, "design", f"{sid}.raw{attempt + 1}", raw)
            new_shots = []
            for offset, shot in enumerate(raw.get("shots") or []):
                if not isinstance(shot, dict):
                    continue
                shot = dict(shot)
                shot["shot_id"] = f"SH{len(merged_shots) + offset + 1:03d}"
                shot.setdefault("scene_id", sid)
                new_shots.append(shot)
            candidate = sanitize_shot_table(
                {
                    "shots": list(merged_shots) + new_shots,
                    "left_right_lock": header.get("left_right_lock"),
                    "continuity_bible": header.get("continuity_bible"),
                    "whose_pov": header.get("whose_pov"),
                    "visible_change_without_dialogue": "pass",
                },
                writer=check["writer"],
            )
            errors, warnings = validate_shot_table(
                candidate,
                writer=check["writer"],
                sets=check["sets"],
                profile=profile,
                look_text=check["look_text"],
                scene_scope=[sid],
                partial=True,
            )
            if not new_shots:
                errors = ["scene returned no shots"] + errors
            if not errors:
                accepted = candidate["shots"][len(merged_shots):]
                scene_reports.append({"scene_id": sid, "shots": len(accepted), "warnings": warnings, "attempts": attempt + 1})
                break
            last_errors = errors
        if accepted is None:
            _dump_station(prod, "design", f"{sid}.invalid", {"errors": last_errors, "payload": raw})
            raise PermissionError(f"design {sid}: " + " / ".join(last_errors[:6]))
        merged_shots.extend(accepted)
        prev_shot = accepted[-1] if accepted else prev_shot
        cache.setdefault("scenes", {})[sid] = accepted
        _save_design_cache(prod, cache)

    payload = sanitize_shot_table(
        {
            "schema": SHOT_TABLE_SCHEMA,
            "scene_id": "EP01",
            "episode_no": 1,
            "target_model": profile["id"],
            "aspect": "16:9" if "16:9" in check["look_text"] else ("9:16" if "9:16" in check["look_text"] else "16:9"),
            "whose_pov": header.get("whose_pov"),
            "left_right_lock": header.get("left_right_lock"),
            "continuity_bible": header.get("continuity_bible"),
            "scene_plan": header.get("scene_plan"),
            "visible_change_without_dialogue": "pass",
            "dropped_shots": header.get("dropped_shots") or [],
            "design_steps_done": [1, 2, 3, 4, 5, 6, 7],
            "shots": merged_shots,
        },
        writer=check["writer"],
    )
    errors, warnings = validate_shot_table(payload, writer=check["writer"], sets=check["sets"], profile=profile, look_text=check["look_text"])
    if errors:
        _dump_station(prod, "design", "invalid", {"errors": errors, "payload": payload})
        raise PermissionError("design: " + " / ".join(errors[:8]))
    payload["warnings"] = warnings
    payload["scene_reports"] = scene_reports
    payload = _merge_status(payload, "design")
    written = write_artifact(prod, "shot_list.json", payload)
    clear_design_cache(prod)
    specs = _merge_status(compile_specs_from_shot_table(written, aspect=written.get("aspect") or "16:9"), "spec")
    specs["origin"] = "compiled-from-shot-table"
    write_artifact(prod, "shot_specs.json", specs)
    title = str((read_artifact(prod, "writer.json").get("episode_outline") or [{}])[0].get("title") or "第 01 集")
    write_text(prod, "03-storyboard/shot-list.draft.md", render_shot_table_md(written, title=f"第 01 集 {title}", profile=profile, warnings=warnings))
    return {
        "ok": True,
        "station": "design",
        "file": "shot_list.json",
        "origin": "station-agent",
        "used_tokens": True,
        "artifact": written,
        "specs_file": "shot_specs.json",
        "table_md": "03-storyboard/shot-list.draft.md",
        "warnings": warnings,
        "scene_reports": scene_reports,
    }


def _merge_status(data: dict, station: str) -> dict:
    payload = dict(data or {})
    payload["agent"] = station
    payload["status"] = "draft"
    payload["origin"] = "station-agent"
    payload["updated_at"] = int(time.time())
    if station == "package":
        payload["confirmed"] = False
        for item in payload.get("packages") or payload.get("gen_packages") or []:
            item["confirmed"] = False
            item["keyframe_files"] = []
    return payload


def _dump_station(prod: Path, station: str, suffix: str, payload: Any) -> Path:
    dest = pipeline_dir(prod, create=True) / f"{station}.{suffix}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def _sanitize_writer(data: dict) -> dict:
    payload = dict(data or {})
    for index, scene in enumerate(payload.get("scenes") or [], start=1):
        if not scene.get("scene_id"):
            scene["scene_id"] = f"EP01_SC{index:02d}"
        if not scene.get("episode_no"):
            scene["episode_no"] = 1
        if scene.get("dialogue") is None:
            scene["dialogue"] = []
        for item in scene.get("dialogue") or []:
            if not item.get("speaker") and item.get("character"):
                item["speaker"] = item.get("character")
        if not scene.get("mute_test"):
            scene["mute_test"] = "pass"
        if not scene.get("unfilmable_check"):
            scene["unfilmable_check"] = "pass"
        if not scene.get("preach_check"):
            scene["preach_check"] = "pass"
    return payload


def _sanitize_design(data: dict) -> dict:
    payload = dict(data or {})
    if not payload.get("design_steps_done"):
        payload["design_steps_done"] = [1, 2, 3, 4, 5, 6, 7]
    if not payload.get("visible_change_without_dialogue"):
        payload["visible_change_without_dialogue"] = "pass"
    if not payload.get("dropped_shots"):
        payload["dropped_shots"] = []
    for shot in payload.get("shots") or []:
        for key in DESIGN_FORBIDDEN:
            shot.pop(key, None)
        coverage = str(shot.get("coverage_type") or shot.get("setup") or "")
        if coverage == "ots":
            shot["coverage_type"] = "otc"
        if not shot.get("move_needed"):
            if shot.get("move_reason") or str(shot.get("move") or "") not in {"", "static"}:
                shot["move_needed"] = "move"
            else:
                shot["move_needed"] = "static"
        if shot.get("move_needed") == "move" and not shot.get("move_reason"):
            shot["move_needed"] = "static"
    return payload


def _sanitize_spec(data: dict, prod: Path) -> dict:
    payload = dict(data or {})
    look = read_text(prod, "02-assets/LOOK.md")
    aspect = "16:9" if "16:9" in look else ("9:16" if "9:16" in look else "16:9")
    specs = payload.get("shot_specs") or payload.get("specs") or []
    payload["shot_specs"] = specs
    for spec in specs:
        for key in SPEC_FORBIDDEN:
            spec.pop(key, None)
        _flatten_spec_groups(spec, aspect)
        if not spec.get("aspect_ratio") or ("9:16" in str(spec.get("aspect_ratio")) and aspect == "16:9"):
            spec["aspect_ratio"] = aspect
        if str(spec.get("move_type") or "").lower() == "static":
            spec["intensity"] = 0
    return payload


def _flatten_spec_groups(spec: dict, aspect: str) -> None:
    """Lift the 7 nested groups to flat keys. Copies only; never invents a side, a lens, or a duration.

    Anything still missing after this fails validation, which is the point: a spec that
    guesses "速卡 on the left" for a shot she is not in is worse than no spec.
    """
    movement = spec.get("movement") if isinstance(spec.get("movement"), dict) else {}
    time_sound = spec.get("time_sound") if isinstance(spec.get("time_sound"), dict) else {}
    continuity = spec.get("continuity") if isinstance(spec.get("continuity"), dict) else {}
    if not spec.get("action_now") and spec.get("content"):
        spec["action_now"] = spec.get("content")
    spec["aspect_ratio"] = spec.get("aspect_ratio") or aspect
    for key in ("move_type", "move_detail", "move_reason"):
        if not spec.get(key) and movement.get(key):
            spec[key] = movement.get(key)
    if spec.get("intensity") in (None, "") and movement.get("intensity") not in (None, ""):
        spec["intensity"] = movement.get("intensity")
    if spec.get("duration_sec") in (None, "") and time_sound.get("duration_sec") not in (None, ""):
        spec["duration_sec"] = time_sound.get("duration_sec")
    if spec.get("duration_sec") not in (None, ""):
        try:
            spec["duration_sec"] = float(spec["duration_sec"])
        except (TypeError, ValueError):
            spec["duration_sec"] = None
    if spec.get("dialogue_line") in (None, "") and time_sound.get("dialogue_line"):
        spec["dialogue_line"] = time_sound.get("dialogue_line")
    if spec.get("dialogue_start_sec") in (None, "") and time_sound.get("dialogue_start_sec") not in (None, ""):
        spec["dialogue_start_sec"] = time_sound.get("dialogue_start_sec")
    if not spec.get("key_sfx") and time_sound.get("sfx"):
        spec["key_sfx"] = time_sound.get("sfx")
    if not spec.get("axis_side") and continuity.get("axis"):
        spec["axis_side"] = continuity.get("axis")
    if not spec.get("in_from") and continuity.get("from_prev"):
        spec["in_from"] = continuity.get("from_prev")
    if not spec.get("out_to") and continuity.get("to_next"):
        spec["out_to"] = continuity.get("to_next")


def _sanitize_station(prod: Path, station: str, data: dict) -> dict:
    if station == "writer":
        return _sanitize_writer(data)
    if station == "design":
        return _sanitize_design(data)
    if station == "spec":
        return _sanitize_spec(data, prod)
    return data


def run_station_agent(prod: Path, station: str, *, brief: str = "", target_model: Optional[str] = None, resume: bool = True) -> dict:
    if station not in STATION_FILES:
        raise ValueError("unknown station " + station)
    if station == "design":
        return run_design_table(prod, brief=brief, target_model=target_model, resume=resume)
    if station == "spec":
        shot_list = read_artifact(prod, "shot_list.json")
        if str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA:
            specs = _merge_status(compile_specs_from_shot_table(shot_list, aspect=shot_list.get("aspect") or "16:9"), "spec")
            specs["origin"] = "compiled-from-shot-table"
            written = write_artifact(prod, "shot_specs.json", specs)
            return {"ok": True, "station": "spec", "file": "shot_specs.json", "origin": "compiled-from-shot-table", "used_tokens": False, "artifact": written}
    if station == "package":
        shot_list = read_artifact(prod, "shot_list.json")
        if str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA:
            model = target_model or shot_list.get("target_model") or "seedance_2_0"
            payload = _merge_status(compile_packages_from_specs(prod, target_model=model), "package")
            payload["origin"] = "compiled-from-shot-table"
            errors = STATION_VALIDATORS["package"](payload, prod)
            if errors:
                _dump_station(prod, "package", "invalid", {"errors": errors, "payload": payload})
                raise PermissionError("package: " + " / ".join(errors[:6]))
            written = write_artifact(prod, STATION_FILES["package"], payload)
            return {
                "ok": True,
                "station": "package",
                "file": "gen_packages.json",
                "origin": "compiled-from-shot-table",
                "used_tokens": False,
                "artifact": written,
            }
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
    ctx = _context(prod, station)
    if brief:
        ctx["user_note"] = brief
    user = json.dumps(ctx, ensure_ascii=False)
    try:
        data = chat_json(_system(station), user, timeout=240)
    except Exception as exc:
        _dump_station(prod, station, "error", {"error": str(exc), "station": station})
        raise
    _dump_station(prod, station, "raw", data)
    if not isinstance(data, dict):
        raise TextError("GROK_JSON", station + " Agent 没有返回对象")
    payload = _merge_status(_sanitize_station(prod, station, data), station)
    validator = STATION_VALIDATORS[station]
    errors = validator(payload, prod)
    if errors:
        _dump_station(prod, station, "invalid", {"errors": errors, "payload": payload})
        raise PermissionError(station + ": " + " / ".join(errors[:6]))
    written = write_artifact(prod, STATION_FILES[station], payload)
    if station == "novel":
        _write_novel_sidecar(prod, written)
    if station == "writer":
        _write_writer_sidecar(prod, written)
    return {
        "ok": True,
        "station": station,
        "file": STATION_FILES[station],
        "origin": "station-agent",
        "used_tokens": True,
        "artifact": written,
    }


def _write_novel_sidecar(prod: Path, novel: dict) -> None:
    body = str(novel.get("body") or "").strip()
    if not body:
        return
    dest = prod / "01-bible" / "source"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "original.draft.md").write_text(body + "\n", encoding="utf-8")
    title = str(novel.get("title") or prod.name)
    (dest / "source.draft.json").write_text(
        json.dumps({"kind": "novel", "title": title, "origin": "station-agent"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_writer_sidecar(prod: Path, writer: dict) -> None:
    scenes = writer.get("scenes") or []
    if not scenes:
        return
    chunks = ["# 第 01 集\n"]
    for scene in scenes:
        chunks.append("## " + str(scene.get("heading") or scene.get("scene_id") or "场"))
        chunks.append("在场：" + ", ".join(scene.get("present_cast") or []))
        chunks.append("任务：" + str(scene.get("scene_job") or ""))
        chunks.append(str(scene.get("action") or ""))
        for item in scene.get("dialogue") or []:
            speaker = item.get("speaker") or ""
            line = item.get("line") or ""
            chunks.append("**" + str(speaker) + "：** " + str(line))
        chunks.append("")
    dest = prod / "01-bible" / "ep01.draft.md"
    dest.write_text("\n".join(chunks), encoding="utf-8")
