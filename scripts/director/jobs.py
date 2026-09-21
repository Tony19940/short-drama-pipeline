"""GPU I2V jobs. Missing LOCAL_H3_BASE leaves jobs queued; never fake success."""

from __future__ import annotations

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


def enqueue_render_confirmed(
    prod: Path,
    fingerprint: Optional[str] = None,
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode=1,
) -> dict:
    require_fresh_gate(prod, "C")
    from .pipeline import assert_clips_passed, assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod, episode)
        assert_keyframes_passed(prod, episode)
        from .show_policy import load_show_policy

        if load_show_policy(prod).animatic_required:
            from .animatic import require_animatic_approval

            require_animatic_approval(prod, episode)
    check = run_check(prod)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    selected = select_shots(prod, shot_ids, episode)
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
        shot_dir = episode_shot_dir(episode)
        frame_dir = episode_frame_dir(episode)
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


def _trim_segment_av(
    *,
    video_src: Path,
    video_in: float,
    video_out: float,
    audio_src: Path,
    audio_in: float,
    audio_out: float,
    dest: Path,
) -> None:
    video_dur = max(0.1, float(video_out) - float(video_in))
    audio_dur = max(0.1, float(audio_out) - float(audio_in)) if float(audio_out) > float(audio_in) else video_dur
    dest.parent.mkdir(parents=True, exist_ok=True)
    picture = dest.with_name(dest.stem + "-v.mp4")
    sound = dest.with_name(dest.stem + "-a.m4a")
    video_cmd = [
        "ffmpeg", "-y", "-ss", f"{float(video_in):.3f}", "-i", str(video_src),
        "-t", f"{video_dur:.3f}", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        str(picture),
    ]
    proc = subprocess.run(video_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"{dest.name} 画面修剪失败")
    audio_cmd = [
        "ffmpeg", "-y", "-ss", f"{float(audio_in):.3f}", "-i", str(audio_src),
        "-t", f"{audio_dur:.3f}", "-vn", "-c:a", "aac", "-b:a", "160k",
        str(sound),
    ]
    audio_proc = subprocess.run(audio_cmd, capture_output=True, text=True)
    if audio_proc.returncode != 0:
        silent = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
            "-t", f"{video_dur:.3f}", "-c:a", "aac", "-b:a", "160k", str(sound),
        ]
        silent_proc = subprocess.run(silent, capture_output=True, text=True)
        if silent_proc.returncode != 0:
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


def assemble_episode(prod: Path, episode=1) -> dict:
    from .pipeline import (
        assert_clips_passed,
        default_cut_from_specs,
        duration_for_shot,
        episode_artifact_name,
        episode_label,
        episode_shot_dir,
        read_artifact,
        uses_pipeline,
        validate_cut,
        write_artifact,
    )
    from .takes import (
        episode_export_rel,
        episode_key,
        resolve_segment_takes,
        resolve_shot_media,
        segments_from_timeline,
        take_media_file,
    )

    if uses_pipeline(prod):
        assert_clips_passed(prod, episode)
    shots = _shots(prod, episode)
    cut_name = episode_artifact_name("cut.json", episode)
    cut = read_artifact(prod, cut_name) or (read_artifact(prod, "cut.json") if not episode_label(episode) else {})
    timeline = list(cut.get("timeline") or [])
    if not timeline:
        cut = default_cut_from_specs(prod, [shot["id"] for shot in shots], episode)
        timeline = list(cut.get("timeline") or [])
        write_artifact(prod, cut_name, cut)
    errors = validate_cut(cut) if cut else []
    if errors:
        raise PermissionError(errors[0])
    used = [item for item in timeline if item.get("used", True)]
    if not used:
        raise PermissionError("时间线没有采用任何镜头")
    shot_dir = prod / episode_shot_dir(episode)
    if shot_dir.exists():
        for path in shot_dir.iterdir():
            if path.is_file() and ken_burns_blocked(path):
                raise PermissionError(f"{path.name} 是 Ken Burns 路径，不能进入成片")
    export_rel = episode_export_rel(episode)
    dest = prod / export_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and ken_burns_blocked(dest):
        dest.unlink()
    work = prod / ".director" / "cut-work" / episode_key(episode)
    if work.exists():
        for stale in work.iterdir():
            if stale.is_file():
                stale.unlink()
    work.mkdir(parents=True, exist_ok=True)
    list_path = work / "concat.txt"
    lines = []
    used_takes = []
    segments = segments_from_timeline(used, episode)
    for index, (item, segment) in enumerate(zip(used, segments)):
        sid = item.get("shot_id")
        try:
            picture, audio = resolve_segment_takes(prod, segment, episode)
            video_src = take_media_file(prod, picture)
            audio_src = take_media_file(prod, audio)
            used_takes.append(picture.take_id)
        except PermissionError:
            video_src = resolve_shot_media(prod, sid, episode)
            audio_src = video_src
        if ken_burns_blocked(video_src) or ken_burns_blocked(audio_src):
            raise PermissionError(f"{video_src.name} 是 Ken Burns 路径，不能进入成片")
        inn = float(item.get("in_sec", item.get("in_point") or 0) or 0)
        out = float(item.get("out_sec", item.get("out_point") or duration_for_shot(prod, sid, 4, episode)))
        audio_in = float(item.get("audio_in_sec", inn) or 0)
        audio_out = float(item.get("audio_out_sec", out) or out)
        clip = work / f"{index:03d}-{segment.segment_id}.mp4"
        _trim_segment_av(
            video_src=video_src,
            video_in=inn,
            video_out=out,
            audio_src=audio_src,
            audio_in=audio_in,
            audio_out=audio_out,
            dest=clip,
        )
        lines.append(f"file '{clip}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "assemble 失败")
    if ken_burns_blocked(dest):
        dest.unlink(missing_ok=True)
        raise PermissionError("拼接结果不能是 Ken Burns")
    cut["final_file"] = export_rel
    cut["status"] = "ready"
    cut["episode"] = episode_key(episode)
    write_artifact(prod, cut_name, cut)
    return {
        "ok": True,
        "output": export_rel,
        "stdout": proc.stdout,
        "used": [item.get("shot_id") for item in used],
        "takes": used_takes,
        "episode": episode_key(episode),
    }
