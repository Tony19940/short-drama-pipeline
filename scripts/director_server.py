#!/usr/bin/env python3
"""Local director console. Reads/writes productions/ in place."""

from __future__ import annotations

import mimetypes
import sys
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.frames import (  # noqa: E402
    frame_board,
    lock_candidate,
    request_asset_still,
    request_shot_still,
    resolve_asset_parent,
    resolve_shot_parent,
    upload_candidate,
)
from director.inbox import list_tasks, scan_inbox, task_for_asset, task_for_shot  # noqa: E402
from director.gates import lock_gate, snapshot  # noqa: E402
from director.fingerprint import prepare_render  # noqa: E402
from director.jobs import assemble_episode, enqueue_render_confirmed, enqueue_review, gpu_configured  # noqa: E402
from director.gpu_caps import gpu_capabilities, minimax_configured, seedance_configured, wan_configured, video_backend_name, video_ready  # noqa: E402
from director.story import ingest_upload, snapshot_story, write_brief  # noqa: E402
from director.inkos import launch_inkos  # noqa: E402
from director.producer import snapshot_producer, write_producer_draft  # noqa: E402
from director.qc import snapshot_qc, write_qc_draft  # noqa: E402
from director.sound_contract import snapshot_sound, write_sound_draft  # noqa: E402
from director.agents import agent_diff  # noqa: E402
from director.writer_checks import check_episode  # noqa: E402
from director.paths import load_dotenv, prod_path, productions_root, safe_under  # noqa: E402
from director.production import (  # noqa: E402
    assets,
    bible,
    coverage,
    create_production,
    import_script,
    overview,
    render_blocking,
    save_bible_file,
    save_coverage,
    save_look,
    save_sets,
    save_shots,
    save_shot_draft,
    accept_shot_draft,
    load_shot_draft,
    shot_board,
    stage,
)
from director.reverse import (  # noqa: E402
    ReverseError,
    enqueue_reverse,
    ingest_video,
    snapshot_reverse,
)
from director.grok_text import text_configured  # noqa: E402
from director.scriptwriter import ScriptError, draft_script, snapshot_scriptwriter  # noqa: E402
from director.store import load_jobs  # noqa: E402
from director.reviewer import load_review, review_storyboard  # noqa: E402
from director.review_contract import evaluate_review_contract, freeze_review_contract, load_contract  # noqa: E402

load_dotenv()

app = FastAPI(title="Short Drama Director", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3101", "http://localhost:3101", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fail(exc: Exception, status: int = 400) -> JSONResponse:
    code = getattr(exc, "code", None)
    return JSONResponse(
        {"error": str(exc), "code": code or exc.__class__.__name__},
        status_code=status,
    )


def payload_dict(payload: Optional[dict]) -> dict:
    return payload or {}


def get_prod(slug: str) -> Path:
    try:
        return prod_path(slug)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "gpu": gpu_configured(),
        "video_ready": video_ready(),
        "video_backend": video_backend_name(),
        "seedance": seedance_configured(),
        "minimax": minimax_configured(),
        "wan": wan_configured(),
        "imagine": bool(__import__("os").environ.get("XAI_API_KEY", "").strip()),
        "grok_text": text_configured(),
        "grok_backend": __import__("director.grok_text", fromlist=["text_backend"]).text_backend(),
        "productions": str(productions_root()),
    }


@app.get("/api/productions")
def api_productions():
    return {"productions": overview()}


@app.post("/api/productions")
def api_create_production(payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        created = create_production(str(payload.get("id") or ""), str(payload.get("title") or ""))
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        return fail(exc, 409 if isinstance(exc, FileExistsError) else 400)
    return created


@app.get("/api/productions/{slug}")
def api_production(slug: str):
    prod = get_prod(slug)
    return {
        "id": slug,
        "path": str(prod),
        "gates": snapshot(prod),
        "gpu": gpu_configured(),
        "video_ready": video_ready(),
        "video_backend": video_backend_name(),
        "seedance": seedance_configured(),
        "minimax": minimax_configured(),
        "wan": wan_configured(),
        "gpu_caps": gpu_capabilities(),
        "imagine": bool(__import__("os").environ.get("XAI_API_KEY", "").strip()),
        "grok_text": text_configured(),
        "grok_backend": __import__("director.grok_text", fromlist=["text_backend"]).text_backend(),
        "reverse": snapshot_reverse(prod),
        "scriptwriter": snapshot_scriptwriter(prod),
        "pipeline": __import__("director.pipeline", fromlist=["snapshot_pipeline"]).snapshot_pipeline(prod),
    }


@app.post("/api/productions/{slug}/gates/lock")
def api_lock(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    prod = get_prod(slug)
    gate_id = str(payload.get("gateId") or payload.get("id") or "")
    try:
        return lock_gate(prod, gate_id, bool(payload.get("locked", True)))
    except PermissionError as exc:
        return fail(exc, 409)
    except ValueError as exc:
        return fail(exc, 400)




@app.get("/api/productions/{slug}/pipeline")
def api_pipeline(slug: str):
    from director.pipeline import snapshot_pipeline

    return snapshot_pipeline(get_prod(slug))


@app.get("/api/productions/{slug}/pipeline/{name}")
def api_pipeline_get(slug: str, name: str):
    from director.pipeline import preview_artifact

    if not name.endswith(".json"):
        name = name + ".json"
    return preview_artifact(get_prod(slug), name)


@app.put("/api/productions/{slug}/pipeline/{name}")
def api_pipeline_put(slug: str, name: str, payload: Optional[dict] = Body(None)):
    from director.pipeline import (
        raise_if,
        validate_assets,
        validate_cut,
        validate_keyframes,
        validate_novel,
        validate_packages,
        validate_shot_list,
        validate_shot_specs,
        validate_writer,
        write_artifact,
    )

    from director.station_agents import _validate_frame_desc_artifact, _validate_scene_cards_artifact

    payload = payload_dict(payload)
    if not name.endswith(".json"):
        name = name + ".json"
    from director.pipeline import episode_artifact_name, parse_artifact_filename, read_artifact

    kind, episode = parse_artifact_filename(name)
    prod = get_prod(slug)
    if kind == "shot_list.json" and str(payload.get("schema") or "") == "shot-table-v2":
        from director.shot_table import sanitize_shot_table

        payload = sanitize_shot_table(payload, writer=read_artifact(prod, episode_artifact_name("writer.json", episode)))
    validators = {
        "novel.json": validate_novel,
        "writer.json": validate_writer,
        "assets.json": lambda data: validate_assets(data, prod),
        "shot_list.json": lambda data: validate_shot_list(data, **_shot_list_context(prod, data, episode)),
        "scene_cards.json": lambda data: _validate_scene_cards_artifact(data, prod),
        "frame_descriptions.json": lambda data: _validate_frame_desc_artifact(data, prod),
        "shot_specs.json": lambda data: validate_shot_specs(data, read_artifact(prod, episode_artifact_name("writer.json", episode))),
        "gen_packages.json": lambda data: validate_packages(
            data,
            read_artifact(prod, "assets.json"),
            read_artifact(prod, episode_artifact_name("shot_specs.json", episode)),
        ),
        "keyframes.json": validate_keyframes,
        "clips.json": __import__("director.pipeline", fromlist=["validate_clips"]).validate_clips,
        "cut.json": validate_cut,
    }
    validator = validators.get(kind)
    if validator:
        try:
            raise_if(validator(payload))
        except PermissionError as exc:
            return fail(exc, 409)
    written = write_artifact(prod, name, payload)
    if kind == "shot_list.json" and str(payload.get("schema") or "") == "shot-table-v2":
        _rerender_shot_table(prod, written)
    return written


def _shot_list_context(prod: Path, data: dict, episode=1) -> dict:
    """A v2 table saved from the studio is checked against the same writer / sets / look / profile as the agent's."""
    if str(data.get("schema") or "") != "shot-table-v2":
        return {}
    from director.shot_table import table_context

    check = table_context(prod, str(data.get("target_model") or "") or None, episode=episode)
    return {"writer": check["writer"], "sets": check["sets"], "profile": check["profile"], "look_text": check["look_text"], "prod": prod}


def _rerender_shot_table(prod: Path, table: dict) -> None:
    """Keep shot-list.draft.md and the compiled specs in step with a hand-edited v2 table. Best effort."""
    try:
        from director.frame_desc import index_by_shot
        from director.pipeline import read_artifact, write_artifact
        from director.production import write_text
        from director.shot_table import compile_specs_from_shot_table, render_shot_table_md, table_context, validate_shot_table

        check = table_context(prod, str(table.get("target_model") or "") or None)
        _errors, warnings = validate_shot_table(table, writer=check["writer"], sets=check["sets"], profile=check["profile"], look_text=check["look_text"], prod=prod)
        specs = compile_specs_from_shot_table(table, aspect=str(table.get("aspect") or "16:9"))
        specs["origin"] = "compiled-from-shot-table"
        write_artifact(prod, "shot_specs.json", specs)
        title = str((read_artifact(prod, "writer.json").get("episode_outline") or [{}])[0].get("title") or "第 01 集")
        write_text(
            prod,
            "03-storyboard/shot-list.draft.md",
            render_shot_table_md(table, title=f"第 01 集 {title}", profile=check["profile"], warnings=warnings, frame_descriptions=index_by_shot(read_artifact(prod, "frame_descriptions.json"))),
        )
    except Exception:  # the artifact itself is already saved; the mirror files are a convenience
        return


@app.post("/api/productions/{slug}/pipeline/seed")
def api_pipeline_seed(slug: str, payload: Optional[dict] = Body(None)):
    from director.pipeline import seed_pipeline_drafts

    payload = payload_dict(payload)
    return seed_pipeline_drafts(get_prod(slug), force=bool(payload.get("force")))


@app.post("/api/productions/{slug}/pipeline/confirm")
def api_pipeline_confirm(slug: str, payload: Optional[dict] = Body(None)):
    from director.pipeline import confirm_packages

    payload = payload_dict(payload)
    try:
        return confirm_packages(get_prod(slug), bool(payload.get("confirmed", True)))
    except PermissionError as exc:
        return fail(exc, 409)


@app.post("/api/productions/{slug}/pipeline/reject")
def api_pipeline_reject(slug: str, payload: Optional[dict] = Body(None)):
    from director.pipeline import reject_to

    payload = payload_dict(payload)
    try:
        return reject_to(
            get_prod(slug),
            from_agent=str(payload.get("fromAgent") or payload.get("from_agent") or ""),
            send_back_to=str(payload.get("sendBackTo") or payload.get("reject_to") or ""),
            reason=str(payload.get("reason") or ""),
            evidence=str(payload.get("evidence") or ""),
        )
    except (PermissionError, ValueError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.post("/api/productions/{slug}/agents/{station}")
def api_station_agent(slug: str, station: str, payload: Optional[dict] = Body(None)):
    from director.grok_text import TextError
    from director.station_agents import run_station_agent

    payload = payload_dict(payload)
    candidates = payload.get("candidates")
    try:
        candidates = int(candidates) if candidates not in (None, "") else None
    except (TypeError, ValueError):
        return fail(ValueError("candidates 必须是整数"), 400)
    scene_ids = payload.get("scene_ids") or payload.get("sceneIds")
    if isinstance(scene_ids, str):
        scene_ids = [s.strip() for s in scene_ids.split(",") if s.strip()]
    scene_ids = [str(s) for s in scene_ids] if isinstance(scene_ids, list) and scene_ids else None
    try:
        episode = int(payload.get("episode") or payload.get("episode_no") or 1)
    except (TypeError, ValueError):
        return fail(ValueError("episode 必须是整数"), 400)
    try:
        return run_station_agent(
            get_prod(slug),
            station,
            brief=str(payload.get("brief") or ""),
            target_model=str(payload.get("targetModel") or payload.get("target_model") or "") or None,
            resume=bool(payload.get("resume", True)),
            candidates=candidates,
            scene_ids=scene_ids,
            episode=episode,
        )
    except TextError as exc:
        return fail(exc, 409)
    except PermissionError as exc:
        return fail(exc, 409)
    except ValueError as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/design/candidates")
def api_design_candidates(slug: str):
    """Raw candidates plus the deterministic metrics the compare page shows next to the critic's scores."""
    from director.direction import candidate_metrics
    from director.station_agents import design_candidates

    data = design_candidates(get_prod(slug))
    for row in data.get("scenes") or []:
        card = row.get("scene_card")
        for cand in row.get("candidates") or []:
            if isinstance(cand, dict):
                cand["metrics"] = candidate_metrics(list(cand.get("shots") or []), card, cand.get("warnings") or [])
    return data


@app.post("/api/productions/{slug}/design/pick")
def api_design_pick(slug: str, payload: Optional[dict] = Body(None)):
    from director.station_agents import pick_candidate

    payload = payload_dict(payload)
    scene_id = str(payload.get("scene_id") or payload.get("sceneId") or "")
    try:
        index = int(payload.get("candidate") if payload.get("candidate") is not None else payload.get("index"))
    except (TypeError, ValueError):
        return fail(ValueError("candidate 必须是候选序号"), 400)
    if not scene_id:
        return fail(ValueError("缺 scene_id"), 400)
    try:
        return pick_candidate(get_prod(slug), scene_id, index)
    except PermissionError as exc:
        return fail(exc, 409)
    except ValueError as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/animatic")
def api_animatic(slug: str, episode: int = 1):
    from director.animatic import snapshot_animatic

    return snapshot_animatic(get_prod(slug), episode)


@app.post("/api/productions/{slug}/animatic")
def api_animatic_build(slug: str, payload: Optional[dict] = Body(None)):
    from director.animatic import build_animatic
    from director.paths import media_url

    payload = payload_dict(payload)
    prod = get_prod(slug)
    try:
        result = build_animatic(
            prod,
            int(payload.get("episode") or 1),
            audio=str(payload.get("audio") or "") or None,
            fps=int(payload.get("fps") or 24),
        )
    except PermissionError as exc:
        return fail(exc, 409)
    except ValueError as exc:
        return fail(exc, 400)
    except RuntimeError as exc:
        return fail(exc, 500)
    result["url"] = media_url(prod, result["file"])
    return result


@app.get("/api/productions/{slug}/feedback")
def api_feedback(slug: str, profile: str = ""):
    from director.model_notes import snapshot_feedback

    return snapshot_feedback(get_prod(slug), profile or None)


@app.post("/api/productions/{slug}/feedback")
def api_feedback_record(slug: str, payload: Optional[dict] = Body(None)):
    from director.model_notes import record_outcome

    payload = payload_dict(payload)
    try:
        return record_outcome(
            get_prod(slug),
            str(payload.get("shot_id") or payload.get("shotId") or ""),
            str(payload.get("verdict") or ""),
            payload.get("tags"),
            str(payload.get("note") or ""),
            str(payload.get("profile_id") or payload.get("profileId") or "") or None,
        )
    except ValueError as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/camera-plot")
def api_camera_plot(slug: str):
    from director.camera_plot import snapshot_camera_plot

    return snapshot_camera_plot(get_prod(slug))


@app.post("/api/productions/{slug}/camera-plot/render")
def api_camera_plot_render(slug: str):
    from director.camera_plot import render_all, snapshot_camera_plot

    prod = get_prod(slug)
    try:
        result = render_all(prod)
    except (OSError, ValueError) as exc:
        return fail(exc, 400)
    result["snapshot"] = snapshot_camera_plot(prod)
    return result

@app.get("/api/productions/{slug}/diff")
def api_diff(slug: str, gateId: str = ""):
    prod = get_prod(slug)
    gate_id = gateId or "C"
    try:
        return agent_diff(prod, gate_id)
    except Exception as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/story")
def api_story(slug: str):
    return snapshot_story(get_prod(slug))


@app.post("/api/productions/{slug}/story/brief")
def api_story_brief(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    return write_brief(get_prod(slug), payload)


@app.post("/api/productions/{slug}/story/inkos")
def api_story_inkos(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    prod = get_prod(slug)
    if any(payload.get(k) for k in ("title", "logline", "notes", "audience")):
        write_brief(prod, payload)
    result = launch_inkos(payload)
    snap = snapshot_story(prod)
    snap["inkos"] = result
    return snap


@app.post("/api/productions/{slug}/story/upload")
async def api_story_upload(slug: str, file: UploadFile = File(...)):
    data = await file.read()
    try:
        return ingest_upload(get_prod(slug), file.filename or "upload.txt", data)
    except ValueError as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/producer")
def api_producer(slug: str):
    return snapshot_producer(get_prod(slug))


@app.post("/api/productions/{slug}/producer/draft")
def api_producer_draft(slug: str):
    return write_producer_draft(get_prod(slug))


@app.get("/api/productions/{slug}/sound")
def api_sound(slug: str):
    return snapshot_sound(get_prod(slug))


@app.post("/api/productions/{slug}/sound/draft")
def api_sound_draft(slug: str):
    return write_sound_draft(get_prod(slug))


@app.post("/api/productions/{slug}/sound/sfx")
def api_sound_sfx(slug: str, payload: Optional[dict] = Body(None)):
    from director.sfx import run_mix

    payload = payload_dict(payload)
    try:
        return run_mix(
            get_prod(slug),
            episode=int(payload.get("episode") or 1),
            dry_run=bool(payload.get("dry_run")),
            force=bool(payload.get("force")),
            preview=payload.get("preview", True),
        )
    except ValueError as exc:
        return fail(exc, 400)
    except Exception as exc:
        return fail(exc, 500)


@app.get("/api/productions/{slug}/qc")
def api_qc(slug: str):
    return snapshot_qc(get_prod(slug))


@app.post("/api/productions/{slug}/qc/draft")
def api_qc_draft(slug: str):
    return write_qc_draft(get_prod(slug))


@app.get("/api/productions/{slug}/writer-checks")
def api_writer_checks(slug: str):
    prod = get_prod(slug)
    from director.production import load_json

    shots = load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or []
    return {"issues": check_episode(prod, shots)}


@app.get("/api/gpu")
def api_gpu():
    return gpu_capabilities(force=True)


@app.get("/api/productions/{slug}/bible")
def api_bible(slug: str):
    return bible(get_prod(slug))


@app.put("/api/productions/{slug}/bible")
def api_save_bible(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    rel = payload.get("path")
    if not rel:
        raise HTTPException(400, "缺少 path")
    try:
        return save_bible_file(get_prod(slug), rel, payload.get("content") or "")
    except ValueError as exc:
        return fail(exc)


@app.post("/api/productions/{slug}/script")
def api_script(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    text = payload.get("text") or ""
    if not text.strip():
        raise HTTPException(400, "剧本是空的")
    return import_script(get_prod(slug), text)


@app.get("/api/productions/{slug}/scriptwriter")
def api_scriptwriter(slug: str):
    return snapshot_scriptwriter(get_prod(slug))


@app.post("/api/productions/{slug}/scriptwriter")
def api_scriptwriter_run(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return draft_script(
            get_prod(slug),
            brief=str(payload.get("brief") or ""),
            use_grok=bool(payload.get("useGrok", True)),
        )
    except ScriptError as exc:
        return fail(exc, 400)


@app.post("/api/productions/{slug}/breakdown")
def api_breakdown(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    prod = get_prod(slug)
    brief = str(payload.get("brief") or "")
    from director.grok_text import TextError, text_configured
    from director.station_agents import run_station_agent
    if payload.get("rulesOnly"):
        try:
            return draft_script(prod, brief=brief, use_grok=False)
        except ScriptError as exc:
            return fail(exc, 400)
    if text_configured():
        try:
            candidates = payload.get("candidates")
            result = run_station_agent(
                prod,
                "design",
                brief=brief,
                target_model=str(payload.get("targetModel") or payload.get("target_model") or "") or None,
                candidates=int(candidates) if candidates not in (None, "") else None,
            )
            result["shot_count"] = len((result.get("artifact") or {}).get("shots") or [])
            result["origin"] = "station-agent"
            return result
        except (TextError, PermissionError) as exc:
            return fail(exc, 409)
    try:
        written = draft_script(prod, brief=brief, use_grok=False)
        written["origin"] = written.get("origin") or "director-breakdown"
        written["used_tokens"] = False
        written["note"] = "没有文本密钥，只用规则编译器拆镜，不是导演 Agent。"
        return written
    except ScriptError as exc:
        return fail(exc, 400)


@app.get("/api/productions/{slug}/assets")
def api_assets(slug: str):
    return assets(get_prod(slug))


@app.put("/api/productions/{slug}/assets/look")
def api_look(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    return save_look(get_prod(slug), payload.get("content") or "")


@app.get("/api/productions/{slug}/stage")
def api_stage(slug: str):
    return stage(get_prod(slug))


@app.put("/api/productions/{slug}/stage")
def api_save_stage(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return save_sets(get_prod(slug), payload)
    except ValueError as exc:
        return fail(exc)


@app.post("/api/productions/{slug}/stage/render")
def api_render_stage(slug: str):
    try:
        return render_blocking(get_prod(slug))
    except PermissionError as exc:
        return fail(exc, 409)
    except RuntimeError as exc:
        return fail(exc, 500)


@app.get("/api/productions/{slug}/coverage")
def api_coverage(slug: str):
    return coverage(get_prod(slug))


@app.put("/api/productions/{slug}/coverage")
def api_save_coverage(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return save_coverage(get_prod(slug), payload.get("field"), payload.get("content") or "")
    except ValueError as exc:
        return fail(exc)


@app.put("/api/productions/{slug}/shots")
def api_save_shots(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return save_shots(get_prod(slug), payload)
    except (ValueError, PermissionError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.get("/api/productions/{slug}/shots")
def api_shots(slug: str):
    return shot_board(get_prod(slug))


@app.get("/api/productions/{slug}/grid")
def api_grid(slug: str, source: str = "official"):
    from director.grid import storyboard_grid

    if source not in {"draft", "official"}:
        raise HTTPException(400, "source 只能是 draft 或 official")
    return storyboard_grid(get_prod(slug), source=source)


@app.get("/api/productions/{slug}/frames")
def api_frames(slug: str):
    return frame_board(get_prod(slug))


@app.get("/api/productions/{slug}/frames/parent")
def api_frame_parent(slug: str, shotId: str):
    try:
        parent = resolve_shot_parent(get_prod(slug), shotId)
        parent.pop("shot", None)
        return parent
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.get("/api/productions/{slug}/shots/draft")
def api_shot_draft(slug: str):
    return load_shot_draft(get_prod(slug))


@app.put("/api/productions/{slug}/shots/draft")
def api_save_shot_draft(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return save_shot_draft(get_prod(slug), payload)
    except ValueError as exc:
        return fail(exc)


@app.post("/api/productions/{slug}/shots/draft/accept")
def api_accept_shot_draft(slug: str):
    try:
        return accept_shot_draft(get_prod(slug))
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.get("/api/productions/{slug}/review-draft")
def api_load_review_draft(slug: str):
    return load_review(get_prod(slug))


@app.post("/api/productions/{slug}/review-draft")
def api_review_draft(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    source = str(payload.get("source") or "draft")
    if source not in {"draft", "official"}:
        raise HTTPException(400, "source 只能是 draft 或 official")
    return review_storyboard(get_prod(slug), source=source)


@app.get("/api/productions/{slug}/inbox")
def api_inbox(slug: str):
    prod = get_prod(slug)
    return {"tasks": list_tasks(prod), "path": str(prod / ".director" / "inbox")}


@app.post("/api/productions/{slug}/inbox/task")
def api_inbox_task(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    prod = get_prod(slug)
    try:
        if payload.get("shotId"):
            return task_for_shot(prod, payload["shotId"])
        return task_for_asset(prod, payload.get("kind"), payload.get("slug"), payload.get("slot"), payload.get("prompt") or "")
    except (FileNotFoundError, ValueError) as exc:
        return fail(exc, 400)


@app.post("/api/productions/{slug}/inbox/scan")
def api_inbox_scan(slug: str):
    return scan_inbox(get_prod(slug))


@app.post("/api/productions/{slug}/frames/generate")
def api_generate_frame(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    prod = get_prod(slug)
    try:
        if payload.get("shotId"):
            return request_shot_still(prod, payload["shotId"], payload.get("prompt"))
        return request_asset_still(
            prod,
            payload.get("kind"),
            payload.get("slug"),
            payload.get("slot"),
            payload.get("prompt") or "",
        )
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.post("/api/productions/{slug}/frames/upload")
async def api_upload_frame(
    slug: str,
    target: str = Form(...),
    dest: str = Form(""),
    parent: str = Form(""),
    file: UploadFile = File(...),
):
    prod = get_prod(slug)
    data = await file.read()
    try:
        if dest.startswith("04-frames/") and dest.endswith(".jpg"):
            shot_id = Path(dest).stem
            parent_info = resolve_shot_parent(prod, shot_id)
            if not parent and not parent_info.get("path"):
                raise PermissionError("上传首帧也必须挂父镜")
            parent = parent or parent_info["path"]
        elif dest.startswith("02-assets/"):
            parts = Path(dest).parts
            if len(parts) >= 4:
                parent_info = resolve_asset_parent(prod, "character" if parts[1] == "characters" else "scene", parts[2], Path(dest).stem)
                if parent_info["kind"] == "edit" and not parent_info["exists"]:
                    raise PermissionError(parent_info["reason"])
                parent = parent or parent_info.get("path") or ""
        created = upload_candidate(prod, target, file.filename or "upload.jpg", data, parent or None)
        return created
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.post("/api/productions/{slug}/frames/lock")
def api_lock_frame(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return lock_candidate(get_prod(slug), payload.get("candidateId"), payload.get("dest"))
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.get("/api/productions/{slug}/jobs")
def api_jobs(slug: str):
    return load_jobs(get_prod(slug))


@app.post("/api/productions/{slug}/render/prepare")
def api_render_prepare(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return prepare_render(
            get_prod(slug),
            payload.get("shotIds"),
            bool(payload.get("reviewTrack")),
            payload.get("episode") or 1,
        )
    except (PermissionError, ValueError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.post("/api/productions/{slug}/render")
def api_render(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return enqueue_render_confirmed(
            get_prod(slug),
            payload.get("fingerprint"),
            payload.get("shotIds"),
            bool(payload.get("reviewTrack")),
            payload.get("episode") or 1,
        )
    except (PermissionError, ValueError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 400)


@app.get("/api/productions/{slug}/review-contract")
def api_review_contract(slug: str):
    return load_contract(get_prod(slug)) or {"exists": False}


@app.post("/api/productions/{slug}/review")
def api_review(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        prod = get_prod(slug)
        contract = freeze_review_contract(prod, payload.get("shotIds"))
        job = enqueue_review(prod, payload.get("shotIds"))
        job["frozen"] = contract
        return job
    except (PermissionError, ValueError) as exc:
        prod = get_prod(slug)
        evaluated = evaluate_review_contract(prod)
        return JSONResponse(
            {
                "error": str(exc),
                "code": exc.__class__.__name__,
                "contract": evaluated,
            },
            status_code=409 if isinstance(exc, PermissionError) else 400,
        )


@app.post("/api/productions/{slug}/assemble")
def api_assemble(slug: str):
    try:
        return assemble_episode(get_prod(slug))
    except (PermissionError, RuntimeError) as exc:
        return fail(exc, 409 if isinstance(exc, PermissionError) else 500)


@app.get("/api/productions/{slug}/reverse")
def api_reverse(slug: str):
    return snapshot_reverse(get_prod(slug))


@app.post("/api/productions/{slug}/reverse/upload")
async def api_reverse_upload(slug: str, file: UploadFile = File(...)):
    prod = get_prod(slug)
    suffix = Path(file.filename or "reference.mp4").suffix.lower() or ".mp4"
    tmp = prod / "00-reverse" / "source" / f"upload{suffix}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    tmp.write_bytes(data)
    try:
        info = ingest_video(prod, tmp, file.filename or "reference.mp4")
        if tmp.exists() and tmp.name != "reference.mp4":
            tmp.unlink(missing_ok=True)
        return info
    except ReverseError as exc:
        return fail(exc, 400)


@app.post("/api/productions/{slug}/reverse/analyze")
def api_reverse_analyze(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return enqueue_reverse(
            get_prod(slug),
            action="analyze",
            brief=str(payload.get("brief") or ""),
            use_grok=bool(payload.get("useGrok", True)),
        )
    except ReverseError as exc:
        return fail(exc, 400)


@app.post("/api/productions/{slug}/reverse/localize")
def api_reverse_localize(slug: str, payload: Optional[dict] = Body(None)):
    payload = payload_dict(payload)
    try:
        return enqueue_reverse(
            get_prod(slug),
            action="localize",
            brief=str(payload.get("brief") or ""),
            use_grok=bool(payload.get("useGrok", True)),
        )
    except ReverseError as exc:
        return fail(exc, 400)


@app.get("/media/{slug}/{rel_path:path}")
def media(slug: str, rel_path: str):
    prod = get_prod(slug)
    try:
        path = safe_under(prod, rel_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "文件不存在")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return FileResponse(path, media_type=mime, headers=headers)


studio_dist = ROOT / "studio" / "dist"
if studio_dist.exists():
    app.mount("/", StaticFiles(directory=studio_dist, html=True), name="studio")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "director_server:app",
        app_dir=str(SCRIPTS),
        host="127.0.0.1",
        port=int(__import__("os").environ.get("DIRECTOR_API_PORT", "18765")),
        reload=False,
    )


if __name__ == "__main__":
    main()
