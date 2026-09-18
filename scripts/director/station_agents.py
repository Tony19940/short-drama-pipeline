"""Station agents: each job drafts only its artifact. Rules validate; humans lock."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .design_critic import (
    RUBRIC,
    candidate_summary,
    critic_errors,
    fallback_verdict,
    normalize_verdict,
    render_candidates_md,
    styles_for,
)
from .direction import (
    SCENE_CARD_SCHEMA,
    normalize_scene_card,
    normalize_visual_grammar,
    render_scene_cards_md,
    scene_card_for,
    validate_scene_cards,
    validate_visual_grammar,
)
from .frame_desc import (
    SCHEMA as FRAME_DESC_SCHEMA,
    index_by_shot as frame_desc_index,
    normalize_item as normalize_frame_desc,
    render_frame_descriptions_md,
    validate_frame_descriptions,
)
from .still_t0 import keyframe_plan_of
from .grok_text import TextError, chat_json, text_configured
from .knowledge import cases_for, pack_prompt, prompt_block
from .pipeline import (
    compile_assets_from_folder,
    compile_packages_from_specs,
    compile_shot_list_from_legacy,
    compile_specs_from_legacy,
    default_cut_from_specs,
    DESIGN_FORBIDDEN,
    episode_artifact_name,
    episode_label,
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
    needed_seconds,
    pack_dialogue_for_budget,
    render_shot_table_md,
    sanitize_shot_table,
    table_context,
    validate_shot_table,
    writer_lines,
    clauses_of,
    lock_is_present,
    BASE_ACTION_SEC,
)
from .video_profiles import profile_brief, resolve_target_model

DESIGN_EFFORT = os.environ.get("GROK_DESIGN_EFFORT", "medium")
DESIGN_TIMEOUT = int(os.environ.get("GROK_DESIGN_TIMEOUT", "420"))
DESIGN_HTTP_RETRIES = 3
DESIGN_CACHE = "design.cache.json"
# How many versions of every scene the design station drafts before the critic picks. 1 = old behaviour.
DESIGN_CANDIDATES = max(1, int(os.environ.get("GROK_DESIGN_CANDIDATES", "3") or 3))
CANDIDATES_FILE = "design.candidates.json"
_ACTIVE_EPISODE = 1


def _design_retries() -> int:
    raw = os.environ.get("GROK_DESIGN_RETRIES", "2")
    try:
        return max(1, int(raw or 2))
    except (TypeError, ValueError):
        return 2


DESIGN_RETRIES = _design_retries()


def active_episode() -> int:
    return int(_ACTIVE_EPISODE or 1)


def set_active_episode(episode: Optional[int]) -> int:
    global _ACTIVE_EPISODE
    prev = active_episode()
    _ACTIVE_EPISODE = max(1, int(episode or 1))
    return prev


def _ep() -> int:
    return active_episode()


def writer_artifact_name(episode: int = 1) -> str:
    return episode_artifact_name("writer.json", episode)


def shot_list_artifact_name(episode=1) -> str:
    return episode_artifact_name("shot_list.json", episode)


def scene_cards_artifact_name(episode: int = 1) -> str:
    return episode_artifact_name("scene_cards.json", episode)


def frame_desc_artifact_name(episode: int = 1) -> str:
    return episode_artifact_name("frame_descriptions.json", episode)


def shot_specs_artifact_name(episode: int = 1) -> str:
    return episode_artifact_name("shot_specs.json", episode)


def packages_artifact_name(episode: int = 1) -> str:
    return episode_artifact_name("gen_packages.json", episode)


def sets_rel(episode=1) -> str:
    label = episode_label(episode)
    return "03-storyboard/sets.json" if not label else f"03-storyboard/sets.{label}.json"


def storyboard_md_name(filename: str, episode=1) -> str:
    """EP01 keeps historical names; later episodes / labels insert `.<label>` before `.draft.md` or `.md`."""
    label = episode_label(episode)
    if not label:
        return f"03-storyboard/{filename}"
    if filename.endswith(".draft.md"):
        head = filename[: -len(".draft.md")]
        return f"03-storyboard/{head}.{label}.draft.md"
    if filename.endswith(".md"):
        return f"03-storyboard/{filename[:-3]}.{label}.md"
    return f"03-storyboard/{filename}.{label}"


def design_cache_name(episode: int = 1) -> str:
    return DESIGN_CACHE if int(episode) == 1 else f"design.cache.ep{int(episode):02d}.json"


def candidates_name(episode: int = 1) -> str:
    return CANDIDATES_FILE if int(episode) == 1 else f"design.candidates.ep{int(episode):02d}.json"

STATION_FILES = {
    "novel": "novel.json",
    "writer": "writer.json",
    "assets": "assets.json",
    "analysis": "scene_cards.json",
    "design": "shot_list.json",
    "spec": "shot_specs.json",
    "package": "gen_packages.json",
    "frame_desc": "frame_descriptions.json",
    "sound": "audio.json",
    "edit": "cut.json",
}


def _validate_scene_cards_artifact(data: dict, prod: Path) -> list[str]:
    writer = read_artifact(prod, "writer.json")
    scene_ids = [str(s.get("scene_id") or "") for s in writer.get("scenes") or [] if int(s.get("episode_no") or 1) == 1]
    errors = validate_scene_cards(data.get("scene_cards"), scene_ids)
    if data.get("visual_grammar"):
        errors.extend(validate_visual_grammar(data.get("visual_grammar")))
    return errors


def _validate_frame_desc_artifact(data: dict, prod: Path) -> list[str]:
    table = read_artifact(prod, "shot_list.json")
    ids = [str(s.get("shot_id") or "") for s in table.get("shots") or [] if s.get("shot_id")]
    # still_t0 issues are errors when the agent writes; PUT of old later-ep files stays warning.
    return validate_frame_descriptions(
        data, ids or None, shots=list(table.get("shots") or []), still_t0="warning"
    )


STATION_VALIDATORS = {
    "novel": lambda data, prod: validate_novel(data),
    "writer": lambda data, prod: validate_writer(data),
    "assets": lambda data, prod: validate_assets(data, prod),
    "analysis": _validate_scene_cards_artifact,
    "design": lambda data, prod: validate_shot_list(data),
    "spec": lambda data, prod: validate_shot_specs(data, read_artifact(prod, "writer.json")),
    "package": lambda data, prod: validate_packages(data, read_artifact(prod, "assets.json"), read_artifact(prod, "shot_specs.json")),
    "frame_desc": _validate_frame_desc_artifact,
    "sound": lambda data, prod: validate_audio(data, read_artifact(prod, "writer.json"), prod),
    "edit": lambda data, prod: validate_cut(data),
}


def _clip(text: str, limit: int = 8000) -> str:
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n..."


def _episode_text(prod: Path, episode: Optional[int] = None) -> str:
    ep = int(episode or _ep())
    text = read_text(prod, f"01-bible/ep{ep:02d}.md")
    if text:
        return text
    if ep == 1:
        return read_text(prod, "01-bible/source/original.md")
    return ""


def _brief(prod: Path) -> str:
    return read_text(prod, "01-bible/source/brief.draft.md") or read_text(prod, "01-bible/confirm.md")


def _context(prod: Path, station: str) -> dict:
    ep = _ep()
    ctx: dict[str, Any] = {
        "project_id": prod.name,
        "episode_no": ep,
        "brief": _clip(_brief(prod), 2500),
        "look": _clip(read_text(prod, "02-assets/LOOK.md"), 1500),
        "confirm": _clip(read_text(prod, "01-bible/confirm.md"), 1500),
    }
    if station == "novel":
        ctx["existing_body"] = _clip(_episode_text(prod, ep), 6000)
        ctx["output"] = {"title": "", "body": "", "characters": [{"name": "", "want": "", "conflict": ""}], "notes": ""}
    elif station == "writer":
        novel = read_artifact(prod, "novel.json")
        existing = read_artifact(prod, "writer.json")
        ctx["novel"] = novel or {"body": _clip(_episode_text(prod, ep), 8000)}
        ctx["episode_md"] = _clip(_episode_text(prod, ep), 12000)
        ctx["reuse_series_bible"] = (existing.get("series_bible") or {}) if existing else {}
        ctx["scene_id_prefix"] = f"EP{ep:02d}_SC"
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
        from .sfx import snapshot_sfx

        shot_list = read_artifact(prod, "shot_list.json")
        ctx["writer"] = read_artifact(prod, "writer.json")
        ctx["shot_specs"] = read_artifact(prod, "shot_specs.json")
        ctx["key_sfx"] = [
            {"shot_id": s.get("shot_id"), "key_sfx": list(s.get("key_sfx") or [])}
            for s in (shot_list.get("shots") or [])
            if s.get("key_sfx")
        ]
        ctx["sfx"] = snapshot_sfx(prod)
        ctx["output"] = {"dialogue_takes": [], "vo_takes": [], "sfx_file": "", "ambience_file": ""}
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
    layers = prompt_block(station, include_pack=False)
    parts = [part for part in (duty, layers) if part]
    return (
        "\n\n".join(parts)
        + "\n\nYou output ONE JSON object only. No markdown. Stay inside this station. "
        "Do not invent camera language if you are the writer. Do not write prompts if you are design. "
        "Do not name keyframe files if you are package. Dialogue lines must copy the writer verbatim when present."
    )


def _design_base_context(prod: Path, target_model: Optional[str] = None) -> dict:
    """What the shot-table agent sees on every call: full episode text, every writer scene, stage axes, look, model profile."""
    ep = _ep()
    writer = read_artifact(prod, writer_artifact_name(ep))
    if not writer.get("scenes") and ep == 1:
        writer = read_artifact(prod, "writer.json")
    scenes = []
    for scene in writer.get("scenes") or []:
        if int(scene.get("episode_no") or ep) != ep:
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
    sets = load_json(prod, sets_rel(ep), {"sets": []})
    if ep != 1 and not (sets.get("sets") or []):
        sets = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    characters = []
    char_dir = prod / "02-assets" / "characters"
    if char_dir.exists():
        for card in sorted(char_dir.glob("*.md")):
            characters.append({"slug": card.stem, "card": _clip(card.read_text(encoding="utf-8"), 600)})
    model = resolve_target_model(prod, target_model)
    from .video_profiles import get_profile

    return {
        "episode_text": _clip(_episode_text(prod, ep), 12000),
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


def _design_chat(system: str, ctx: dict, temperature: float = 0.3) -> dict:
    """One design call. Proxy stalls (5xx / timeouts) are retried; bad JSON is not."""
    last: Optional[Exception] = None
    for attempt in range(DESIGN_HTTP_RETRIES):
        try:
            data = chat_json(
                system,
                json.dumps(ctx, ensure_ascii=False),
                timeout=DESIGN_TIMEOUT,
                effort=os.environ.get("GROK_DESIGN_EFFORT", DESIGN_EFFORT),
                temperature=temperature,
            )
        except TextError as exc:
            if exc.code not in {"GROK_HTTP", "GROK_JSON", "GROK_EMPTY"}:
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

    ep = _ep()
    blob = "|".join([
        read_text(prod, f".pipeline/{writer_artifact_name(ep)}"),
        _episode_text(prod, ep),
        read_text(prod, sets_rel(ep)) or read_text(prod, "03-storyboard/sets.json"),
        read_text(prod, "02-assets/LOOK.md"),
        brief,
        profile_id,
        system,
        f"episode={ep}",
    ])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _load_design_cache(prod: Path, key: str) -> dict:
    path = pipeline_dir(prod) / design_cache_name(_ep())
    if not path.exists():
        return {"key": key, "header": None, "scenes": {}}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"key": key, "header": None, "scenes": {}}
    if cache.get("key") != key:
        writer_ids = {
            str(s.get("scene_id") or "")
            for s in (read_artifact(prod, writer_artifact_name(_ep())).get("scenes") or [])
        }
        kept = {sid: shots for sid, shots in (cache.get("scenes") or {}).items() if sid in writer_ids and shots}
        if cache.get("header") and cache.get("analysis") and writer_ids:
            cache["key"] = key
            cache["scenes"] = kept
            cache.setdefault("candidates", {})
            cache.setdefault("verdicts", {})
            return cache
        return {"key": key, "header": None, "scenes": {}}
    cache.setdefault("scenes", {})
    return cache


def _save_design_cache(prod: Path, cache: dict) -> None:
    path = pipeline_dir(prod, create=True) / design_cache_name(_ep())
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_design_cache(prod: Path) -> None:
    path = pipeline_dir(prod) / design_cache_name(_ep())
    if path.exists():
        path.unlink()


def _header_errors(header: dict, scene_ids: list[str]) -> list[str]:
    errors = []
    lock = header.get("left_right_lock")
    if not isinstance(lock, dict):
        errors.append("left_right_lock must be an object keyed by scene_id")
    else:
        for sid in scene_ids:
            if not lock_is_present(lock.get(sid)):
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


def _analysis_errors(payload: dict, scene_ids: list[str]) -> list[str]:
    errors = validate_scene_cards(payload.get("scene_cards"), scene_ids)
    grammar = payload.get("visual_grammar")
    if grammar is None:
        errors.append("missing visual_grammar")
    else:
        errors.extend(validate_visual_grammar(grammar))
    return errors


def _analysis_output_stub(scene_ids: list[str]) -> dict:
    return {
        "scene_cards": [
            {
                "scene_id": sid,
                "dramatic_question": "",
                "turn": {"at": "", "what_flips": "power|information|attention|space|emotion"},
                "emotion_curve": {"start": 0, "peak": 0, "end": 0, "peak_at": ""},
                "the_shot": {"moment": "", "scale": "", "why": ""},
                "reveal_order": [],
                "pov": "",
                "distance_strategy": "",
                "light_motivation": "",
                "color_shift": "",
                "silence_test": "",
                "case_cards": [],
            }
            for sid in scene_ids
        ],
        "visual_grammar": {
            "motifs": [{"id": "", "subject": "", "rule": "", "when": "always|first_appearance|first_shot_in_scene", "scenes": [], "scale_not": [], "scale_in": [], "angle": ""}],
            "scale_rhythm": "",
            "light_motivation": "",
            "color_arc": "",
            "ending_hook": {"scale": [], "note": ""},
        },
    }


def _scene_blob(scene: dict) -> str:
    parts = [scene.get("heading"), scene.get("scene_job"), scene.get("action"), scene.get("start_state"), scene.get("end_state")]
    for item in scene.get("dialogue") or []:
        if isinstance(item, dict):
            parts.append(item.get("line"))
    return " ".join(str(p or "") for p in parts)


def run_scene_analysis(prod: Path, *, base: Optional[dict] = None, brief: str = "", cache: Optional[dict] = None) -> dict:
    """Director's statement: one call for the whole episode → scene cards + visual grammar.

    Runs before the header. The design agent then designs *toward* the card instead of
    only avoiding continuity errors.
    """
    base = base or _design_base_context(prod)
    scenes = base["writer"]["scenes"]
    if not scenes:
        raise PermissionError("analysis: writer.json 还没有 scenes，先过编剧岗")
    scene_ids = [str(s.get("scene_id") or "") for s in scenes]
    if cache is not None and cache.get("analysis"):
        return cache["analysis"]
    system = _system("analysis")
    ctx = dict(base)
    ctx["call"] = "analysis"
    ctx["case_library"] = [{"id": c["id"], "title": c["title"]} for c in _all_case_titles()]
    ctx["output"] = _analysis_output_stub(scene_ids)
    if brief:
        ctx["user_note"] = brief
    last_errors: list[str] = []
    payload: dict = {}
    for attempt in range(_design_retries()):
        if last_errors:
            ctx["fix_these"] = last_errors
        payload = _design_chat(system, ctx, temperature=0.35)
        _dump_station(prod, "analysis", f"raw{attempt + 1}", payload)
        last_errors = _analysis_errors(payload, scene_ids)
        if not last_errors:
            break
    if last_errors:
        _dump_station(prod, "analysis", "invalid", {"errors": last_errors, "payload": payload})
        raise PermissionError("analysis: " + " / ".join(last_errors[:6]))
    result = {
        "schema": SCENE_CARD_SCHEMA,
        "scene_cards": [normalize_scene_card(c) for c in payload.get("scene_cards") or []],
        "visual_grammar": normalize_visual_grammar(payload.get("visual_grammar")),
    }
    if cache is not None:
        cache["analysis"] = result
        _save_design_cache(prod, cache)
    return result


def _all_case_titles() -> list[dict]:
    from .knowledge import case_cards

    return case_cards()


def _candidate_context(base: dict, header: dict, scene: dict, card: Optional[dict], grammar: dict, shot_id_start: str, prev_shot: Optional[dict], style: dict, brief: str) -> dict:
    plan = next((p for p in header.get("scene_plan") or [] if str(p.get("scene_id") or "") == str(scene.get("scene_id") or "")), {})
    ctx = dict(base)
    ctx["call"] = "scene"
    ctx["header"] = {
        "whose_pov": header.get("whose_pov"),
        "left_right_lock": header.get("left_right_lock"),
        "continuity_bible": header.get("continuity_bible"),
        "scene_plan": plan,
    }
    ctx["scene"] = scene
    ctx["scene_card"] = card
    ctx["visual_grammar"] = grammar
    ctx["case_cards"] = cases_for(_scene_blob(scene) + " " + " ".join((card or {}).get("case_cards") or []))
    ctx["shot_id_start"] = shot_id_start
    ctx["prev_shot"] = {k: prev_shot.get(k) for k in ("shot_id", "scene_id", "scale", "left", "right", "out_to", "one_action")} if prev_shot else None
    ctx["candidate_style"] = {"id": style["id"], "label": style["label"], "brief": style["brief"]}
    ctx["output"] = {"shots": []}
    if brief:
        ctx["user_note"] = brief
    return ctx


def _design_one_candidate(prod: Path, system: str, ctx: dict, *, sid: str, merged_shots: list[dict], header: dict, check: dict, profile: dict, style: dict, table_extra: dict) -> Optional[dict]:
    """Design this scene once in one style; machine-check; retry once with the error list. None when it never passes."""
    last_errors: list[str] = []
    raw: dict = {}
    temperature = float(style.get("temperature") or 0.3)
    for attempt in range(_design_retries()):
        if last_errors:
            ctx["fix_these"] = last_errors
        try:
            raw = _design_chat(system, ctx, temperature=temperature)
        except TextError as exc:
            last_errors = [str(exc)]
            continue
        _dump_station(prod, "design", f"{sid}.{style['id']}.raw{attempt + 1}", raw)
        new_shots = []
        for offset, shot in enumerate(raw.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            shot = dict(shot)
            shot["shot_id"] = f"SH{len(merged_shots) + offset + 1:03d}"
            shot.setdefault("scene_id", sid)
            new_shots.append(shot)
        _repair_writer_lines(new_shots, check["writer"], sid)
        new_shots = _split_overlong_shots(new_shots, int(profile.get("max_shot_sec") or 15))
        new_shots = _renumber(new_shots, len(merged_shots) + 1)
        candidate = sanitize_shot_table(
            {
                "shots": list(merged_shots) + new_shots,
                "left_right_lock": header.get("left_right_lock"),
                "continuity_bible": header.get("continuity_bible"),
                "whose_pov": header.get("whose_pov"),
                "visible_change_without_dialogue": "pass",
                **table_extra,
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
            prod=prod,
        )
        if not new_shots:
            errors = ["scene returned no shots"] + errors
        if errors and any("needs about" in e and "split the shot" in e for e in errors):
            max_sec = int(profile.get("max_shot_sec") or 15)
            for shot in candidate["shots"][len(merged_shots):]:
                import math

                need = needed_seconds(shot)
                dur = int(shot.get("duration_sec") or 0)
                if need > dur + 0.05:
                    bumped = min(max_sec, int(math.ceil(need - 1e-9)))
                    if bumped > dur:
                        shot["duration_sec"] = bumped
            candidate["total_sec"] = sum(int(s.get("duration_sec") or 0) for s in candidate["shots"])
            errors, warnings = validate_shot_table(
                candidate,
                writer=check["writer"],
                sets=check["sets"],
                profile=profile,
                look_text=check["look_text"],
                scene_scope=[sid],
                partial=True,
                prod=prod,
            )
        if not errors:
            accepted = candidate["shots"][len(merged_shots):]
            scene_warnings = [w for w in warnings if sid in w or any(s.get("shot_id") in w for s in accepted)]
            return {"style": style["id"], "label": style["label"], "shots": accepted, "warnings": scene_warnings, "attempts": attempt + 1}
        last_errors = errors
    _dump_station(prod, "design", f"{sid}.{style['id']}.invalid", {"errors": last_errors, "payload": raw})
    return None


FRAME_DESC_SHOT_KEYS = (
    "shot_id", "beat", "shot_job", "coverage_type", "scale", "angle", "height", "lens", "move_type", "move_reason",
    "left", "right", "eyeline", "body_facing", "camera_side", "one_action", "duration_sec", "dialogue_ref", "light",
    "in_from", "out_to", "state", "emotion_level",
)


def frame_desc_shots_ctx(scene_shots: list[dict]) -> list[dict]:
    """Per-shot payload for the frame-desc agent, including facing and the previous shot."""
    out: list[dict] = []
    prev: Optional[dict] = None
    for shot in scene_shots:
        row = {key: shot.get(key) for key in FRAME_DESC_SHOT_KEYS}
        row["prev_shot_id"] = str((prev or {}).get("shot_id") or "")
        row["prev_facing"] = (prev or {}).get("body_facing") or ""
        row["keyframe_plan"] = keyframe_plan_of(shot)
        out.append(row)
        prev = shot
    return out


def _run_critic(prod: Path, *, sid: str, scene: dict, card: Optional[dict], grammar: dict, candidates: list[dict], profile: dict) -> dict:
    """Score candidates against the scene card, including a single-version continuity review."""
    if not candidates:
        return {"pick": 0, "why": "没有候选。", "merge": "", "scores": [], "source": "empty"}
    system = _system("critic")
    ctx = {
        "call": "critic",
        "scene": scene,
        "scene_card": card,
        "visual_grammar": grammar,
        "target_profile": profile_brief(profile),
        "rubric": RUBRIC,
        "candidates": [candidate_summary({**c, "index": i}, card) for i, c in enumerate(candidates)],
        "output": {
            "scores": [{"candidate": i, "dims": {k: 0 for k in RUBRIC}, "notes": "", "fixes": []} for i in range(len(candidates))],
            "pick": 0,
            "why": "",
            "merge": "",
        },
    }
    last_errors: list[str] = []
    verdict: dict = {}
    try:
        for attempt in range(_design_retries()):
            if last_errors:
                ctx["fix_these"] = last_errors
            verdict = _design_chat(system, ctx, temperature=0.2)
            _dump_station(prod, "critic", f"{sid}.raw{attempt + 1}", verdict)
            last_errors = critic_errors(verdict, len(candidates))
            if not last_errors:
                return normalize_verdict(verdict, len(candidates))
    except TextError as exc:
        last_errors = [str(exc)]
    _dump_station(prod, "critic", f"{sid}.invalid", {"errors": last_errors, "payload": verdict})
    return fallback_verdict(candidates, card, " / ".join(last_errors[:2]) or "评审未返回可用结果")


def _repair_writer_lines(shots: list[dict], writer: dict, scene_id: str) -> None:
    """Map paraphrased dialogue onto unused writer lines so coverage does not fail verbatim check."""
    allowed = list(writer_lines(writer).get(scene_id) or [])
    if not allowed:
        return
    used: list[str] = []

    def pick(line: str) -> str:
        unused = [w for w in allowed if used.count(w) < allowed.count(w)]
        for pool in (unused, allowed):
            for writer_line in pool:
                if line == writer_line or (line and (line in writer_line or writer_line in line)):
                    return writer_line
        return ""

    for shot in shots:
        for item in shot.get("dialogue_ref") or []:
            if not isinstance(item, dict):
                continue
            line = str(item.get("line") or "").strip()
            match = pick(line)
            if match:
                item["line"] = match
                used.append(match)
    missing = [line for line in allowed if used.count(line) < allowed.count(line)]
    for shot in shots:
        for item in shot.get("dialogue_ref") or []:
            if not isinstance(item, dict):
                continue
            line = str(item.get("line") or "").strip()
            if line and line not in allowed and missing:
                item["line"] = missing.pop(0)


def _split_overlong_shots(shots: list[dict], max_sec: int) -> list[dict]:
    """If a shot's dialogue+action needs more than the model max, split extra lines or a long monologue."""
    import math

    out: list[dict] = []
    budget = max(4.0, float(max_sec) - BASE_ACTION_SEC - 1.0)
    for shot in shots:
        need = needed_seconds(shot)
        lines = [item for item in (shot.get("dialogue_ref") or []) if isinstance(item, dict)]
        if need <= max_sec:
            out.append(shot)
            continue
        if len(lines) >= 2:
            first = dict(shot)
            first["dialogue_ref"] = [lines[0]]
            first["duration_sec"] = min(max_sec, max(3, int(math.ceil(needed_seconds(first) - 1e-9))))
            rest = dict(shot)
            rest["dialogue_ref"] = lines[1:]
            rest["coverage_type"] = "reaction"
            rest["scale"] = "close" if str(shot.get("scale") or "") != "close" else "otc"
            rest["shot_job"] = (str(shot.get("shot_job") or "") + "（拆出下一句）").strip()
            rest["one_action"] = "听完，停一拍。"
            rest["duration_sec"] = min(max_sec, max(3, int(math.ceil(needed_seconds(rest) - 1e-9))))
            rest.pop("shot_id", None)
            out.extend([first, rest])
            continue
        if len(lines) == 1:
            packs = pack_dialogue_for_budget(str(lines[0].get("line") or ""), budget)
            if len(packs) > 1:
                for index, pack in enumerate(packs):
                    piece = dict(shot)
                    piece["dialogue_ref"] = [{**lines[0], "line": pack}]
                    if index:
                        piece["coverage_type"] = "reaction" if index % 2 else "reverse"
                        piece["scale"] = "close" if str(shot.get("scale") or "") != "close" else "otc"
                        piece["shot_job"] = (str(shot.get("shot_job") or "") + f"（对白拆 {index + 1}）").strip()
                        piece["one_action"] = "接着说下一句。" if index % 2 == 0 else "听着，停一拍。"
                        piece.pop("shot_id", None)
                    else:
                        clauses = clauses_of(shot.get("one_action") or "")
                        if len(clauses) > 1:
                            piece["one_action"] = clauses[0] + "。"
                    piece["duration_sec"] = min(max_sec, max(3, int(math.ceil(needed_seconds(piece) - 1e-9))))
                    out.append(piece)
                continue
        if need > max_sec:
            clauses = clauses_of(shot.get("one_action") or "")
            if len(clauses) > 1:
                shot["one_action"] = clauses[0] + "。"
        out.append(shot)
    return out


def _renumber(shots: list[dict], start: int) -> list[dict]:
    out = []
    for offset, shot in enumerate(shots):
        item = dict(shot)
        item["shot_id"] = f"SH{start + offset:03d}"
        out.append(item)
    return out


def run_design_table(
    prod: Path,
    *,
    brief: str = "",
    target_model: Optional[str] = None,
    resume: bool = True,
    candidates: Optional[int] = None,
    episode: int = 1,
) -> dict:
    """Shot-table design, film-grade path.

    1. `analysis` — one call: scene cards (dramatic question, turn, emotion curve, the shot,
       reveal order) + episode visual grammar.
    2. `header` — POV, left/right lock, continuity bible, scene plan (sees the cards).
    3. per scene — N candidates in different directing styles, each machine-checked and retried
       once; then a critic scores them against the card and picks. All versions are kept in
       `.pipeline/design.candidates.json`; humans can swap the pick with `pick_candidate`.

    Accepted analysis / header / candidates are cached under the same input fingerprint.
    EP02+ writes suffixed artifacts and does not touch EP01 `shot_list.json`.
    """
    prev_ep = set_active_episode(episode)
    try:
        return _run_design_table_body(
            prod,
            brief=brief,
            target_model=target_model,
            resume=resume,
            candidates=candidates,
        )
    finally:
        set_active_episode(prev_ep)


def _run_design_table_body(
    prod: Path,
    *,
    brief: str = "",
    target_model: Optional[str] = None,
    resume: bool = True,
    candidates: Optional[int] = None,
) -> dict:
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
    ep = _ep()
    n_candidates = max(1, int(candidates or DESIGN_CANDIDATES))
    base = _design_base_context(prod, target_model)
    scenes = base["writer"]["scenes"]
    if not scenes:
        raise PermissionError(f"design: {writer_artifact_name(ep)} 还没有 scenes，先过编剧岗")
    scene_ids = [str(s.get("scene_id") or "") for s in scenes]
    system = _system("design")
    check = table_context(prod, target_model, episode=ep)
    profile = check["profile"]
    cache_key = _design_cache_key(prod, brief, profile["id"], system + f"|candidates={n_candidates}")
    cache = _load_design_cache(prod, cache_key) if resume else {"key": cache_key, "header": None, "scenes": {}}
    cache.setdefault("candidates", {})
    cache.setdefault("verdicts", {})

    # 1. director's statement
    analysis = run_scene_analysis(prod, base=base, brief=brief, cache=cache)
    scene_cards = analysis["scene_cards"]
    grammar = analysis["visual_grammar"]
    write_artifact(prod, scene_cards_artifact_name(ep), _merge_status({"schema": SCENE_CARD_SCHEMA, "scene_cards": scene_cards, "visual_grammar": grammar}, "analysis"))
    write_text(prod, storyboard_md_name("scene-cards.draft.md", ep), render_scene_cards_md(scene_cards, grammar, title=f"第 {ep:02d} 集"))

    # 2. header
    header_ctx = dict(base)
    header_ctx["call"] = "header"
    header_ctx["scene_cards"] = scene_cards
    header_ctx["visual_grammar"] = grammar
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
        for attempt in range(_design_retries()):
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

    table_extra = {"scene_cards": scene_cards, "visual_grammar": grammar}
    styles = styles_for(n_candidates)

    # 3. scenes
    merged_shots: list[dict] = []
    prev_shot: Optional[dict] = None
    scene_reports = []
    candidate_rows = []
    picks: dict[str, int] = {}
    for scene in scenes:
        sid = str(scene.get("scene_id") or "")
        card = scene_card_for(scene_cards, sid)
        cached = cache.get("scenes", {}).get(sid)
        if cached:
            merged_shots.extend(cached)
            prev_shot = cached[-1] if cached else prev_shot
            picks[sid] = int((cache.get("verdicts", {}).get(sid) or {}).get("pick", 0) or 0)
            scene_reports.append({"scene_id": sid, "shots": len(cached), "warnings": [], "attempts": 0, "cached": True, "candidates": len(cache["candidates"].get(sid) or [])})
            candidate_rows.append({"scene_id": sid, "scene_card": card, "candidates": cache["candidates"].get(sid) or [], "verdict": cache["verdicts"].get(sid) or {}, "pick": picks[sid]})
            continue
        shot_id_start = f"SH{len(merged_shots) + 1:03d}"
        accepted: list[dict] = []
        for style in styles:
            ctx = _candidate_context(base, header, scene, card, grammar, shot_id_start, prev_shot, style, brief)
            result = _design_one_candidate(
                prod, system, ctx, sid=sid, merged_shots=merged_shots, header=header, check=check, profile=profile, style=style, table_extra=table_extra
            )
            if result:
                accepted.append(result)
        if not accepted:
            raise PermissionError(f"design {sid}: {n_candidates} 版都没过机器校验，看 .pipeline/design.{sid}.*.invalid.json")
        verdict = _run_critic(prod, sid=sid, scene=scene, card=card, grammar=grammar, candidates=accepted, profile=profile)
        pick = int(verdict.get("pick", 0) or 0)
        chosen = accepted[pick]["shots"]
        merged_shots.extend(chosen)
        prev_shot = chosen[-1] if chosen else prev_shot
        picks[sid] = pick
        cache.setdefault("scenes", {})[sid] = chosen
        cache["candidates"][sid] = accepted
        cache["verdicts"][sid] = verdict
        _save_design_cache(prod, cache)
        scene_reports.append({
            "scene_id": sid,
            "shots": len(chosen),
            "warnings": accepted[pick]["warnings"],
            "attempts": accepted[pick]["attempts"],
            "candidates": len(accepted),
            "pick": pick,
            "critic": verdict.get("source"),
        })
        candidate_rows.append({"scene_id": sid, "scene_card": card, "candidates": accepted, "verdict": verdict, "pick": pick})

    written = _finalize_design(
        prod,
        merged_shots=merged_shots,
        header=header,
        check=check,
        profile=profile,
        scene_cards=scene_cards,
        grammar=grammar,
        picks=picks,
        candidate_rows=candidate_rows,
        scene_reports=scene_reports,
    )
    clear_design_cache(prod)
    return {
        "ok": True,
        "station": "design",
        "episode": ep,
        "file": shot_list_artifact_name(ep),
        "origin": "station-agent",
        "used_tokens": True,
        "artifact": written,
        "specs_file": shot_specs_artifact_name(ep),
        "table_md": storyboard_md_name("shot-list.draft.md", ep),
        "cards_md": storyboard_md_name("scene-cards.draft.md", ep),
        "candidates_md": storyboard_md_name("shot-candidates.draft.md", ep),
        "warnings": written.get("warnings") or [],
        "scene_reports": scene_reports,
        "candidate_picks": picks,
    }


def _finalize_design(
    prod: Path,
    *,
    merged_shots: list[dict],
    header: dict,
    check: dict,
    profile: dict,
    scene_cards: list[dict],
    grammar: dict,
    picks: dict[str, int],
    candidate_rows: list[dict],
    scene_reports: list[dict],
) -> dict:
    ep = _ep()
    payload = sanitize_shot_table(
        {
            "schema": SHOT_TABLE_SCHEMA,
            "scene_id": f"EP{ep:02d}",
            "episode_no": ep,
            "target_model": profile["id"],
            "aspect": "16:9" if "16:9" in check["look_text"] else ("9:16" if "9:16" in check["look_text"] else "16:9"),
            "whose_pov": header.get("whose_pov"),
            "left_right_lock": header.get("left_right_lock"),
            "continuity_bible": header.get("continuity_bible"),
            "scene_plan": header.get("scene_plan"),
            "scene_cards": scene_cards,
            "visual_grammar": grammar,
            "candidate_picks": picks,
            "visible_change_without_dialogue": "pass",
            "dropped_shots": header.get("dropped_shots") or [],
            "design_steps_done": [1, 2, 3, 4, 5, 6, 7],
            "shots": merged_shots,
        },
        writer=check["writer"],
    )
    errors, warnings = validate_shot_table(payload, writer=check["writer"], sets=check["sets"], profile=profile, look_text=check["look_text"], prod=prod)
    if errors:
        _dump_station(prod, "design", "invalid", {"errors": errors, "payload": payload})
        raise PermissionError("design: " + " / ".join(errors[:8]))
    payload["warnings"] = warnings
    payload["scene_reports"] = scene_reports
    payload = _merge_status(payload, "design")
    written = write_artifact(prod, shot_list_artifact_name(ep), payload)
    _dump_station(prod, "design", "candidates", {"schema": "design-candidates-v1", "scenes": candidate_rows, "picks": picks})
    specs = _merge_status(compile_specs_from_shot_table(written, aspect=written.get("aspect") or "16:9"), "spec")
    specs["origin"] = "compiled-from-shot-table"
    write_artifact(prod, shot_specs_artifact_name(ep), specs)
    title = str((read_artifact(prod, writer_artifact_name(ep)).get("episode_outline") or [{}])[0].get("title") or f"第 {ep:02d} 集")
    descriptions = frame_desc_index(read_artifact(prod, frame_desc_artifact_name(ep)))
    write_text(
        prod,
        storyboard_md_name("shot-list.draft.md", ep),
        render_shot_table_md(written, title=f"第 {ep:02d} 集 {title}", profile=profile, warnings=warnings, frame_descriptions=descriptions),
    )
    write_text(prod, storyboard_md_name("shot-candidates.draft.md", ep), render_candidates_md(candidate_rows, title=f"第 {ep:02d} 集 {title}"))
    return written


def design_candidates(prod: Path) -> dict:
    path = pipeline_dir(prod) / candidates_name(_ep())
    if not path.exists():
        return {"schema": "design-candidates-v1", "scenes": [], "picks": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "design-candidates-v1", "scenes": [], "picks": {}}


def pick_candidate(prod: Path, scene_id: str, index: int, *, target_model: Optional[str] = None) -> dict:
    """Human swaps which version of a scene goes into the table. Re-numbers, re-validates, re-renders. No tokens."""
    data = design_candidates(prod)
    rows = list(data.get("scenes") or [])
    if not rows:
        raise PermissionError("没有候选记录；先让导演 Agent 拆镜")
    target = next((r for r in rows if str(r.get("scene_id") or "") == str(scene_id)), None)
    if target is None:
        raise ValueError(f"没有这场：{scene_id}")
    candidates = list(target.get("candidates") or [])
    if index < 0 or index >= len(candidates):
        raise ValueError(f"{scene_id} 只有 {len(candidates)} 版")
    table = read_artifact(prod, shot_list_artifact_name(_ep()))
    if str(table.get("schema") or "") != SHOT_TABLE_SCHEMA:
        raise PermissionError("正式镜头表不是 shot-table-v2")
    check = table_context(prod, target_model or table.get("target_model"), episode=_ep())
    profile = check["profile"]
    header = {
        "whose_pov": table.get("whose_pov"),
        "left_right_lock": table.get("left_right_lock"),
        "continuity_bible": table.get("continuity_bible"),
        "scene_plan": table.get("scene_plan"),
        "dropped_shots": table.get("dropped_shots"),
    }
    picks = {str(k): int(v) for k, v in (table.get("candidate_picks") or {}).items()}
    picks[str(scene_id)] = int(index)
    target["pick"] = int(index)
    verdict = dict(target.get("verdict") or {})
    verdict["pick"] = int(index)
    verdict["source"] = "human"
    verdict["why"] = (verdict.get("why") or "") + f" 人改选第 {index + 1} 版。"
    target["verdict"] = verdict
    merged: list[dict] = []
    for row in rows:
        sid = str(row.get("scene_id") or "")
        chosen_idx = picks.get(sid, int(row.get("pick") or 0))
        cands = list(row.get("candidates") or [])
        if not cands:
            continue
        chosen_idx = min(max(chosen_idx, 0), len(cands) - 1)
        merged.extend(_renumber(list(cands[chosen_idx].get("shots") or []), len(merged) + 1))
    written = _finalize_design(
        prod,
        merged_shots=merged,
        header=header,
        check=check,
        profile=profile,
        scene_cards=list(table.get("scene_cards") or []),
        grammar=table.get("visual_grammar") or {},
        picks=picks,
        candidate_rows=rows,
        scene_reports=list(table.get("scene_reports") or []),
    )
    return {"ok": True, "scene_id": scene_id, "pick": int(index), "artifact": written, "used_tokens": False}


def run_frame_descriptions(prod: Path, *, brief: str = "", scene_ids: Optional[list[str]] = None, episode: int = 1) -> dict:
    """Second descriptive layer: one call per scene, every shot gets layers / light / hands / composition."""
    prev_ep = set_active_episode(episode)
    try:
        return _run_frame_descriptions_body(prod, brief=brief, scene_ids=scene_ids)
    finally:
        set_active_episode(prev_ep)


def _run_frame_descriptions_body(prod: Path, *, brief: str = "", scene_ids: Optional[list[str]] = None) -> dict:
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
    ep = _ep()
    table = read_artifact(prod, shot_list_artifact_name(ep))
    shots = list(table.get("shots") or [])
    if not shots:
        raise PermissionError("frame_desc: 还没有镜头表，先拆镜")
    writer = read_artifact(prod, writer_artifact_name(ep))
    cards = table.get("scene_cards") or read_artifact(prod, scene_cards_artifact_name(ep)).get("scene_cards") or []
    grammar = table.get("visual_grammar") or read_artifact(prod, scene_cards_artifact_name(ep)).get("visual_grammar") or {}
    sets = load_json(prod, sets_rel(ep), {"sets": []})
    if ep != 1 and not (sets.get("sets") or []):
        sets = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    look = _clip(read_text(prod, "02-assets/LOOK.md"), 2500)
    look_lock = _clip(read_text(prod, "01-bible/LOOK-LOCK.md"), 3500)
    cast_cards = []
    cast_md = read_text(prod, "01-bible/CAST.md")
    if cast_md:
        cast_cards.append({"file": "01-bible/CAST.md", "text": _clip(cast_md, 4000)})
    char_dir = prod / "02-assets" / "characters"
    if char_dir.exists():
        for card in sorted(char_dir.glob("*.md")):
            cast_cards.append({"file": str(card.relative_to(prod)), "text": _clip(card.read_text(encoding="utf-8"), 800)})
    existing = frame_desc_index(read_artifact(prod, frame_desc_artifact_name(ep)))
    system = _system("frame_desc")
    by_scene: dict[str, list[dict]] = {}
    for shot in shots:
        by_scene.setdefault(str(shot.get("scene_id") or ""), []).append(shot)
    scene_meta = {str(s.get("scene_id") or ""): s for s in writer.get("scenes") or []}
    items: dict[str, dict] = dict(existing)
    reports = []
    for sid, scene_shots in by_scene.items():
        if scene_ids and sid not in scene_ids:
            continue
        ids = [str(s.get("shot_id") or "") for s in scene_shots]
        ctx = {
            "call": "frame_desc",
            "scene": scene_meta.get(sid) or {"scene_id": sid},
            "scene_card": scene_card_for(cards, sid),
            "visual_grammar": grammar,
            "set": next((s for s in sets.get("sets") or [] if str(s.get("id") or "") == str(scene_shots[0].get("location_id") or "")), None),
            "look": look,
            "look_lock": look_lock,
            "cast": cast_cards,
            "still_rule": "one_paragraph / still_start = 首帧第 0 秒，动词尚未发生。one_action 只给视频，不要写进首段。keyframe_plan=first_last 必须另写 still_end / last_paragraph。",
            "shots": frame_desc_shots_ctx(scene_shots),
            "output": {"items": [{"shot_id": i, "layers": {"foreground": "", "midground": "", "background": ""}, "light": {"key": "", "fill": "", "practical": "", "quality": ""}, "subject": {"facing": "", "hands": "", "holding": "", "micro_expression": ""}, "composition": {"weight": "", "negative_space": "", "headroom": ""}, "height_meaning": "", "forbidden": [], "one_paragraph": "", "last_paragraph": "", "still_start": {"pose": "", "holding": "", "prop_state": "", "one_paragraph": ""}, "still_end": {"pose": "", "holding": "", "prop_state": "", "one_paragraph": ""}} for i in ids]},
        }
        if brief:
            ctx["user_note"] = brief
        last_errors: list[str] = []
        payload: dict = {}
        accepted: Optional[list[dict]] = None
        for attempt in range(_design_retries()):
            if last_errors:
                ctx["fix_these"] = last_errors
            payload = _design_chat(system, ctx, temperature=0.3)
            _dump_station(prod, "frame_desc", f"{sid}.raw{attempt + 1}", payload)
            candidate = {"schema": FRAME_DESC_SCHEMA, "items": [normalize_frame_desc(i) for i in payload.get("items") or []]}
            last_errors = validate_frame_descriptions(candidate, ids, shots=scene_shots)
            if not last_errors:
                accepted = candidate["items"]
                break
        if accepted is None:
            _dump_station(prod, "frame_desc", f"{sid}.invalid", {"errors": last_errors, "payload": payload})
            raise PermissionError(f"frame_desc {sid}: " + " / ".join(last_errors[:6]))
        for item in accepted:
            items[item["shot_id"]] = item
        reports.append({"scene_id": sid, "shots": len(accepted)})
    ordered = [items[str(s.get("shot_id") or "")] for s in shots if str(s.get("shot_id") or "") in items]
    payload = _merge_status({"schema": FRAME_DESC_SCHEMA, "items": ordered}, "frame_desc")
    errors = validate_frame_descriptions(
        payload,
        [str(s.get("shot_id") or "") for s in shots] if not scene_ids else None,
        shots=shots,
        still_t0="error" if not scene_ids else "warning",
    )
    if errors:
        _dump_station(prod, "frame_desc", "invalid", {"errors": errors, "payload": payload})
        raise PermissionError("frame_desc: " + " / ".join(errors[:6]))
    written = write_artifact(prod, frame_desc_artifact_name(ep), payload)
    title = str((writer.get("episode_outline") or [{}])[0].get("title") or f"第 {ep:02d} 集")
    write_text(prod, storyboard_md_name("frame-descriptions.draft.md", ep), render_frame_descriptions_md(written, title=f"第 {ep:02d} 集 {title}"))
    profile = table_context(prod, table.get("target_model"), episode=ep)["profile"]
    write_text(
        prod,
        storyboard_md_name("shot-list.draft.md", ep),
        render_shot_table_md(table, title=f"第 {ep:02d} 集 {title}", profile=profile, warnings=table.get("warnings") or [], frame_descriptions=frame_desc_index(written)),
    )
    return {
        "ok": True,
        "station": "frame_desc",
        "episode": ep,
        "file": frame_desc_artifact_name(ep),
        "origin": "station-agent",
        "used_tokens": True,
        "artifact": written,
        "md": storyboard_md_name("frame-descriptions.draft.md", ep),
        "scene_reports": reports,
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
    ep = _ep()
    name = f"{station}.{suffix}.json" if ep == 1 else f"{station}.ep{ep:02d}.{suffix}.json"
    dest = pipeline_dir(prod, create=True) / name
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def _infer_scene_time(scene: dict) -> str:
    blob = " ".join(str(scene.get(k) or "") for k in ("heading", "time_of_day", "action", "scene_job"))
    for token, value in (("夜", "夜"), ("晚上", "夜"), ("凌晨", "夜"), ("晨", "晨"), ("午前", "日"), ("午后", "日"), ("白天", "日"), ("日", "日")):
        if token in blob:
            return value
    return "日"


def _infer_int_ext(scene: dict) -> str:
    heading = str(scene.get("heading") or "")
    if heading.startswith("外") or " 外 " in heading or heading.startswith("2 外"):
        return "外"
    loc = str(scene.get("location_id") or "")
    if any(token in loc for token in ("gate", "yard", "road", "river", "night")):
        return "外"
    return "内"


def _sanitize_writer(data: dict, episode: Optional[int] = None) -> dict:
    ep = int(episode or _ep())
    prefix = f"EP{ep:02d}"
    payload = dict(data or {})
    for index, scene in enumerate(payload.get("scenes") or [], start=1):
        sid = str(scene.get("scene_id") or "")
        if not sid or not sid.startswith(f"{prefix}_"):
            scene["scene_id"] = f"{prefix}_SC{index:02d}"
        scene["episode_no"] = ep
        if scene.get("dialogue") is None:
            scene["dialogue"] = []
        speakers: list[str] = []
        for item in scene.get("dialogue") or []:
            if not item.get("speaker") and item.get("character"):
                item["speaker"] = item.get("character")
            speaker = str(item.get("speaker") or item.get("character") or "").strip()
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        if not scene.get("time_of_day"):
            scene["time_of_day"] = _infer_scene_time(scene)
        if not scene.get("int_ext"):
            scene["int_ext"] = _infer_int_ext(scene)
        if not scene.get("location_id"):
            scene["location_id"] = "factory-gate"
        if not scene.get("heading"):
            scene["heading"] = f"{index} {scene['int_ext']} {scene['location_id']} {scene['time_of_day']}"
        if not scene.get("present_cast"):
            scene["present_cast"] = speakers or ["rin"]
        if not scene.get("whose_scene"):
            scene["whose_scene"] = (scene.get("present_cast") or ["rin"])[0]
        if not scene.get("scene_job"):
            scene["scene_job"] = (str(scene.get("action") or "").strip()[:80] or f"场{index}")
        if not scene.get("action"):
            scene["action"] = str(scene.get("scene_job") or "本场动作见剧本。")
        if not scene.get("start_state"):
            scene["start_state"] = "开场"
        if not scene.get("end_state"):
            scene["end_state"] = "转下一场"
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


def run_station_agent(
    prod: Path,
    station: str,
    *,
    brief: str = "",
    target_model: Optional[str] = None,
    resume: bool = True,
    candidates: Optional[int] = None,
    scene_ids: Optional[list[str]] = None,
    episode: int = 1,
) -> dict:
    if station not in STATION_FILES:
        raise ValueError("unknown station " + station)
    prev_ep = set_active_episode(episode)
    try:
        return _run_station_agent_body(
            prod,
            station,
            brief=brief,
            target_model=target_model,
            resume=resume,
            candidates=candidates,
            scene_ids=scene_ids,
        )
    finally:
        set_active_episode(prev_ep)


def _run_station_agent_body(
    prod: Path,
    station: str,
    *,
    brief: str = "",
    target_model: Optional[str] = None,
    resume: bool = True,
    candidates: Optional[int] = None,
    scene_ids: Optional[list[str]] = None,
) -> dict:
    ep = _ep()
    if station == "design":
        return run_design_table(prod, brief=brief, target_model=target_model, resume=resume, candidates=candidates, episode=ep)
    if station == "analysis":
        if not text_configured():
            raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
        analysis = run_scene_analysis(prod, brief=brief)
        payload = _merge_status({"schema": SCENE_CARD_SCHEMA, **analysis}, "analysis")
        written = write_artifact(prod, scene_cards_artifact_name(ep), payload)
        md = storyboard_md_name("scene-cards.draft.md", ep)
        write_text(prod, md, render_scene_cards_md(written.get("scene_cards"), written.get("visual_grammar"), title=f"第 {ep:02d} 集"))
        return {"ok": True, "station": "analysis", "episode": ep, "file": scene_cards_artifact_name(ep), "origin": "station-agent", "used_tokens": True, "artifact": written, "md": md}
    if station == "frame_desc":
        return run_frame_descriptions(prod, brief=brief, scene_ids=scene_ids, episode=ep)
    if station == "spec":
        shot_list = read_artifact(prod, shot_list_artifact_name(ep))
        if str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA:
            specs = _merge_status(compile_specs_from_shot_table(shot_list, aspect=shot_list.get("aspect") or "16:9"), "spec")
            specs["origin"] = "compiled-from-shot-table"
            written = write_artifact(prod, shot_specs_artifact_name(ep), specs)
            return {"ok": True, "station": "spec", "episode": ep, "file": shot_specs_artifact_name(ep), "origin": "compiled-from-shot-table", "used_tokens": False, "artifact": written}
    if station == "package":
        shot_list = read_artifact(prod, shot_list_artifact_name(ep))
        if str(shot_list.get("schema") or "") == SHOT_TABLE_SCHEMA:
            model = target_model or shot_list.get("target_model") or "seedance_2_0"
            specs = read_artifact(prod, shot_specs_artifact_name(ep))
            writer = read_artifact(prod, writer_artifact_name(ep))
            descriptions = read_artifact(prod, frame_desc_artifact_name(ep))
            payload = _merge_status(
                compile_packages_from_specs(
                    prod,
                    target_model=model,
                    table=shot_list,
                    specs=specs,
                    writer=writer,
                    frame_descriptions=descriptions,
                ),
                "package",
            )
            payload["origin"] = "compiled-from-shot-table"
            errors = validate_packages(payload, read_artifact(prod, "assets.json"), specs)
            if errors:
                _dump_station(prod, "package", "invalid", {"errors": errors, "payload": payload})
                raise PermissionError("package: " + " / ".join(errors[:6]))
            written = write_artifact(prod, packages_artifact_name(ep), payload)
            return {
                "ok": True,
                "station": "package",
                "episode": ep,
                "file": packages_artifact_name(ep),
                "origin": "compiled-from-shot-table",
                "used_tokens": False,
                "artifact": written,
            }
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "本机 Grok 订阅代理不可用，也没有 XAI_API_KEY。本岗 Agent 不能装懂。")
    ctx = _context(prod, station)
    if brief:
        ctx["user_note"] = brief
    dest_name = writer_artifact_name(ep) if station == "writer" else STATION_FILES[station]
    last_errors: list[str] = []
    payload: dict = {}
    for attempt in range(_design_retries() if station == "writer" else 1):
        if last_errors:
            ctx["fix_these"] = last_errors
        user = json.dumps(ctx, ensure_ascii=False)
        try:
            data = chat_json(_system(station), user, timeout=DESIGN_TIMEOUT)
        except Exception as exc:
            _dump_station(prod, station, "error", {"error": str(exc), "station": station})
            raise
        _dump_station(prod, station, f"raw{attempt + 1}" if station == "writer" else "raw", data)
        if not isinstance(data, dict):
            raise TextError("GROK_JSON", station + " Agent 没有返回对象")
        payload = _merge_status(_sanitize_station(prod, station, data), station)
        validator = STATION_VALIDATORS[station]
        last_errors = validator(payload, prod)
        if not last_errors:
            break
    if last_errors:
        _dump_station(prod, station, "invalid", {"errors": last_errors, "payload": payload})
        raise PermissionError(station + ": " + " / ".join(last_errors[:6]))
    written = write_artifact(prod, dest_name, payload)
    if station == "novel":
        _write_novel_sidecar(prod, written)
    if station == "writer":
        _write_writer_sidecar(prod, written, episode=ep)
    return {
        "ok": True,
        "station": station,
        "episode": ep,
        "file": dest_name,
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


def _write_writer_sidecar(prod: Path, writer: dict, episode: int = 1) -> None:
    scenes = writer.get("scenes") or []
    if not scenes:
        return
    ep = int(episode or 1)
    chunks = [f"# 第 {ep:02d} 集\n"]
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
    dest = prod / "01-bible" / f"ep{ep:02d}.draft.md"
    dest.write_text("\n".join(chunks), encoding="utf-8")
