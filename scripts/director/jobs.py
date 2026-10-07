"""GPU I2V jobs. Missing LOCAL_H3_BASE leaves jobs queued; never fake success."""

from __future__ import annotations

import math
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from .gates import ken_burns_blocked, require_fresh_gate, run_check
from .paths import ROOT
from .shot_repo import list_shots, select_shots
from .store import exclusive_state_lock, load_jobs, save_jobs


def gpu_configured() -> bool:
    return video_ready()


def seedance_configured() -> bool:
    return bool(os.environ.get("ARK_API_KEY", "").strip())


def minimax_configured() -> bool:
    return bool(os.environ.get("MINIMAX_API_KEY", "").strip())


def wan_configured() -> bool:
    return bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())


def video_ready() -> bool:
    return bool(os.environ.get("LOCAL_H3_BASE", "").strip()) or seedance_configured() or minimax_configured() or wan_configured()


def default_render_backend() -> str:
    if os.environ.get("DIRECTOR_VIDEO_BACKEND", "").strip():
        return os.environ["DIRECTOR_VIDEO_BACKEND"].strip()
    if seedance_configured():
        return "seedance"
    if minimax_configured():
        return "minimax"
    if wan_configured():
        return "wan"
    if os.environ.get("LOCAL_H3_BASE", "").strip():
        return "local"
    return ""


def _shots(prod: Path, episode=1) -> list[dict]:
    return list_shots(prod, episode)


def _append_job(prod: Path, job: dict) -> dict:
    with exclusive_state_lock(prod, "jobs"):
        data = load_jobs(prod)
        data.setdefault("jobs", [])
        data["jobs"].insert(0, job)
        save_jobs(prod, data)
        return job


def _update_job(prod: Path, job_id: str, **fields) -> dict:
    try:
        with exclusive_state_lock(prod, "jobs"):
            data = load_jobs(prod)
            for job in data.get("jobs") or []:
                if job.get("id") == job_id:
                    job.update(fields)
                    job["updated_at"] = int(time.time())
                    save_jobs(prod, data)
                    return job
            raise FileNotFoundError(job_id)
    except (FileNotFoundError, OSError):
        if not Path(prod).exists():
            return {}
        raise


def enqueue_render(prod: Path, shot_ids: Optional[list[str]] = None, review_track: bool = False) -> dict:
    return enqueue_render_confirmed(prod, None, shot_ids, review_track)


def enqueue_render_confirmed(prod: Path, fingerprint: Optional[str] = None,
                             shot_ids: Optional[list[str]] = None, review_track: bool = False,
                             episode=1, revision_id: str = "") -> dict:
    from .context import ProductionContext, using_context

    ctx = ProductionContext.resolve(prod, episode, revision_id)
    with using_context(ctx):
        return _enqueue_render_confirmed(prod, fingerprint, shot_ids, review_track, ctx.episode_token)


def _enqueue_render_confirmed(
    prod: Path,
    fingerprint: Optional[str] = None,
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode=1,
) -> dict:
    from .context import ProductionContext
    from .narrative import require_design_review

    ctx = ProductionContext.resolve(prod, episode)
    episode = ctx.episode_token
    selected = select_shots(prod, shot_ids, episode)
    selected_ids = [shot["id"] for shot in selected]
    require_design_review(prod, episode)
    require_fresh_gate(prod, "C")
    from .pipeline import assert_clips_passed, assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod, episode, selected_shot_ids=selected_ids)
        assert_keyframes_passed(prod, episode, selected_shot_ids=selected_ids)
        from .show_policy import load_show_policy

        if ctx.mode == "registered" or load_show_policy(prod).animatic_required:
            from .animatic import require_animatic_approval

            require_animatic_approval(prod, episode)
    check = run_check(prod, episode=episode)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    from .fingerprint import confirmed_snapshot_rel, consume_render_fingerprint, require_task_inputs

    require_task_inputs(prod, selected, episode)
    used = consume_render_fingerprint(prod, fingerprint, [shot["id"] for shot in selected], review_track, episode)
    if not isinstance(used, dict) or not used.get("snapshot") or not used.get("fingerprint"):
        raise PermissionError("consume must return a paired fingerprint and snapshot")
    if used["snapshot"] != confirmed_snapshot_rel(used["fingerprint"]):
        raise PermissionError("consumed fingerprint and snapshot are not a pair")
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "kind": "render",
        "status": "queued",
        "shot_ids": list(used.get("shot_ids") or [shot["id"] for shot in selected]),
        "review_track": review_track,
        "gpu": gpu_configured(),
        "backend": default_render_backend() or None,
        "fingerprint": used["fingerprint"],
        "snapshot": used["snapshot"],
        "episode": used.get("episode", episode),
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "log": [],
        "error": None,
        "outputs": [],
    }
    if not video_ready():
        job["log"].append("未配置 ARK_API_KEY、MINIMAX_API_KEY 或 LOCAL_H3_BASE，任务停在 queued，不假装成功。")
        return _append_job(prod, job)
    _append_job(prod, job)
    thread = threading.Thread(target=_run_render, args=(prod, job["id"]), daemon=True)
    thread.start()
    return job


def enqueue_review(prod: Path, shot_ids: Optional[list[str]] = None, episode=1) -> dict:
    from .pipeline import episode_shot_dir

    selected = select_shots(prod, shot_ids, episode)
    shot_dir = episode_shot_dir(episode)
    missing = [shot["id"] for shot in selected if not (prod / shot_dir / f"{shot['id']}.mp4").exists()]
    if missing:
        raise PermissionError("缺单镜视频：" + ", ".join(missing))
    for shot in selected:
        video = prod / shot_dir / f"{shot['id']}.mp4"
        if ken_burns_blocked(video):
            raise PermissionError(f"{video.name} 是 Ken Burns 路径，不能进审片")
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "kind": "review",
        "status": "queued",
        "shot_ids": [shot["id"] for shot in selected],
        "episode": episode,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "log": [],
        "error": None,
        "outputs": [],
    }
    _append_job(prod, job)
    thread = threading.Thread(target=_run_review, args=(prod, job["id"]), daemon=True)
    thread.start()
    return job


def _run_render(prod: Path, job_id: str) -> None:
    _update_job(prod, job_id, status="running")
    data = load_jobs(prod)
    job = next(item for item in data["jobs"] if item["id"] == job_id)
    backend = job.get("backend") or default_render_backend() or "local"
    from .pipeline import uses_pipeline

    if uses_pipeline(prod) and backend in {"seedance", "ark"}:
        snapshot = str(job.get("snapshot") or "").strip()
        if not snapshot:
            _update_job(prod, job_id, status="failed", error="missing confirmed snapshot; worker will not recompile")
            return
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "render_seedance_packages.py"),
            "--prod",
            str(prod),
            "--from-snapshot",
            snapshot,
            "--expected-fingerprint",
            str(job.get("fingerprint") or ""),
            "--episode",
            str(job.get("episode") or 1),
        ]
        if job.get("shot_ids"):
            cmd += ["--only", *job["shot_ids"]]
    else:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "render_shots.py"),
            "--prod",
            str(prod),
            "--backend",
            backend,
            "--skip-assemble",
        ]
        if job.get("shot_ids"):
            cmd += ["--only", *job["shot_ids"]]
        if job.get("review_track"):
            cmd.append("--review-track")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            _update_job(prod, job_id, status="failed", error=log[-1200:], log=[log[-2000:]])
            return
        if uses_pipeline(prod) and backend in {"seedance", "ark"} and job.get("review_track"):
            selected_ids = list(job.get("shot_ids") or [])
            from .takes import episode_key as _episode_key

            ep_key = _episode_key(job.get("episode") or 1)
            suffix = "" if ep_key == "1" else f".{ep_key}"
            out = prod / "06-export" / (("preview-vo" if not selected_ids else "preview-partial-vo") + f"{suffix}.mp4")
            mix = [
                sys.executable,
                str(ROOT / "scripts" / "mix_review_track.py"),
                "--prod",
                str(prod),
                "--out",
                str(out),
                "--episode",
                str(job.get("episode") or 1),
            ]
            if selected_ids:
                mix += ["--only", *selected_ids]
            mix_proc = subprocess.run(mix, capture_output=True, text=True)
            log = (log + "\n" + ((mix_proc.stdout or "") + "\n" + (mix_proc.stderr or "")).strip()).strip()
            if mix_proc.returncode != 0:
                _update_job(prod, job_id, status="failed", error=log[-1200:], log=[log[-2000:]])
                return
        outputs = []
        clip_records = []
        fallback_from = None
        scaled_to = None
        used_backend = backend
        from .pipeline import episode_frame_dir, episode_shot_dir
        from .video_fallback import read_clip_record

        episode = job.get("episode") or 1
        from .context import ProductionContext
        ctx = ProductionContext.resolve(prod, episode)
        shot_dir = ctx.shot_dir()
        frame_dir = ctx.frame_dir()
        for shot_id in job.get("shot_ids") or []:
            video = prod / shot_dir / f"{shot_id}.mp4"
            last = prod / frame_dir / f"{shot_id}-last.jpg"
            extracted = prod / shot_dir / f"{shot_id}-last.jpg"
            if video.exists() and ken_burns_blocked(video):
                video.unlink()
                _update_job(
                    prod,
                    job_id,
                    status="failed",
                    error=f"{shot_id} 产出被识别为 Ken Burns，已删除",
                )
                return
            if video.exists():
                outputs.append(f"{shot_dir}/{shot_id}.mp4")
                record = read_clip_record(video)
                if record:
                    clip_records.append(record)
                    if record.get("fallback_from"):
                        used_backend = record.get("backend") or "minimax_h3"
                        fallback_from = record.get("fallback_from")
                        scaled_to = record.get("scaled_to")
            if last.exists():
                outputs.append(f"{frame_dir}/{shot_id}-last.jpg")
            elif extracted.exists():
                outputs.append(f"{shot_dir}/{shot_id}-last.jpg")
        fields = {
            "status": "ready",
            "log": [log[-2000:]],
            "outputs": outputs,
            "error": None,
            "backend": used_backend,
            "review_status": "not_reviewed",
            "approved": False,
            "revision": ctx.to_dict(),
        }
        if fallback_from:
            fields["fallback_from"] = fallback_from
            fields["scaled_to"] = scaled_to
        if clip_records:
            fields["clip_records"] = clip_records
        _update_job(prod, job_id, **fields)
    except Exception as exc:
        _update_job(prod, job_id, status="failed", error=str(exc))


def _run_review(prod: Path, job_id: str) -> None:
    _update_job(prod, job_id, status="running")
    data = load_jobs(prod)
    job = next(item for item in data["jobs"] if item["id"] == job_id)
    from .takes import episode_key as _episode_key

    ep_key = _episode_key(job.get("episode") or 1)
    suffix = "" if ep_key == "1" else f".{ep_key}"
    out = prod / "06-export" / (("preview-vo" if not job.get("shot_ids") else "preview-partial-vo") + f"{suffix}.mp4")
    if len(job.get("shot_ids") or []) == len(_shots(prod, job.get("episode") or 1)):
        out = prod / "06-export" / f"preview-vo{suffix}.mp4"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "mix_review_track.py"),
        "--prod",
        str(prod),
        "--out",
        str(out),
        "--episode",
        str(job.get("episode") or 1),
    ]
    if job.get("shot_ids"):
        cmd += ["--only", *job["shot_ids"]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            _update_job(prod, job_id, status="failed", error=log[-1200:], log=[log[-2000:]])
            return
        if ken_burns_blocked(out):
            _update_job(prod, job_id, status="failed", error="审片输出被识别为 Ken Burns")
            return
        from .review_contract import evaluate_review_contract

        contract = evaluate_review_contract(prod, out)
        _update_job(
            prod,
            job_id,
            status="ready",
            log=[log[-2000:]],
            outputs=[str(out.relative_to(prod))],
            error=None,
            contract=contract,
        )
    except Exception as exc:
        _update_job(prod, job_id, status="failed", error=str(exc))


def _finite_span(start: float, end: float, label: str) -> tuple[float, float]:
    try:
        inn = float(start)
        out = float(end)
    except (TypeError, ValueError) as exc:
        raise PermissionError(f"{label} in/out must be numbers") from exc
    if not math.isfinite(inn) or not math.isfinite(out) or out <= inn:
        raise PermissionError(f"{label} needs a finite range with out > in")
    return inn, out


def _trim_segment_av(
    *,
    video_src: Path,
    video_in: float,
    video_out: float,
    audio_src: Path,
    audio_in: float,
    audio_out: float,
    dest: Path,
    audio_mode: str = "source",
    speed: float = 1.0,
    output_duration_sec: Optional[float] = None,
    fps: int = 30,
) -> None:
    video_in, video_out = _finite_span(video_in, video_out, dest.name)
    mode = str(audio_mode or "source").strip().lower()
    if mode not in {"source", "silent"}:
        raise PermissionError(f"audio_mode must be source or silent, not {audio_mode}")
    if mode == "source":
        audio_in, audio_out = _finite_span(audio_in, audio_out, dest.name + " audio")
    speed = float(speed)
    if not math.isfinite(speed) or speed <= 0:
        raise PermissionError("speed must be finite and positive")
    source_dur = video_out - video_in
    fps = int(fps)
    if fps < 1 or fps > 120:
        raise PermissionError("fps must be 1..120")
    ideal = source_dur / speed
    frames = max(1, round(float(output_duration_sec) * fps)) if output_duration_sec is not None else max(1, math.ceil(ideal * fps - 0.00001))
    video_dur = frames / fps
    if video_dur > ideal + 1 / fps + 0.001:
        raise PermissionError("output duration would add unrecorded video padding")
    audio_dur = (audio_out - audio_in) if mode == "source" else video_dur
    dest.parent.mkdir(parents=True, exist_ok=True)
    picture = dest.with_name(dest.stem + "-v.mp4")
    sound = dest.with_name(dest.stem + "-a.m4a")
    video_cmd = [
        "ffmpeg", "-y", "-ss", f"{video_in:.3f}", "-t", f"{source_dur:.3f}", "-i", str(video_src),
        "-an", "-vf", f"setpts=(PTS-STARTPTS)/{speed:.8f},fps={fps}", "-frames:v", str(frames),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        str(picture),
    ]
    proc = subprocess.run(video_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"{dest.name} 画面修剪失败")
    if mode == "silent":
        audio_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{video_dur:.3f}", "-c:a", "aac", "-b:a", "160k", str(sound),
        ]
    else:
        rates = []
        remaining = speed
        while remaining > 2:
            rates.append("atempo=2")
            remaining /= 2
        while remaining < 0.5:
            rates.append("atempo=0.5")
            remaining *= 2
        rates.append(f"atempo={remaining:.8f}")
        audio_cmd = [
            "ffmpeg", "-y", "-ss", f"{audio_in:.3f}", "-t", f"{audio_dur:.3f}", "-i", str(audio_src),
            "-vn", "-af", ",".join(rates), "-c:a", "aac", "-b:a", "160k",
            str(sound),
        ]
    audio_proc = subprocess.run(audio_cmd, capture_output=True, text=True)
    if audio_proc.returncode != 0:
        raise RuntimeError(audio_proc.stderr or audio_proc.stdout or f"{dest.name} 声音修剪失败")
    mux = [
        "ffmpeg", "-y", "-i", str(picture), "-i", str(sound),
        "-filter_complex", f"[1:a]apad,atrim=0:{video_dur:.3f}[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        str(dest),
    ]
    mux_proc = subprocess.run(mux, capture_output=True, text=True)
    if mux_proc.returncode != 0:
        raise RuntimeError(mux_proc.stderr or mux_proc.stdout or f"{dest.name} 音画合成失败")


def assemble_episode(prod: Path, episode=1, *, candidate: bool = False, revision_id: str = "") -> dict:
    """Render a review export. Approval is a separate, source-bound action."""
    from .context import ProductionContext
    from .pipeline import default_cut_from_specs, uses_pipeline
    from .narrative import (normalize_cut, require_cut_media_reviews, require_event_coverage,
                            inspect_narrative, media_path, write_export_receipt)
    from .takes import episode_export_rel, episode_key

    ctx = ProductionContext.resolve(prod, episode, revision_id)
    token = ctx.episode_token
    shots = _shots(prod, token)
    cut = ctx.read_artifact("cut.json")
    if not cut:
        cut = default_cut_from_specs(prod, [shot["id"] for shot in shots], token)
    try:
        segments = normalize_cut(prod, cut, token)
    except (ValueError, OSError) as exc:
        raise PermissionError("剪辑输入无效：" + str(exc)) from exc
    if not segments:
        raise PermissionError("时间线没有采用任何镜头")
    known = {shot["id"] for shot in shots}
    if (ctx.mode == "registered" or known) and {seg["shot_id"] for seg in segments} - known:
        raise PermissionError("时间线有本版本分镜表以外的镜号")
    shot_root = prod / ctx.shot_dir()
    if shot_root.exists() and any(ken_burns_blocked(p) for p in shot_root.iterdir() if p.is_file()):
        raise PermissionError("单镜目录仍有 Ken Burns 文件；不能当作正式视频拼接")
    if not candidate:
        if uses_pipeline(prod):
            require_cut_media_reviews(prod, cut, token)
        if ctx.mode == "registered":
            require_event_coverage(prod, token, cut=cut)
    export_rel = episode_export_rel(token)
    if candidate:
        export_rel = str(Path(export_rel).with_name(Path(export_rel).stem + ".candidate.mp4"))
    dest = media_path(prod, export_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = prod / ".director" / "cut-work" / episode_key(token) / ("candidate" if candidate else "review")
    work.mkdir(parents=True, exist_ok=True)
    list_path = work / "concat.txt"
    lines = []
    for index, seg in enumerate(segments):
        video_src = media_path(prod, seg["source"])
        audio_src = media_path(prod, seg["audio_source"])
        if not video_src.is_file() or (seg["audio_mode"] != "silent" and not audio_src.is_file()):
            raise PermissionError(f"{seg['shot_id']} 缺实际采用素材")
        if ken_burns_blocked(video_src) or ken_burns_blocked(audio_src):
            raise PermissionError(f"{video_src.name} 是 Ken Burns 路径，不能进入成片")
        clip = work / f"{index:03d}-{seg['shot_id']}.mp4"
        _trim_segment_av(video_src=video_src, video_in=seg["in_sec"], video_out=seg["out_sec"],
                         audio_src=audio_src, audio_in=seg["audio_in_sec"], audio_out=seg["audio_out_sec"],
                         audio_mode=seg["audio_mode"], speed=seg["speed"], output_duration_sec=seg["output_duration_sec"], fps=seg["fps"], dest=clip)
        lines.append("file '" + str(clip).replace("'", "'\\''") + "'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    staged = work / "export.mp4"
    proc = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k", str(staged),
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "assemble 失败")
    # Preserve the last usable export until the replacement has rendered successfully.
    staged.replace(dest)
    contract = ctx.read_artifact("events.json")
    if contract:
        write_export_receipt(prod, contract, cut, export_rel, token)
    status = "candidate" if candidate else "pending_sequence_review"
    result = {"ok": True, "output": export_rel, "stdout": proc.stdout,
              "used": [seg["shot_id"] for seg in segments],
              "takes": [row["take_id"] for row in cut.get("timeline") or [] if row.get("used", True) and row.get("take_id")],
              "episode": episode_key(token), "revision": ctx.to_dict(), "status": status,
              "narrative": inspect_narrative(prod, token, cut=cut), "approved": False}
    result["not_in_edit"] = sorted(known - {seg["shot_id"] for seg in segments})
    result["delivery_scope"] = "partial" if result["not_in_edit"] else "all_planned_shots"
    if candidate:
        # Candidate previews never replace the official EDL or any approval.
        (work / "candidate-export.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        cut = {**cut, "final_file": export_rel, "status": status, "episode": episode_key(token),
               "delivery_scope": result["delivery_scope"], "not_in_edit": result["not_in_edit"], "approved": False}
        path = ctx.artifact_path("cut.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cut, ensure_ascii=False, indent=2) + "\n")
    return result
