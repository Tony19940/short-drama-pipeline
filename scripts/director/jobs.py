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

from .gates import i2v_source, ken_burns_blocked, require_fresh_gate, run_check
from .paths import ROOT
from .production import load_json
from .store import load_jobs, save_jobs


def gpu_configured() -> bool:
    return video_ready()


def seedance_configured() -> bool:
    return bool(os.environ.get("ARK_API_KEY", "").strip())


def video_ready() -> bool:
    return bool(os.environ.get("LOCAL_H3_BASE", "").strip()) or seedance_configured()


def default_render_backend() -> str:
    if os.environ.get("DIRECTOR_VIDEO_BACKEND", "").strip():
        return os.environ["DIRECTOR_VIDEO_BACKEND"].strip()
    if seedance_configured():
        return "seedance"
    if os.environ.get("LOCAL_H3_BASE", "").strip():
        return "local"
    return ""


def _shots(prod: Path) -> list[dict]:
    return list(load_json(prod, "03-storyboard/shots.json", {"shots": []}).get("shots") or [])


def _append_job(prod: Path, job: dict) -> dict:
    data = load_jobs(prod)
    data.setdefault("jobs", [])
    data["jobs"].insert(0, job)
    save_jobs(prod, data)
    return job


def _update_job(prod: Path, job_id: str, **fields) -> dict:
    data = load_jobs(prod)
    for job in data.get("jobs") or []:
        if job.get("id") == job_id:
            job.update(fields)
            job["updated_at"] = int(time.time())
            save_jobs(prod, data)
            return job
    raise FileNotFoundError(job_id)


def enqueue_render(prod: Path, shot_ids: Optional[list[str]] = None, review_track: bool = False) -> dict:
    return enqueue_render_confirmed(prod, None, shot_ids, review_track)


def enqueue_render_confirmed(
    prod: Path,
    fingerprint: Optional[str] = None,
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
) -> dict:
    require_fresh_gate(prod, "C")
    from .pipeline import assert_clips_passed, assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod)
        assert_keyframes_passed(prod)
    check = run_check(prod)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    shots = _shots(prod)
    want = set(shot_ids or [])
    selected = [shot for shot in shots if not want or shot["id"] in want]
    if not selected:
        raise ValueError("没有可出的镜头")
    for shot in selected:
        dest = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
        if not dest.exists():
            raise PermissionError(f"{shot['id']} 还没有锁定首帧")
        source = i2v_source(prod, shot, shots)
        if not source["exists"]:
            raise PermissionError(f"{shot['id']} 缺 I2V 源：{source['reason']}")
    from .fingerprint import consume_render_fingerprint

    used = consume_render_fingerprint(prod, fingerprint, [shot["id"] for shot in selected], review_track)
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "kind": "render",
        "status": "queued",
        "shot_ids": [shot["id"] for shot in selected],
        "review_track": review_track,
        "gpu": gpu_configured(),
        "backend": default_render_backend() or None,
        "fingerprint": used,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "log": [],
        "error": None,
        "outputs": [],
    }
    if not video_ready():
        job["log"].append("未配置 ARK_API_KEY 或 LOCAL_H3_BASE，任务停在 queued，不假装成功。")
        return _append_job(prod, job)
    _append_job(prod, job)
    thread = threading.Thread(target=_run_render, args=(prod, job["id"]), daemon=True)
    thread.start()
    return job


def enqueue_review(prod: Path, shot_ids: Optional[list[str]] = None) -> dict:
    shots = _shots(prod)
    want = set(shot_ids or [])
    selected = [shot for shot in shots if not want or shot["id"] in want]
    missing = [shot["id"] for shot in selected if not (prod / "05-shots" / f"{shot['id']}.mp4").exists()]
    if missing:
        raise PermissionError("缺单镜视频：" + ", ".join(missing))
    for shot in selected:
        video = prod / "05-shots" / f"{shot['id']}.mp4"
        if ken_burns_blocked(video):
            raise PermissionError(f"{video.name} 是 Ken Burns 路径，不能进审片")
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "kind": "review",
        "status": "queued",
        "shot_ids": [shot["id"] for shot in selected],
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
        outputs = []
        for shot_id in job.get("shot_ids") or []:
            video = prod / "05-shots" / f"{shot_id}.mp4"
            last = prod / "04-frames" / f"{shot_id}-last.jpg"
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
                outputs.append(f"05-shots/{shot_id}.mp4")
            if last.exists():
                outputs.append(f"04-frames/{shot_id}-last.jpg")
        _update_job(prod, job_id, status="ready", log=[log[-2000:]], outputs=outputs, error=None)
    except Exception as exc:
        _update_job(prod, job_id, status="failed", error=str(exc))


def _run_review(prod: Path, job_id: str) -> None:
    _update_job(prod, job_id, status="running")
    data = load_jobs(prod)
    job = next(item for item in data["jobs"] if item["id"] == job_id)
    out = prod / "06-export" / ("preview-vo.mp4" if not job.get("shot_ids") else "preview-partial-vo.mp4")
    if len(job.get("shot_ids") or []) == len(_shots(prod)):
        out = prod / "06-export" / "preview-vo.mp4"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "mix_review_track.py"),
        "--prod",
        str(prod),
        "--out",
        str(out),
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


def assemble_episode(prod: Path) -> dict:
    from .pipeline import (
        assert_clips_passed,
        default_cut_from_specs,
        duration_for_shot,
        read_artifact,
        uses_pipeline,
        validate_cut,
        write_artifact,
    )

    if uses_pipeline(prod):
        assert_clips_passed(prod)
    shots = _shots(prod)
    cut = read_artifact(prod, "cut.json")
    timeline = list(cut.get("timeline") or [])
    if not timeline:
        cut = default_cut_from_specs(prod, [shot["id"] for shot in shots])
        timeline = list(cut.get("timeline") or [])
        write_artifact(prod, "cut.json", cut)
    errors = validate_cut(cut) if cut else []
    if errors:
        raise PermissionError(errors[0])
    used = [item for item in timeline if item.get("used", True)]
    if not used:
        raise PermissionError("时间线没有采用任何镜头")
    shot_dir = prod / "05-shots"
    if shot_dir.exists():
        for path in shot_dir.iterdir():
            if path.is_file() and ken_burns_blocked(path):
                raise PermissionError(f"{path.name} 是 Ken Burns 路径，不能进入成片")
    missing = []
    for item in used:
        sid = item.get("shot_id")
        video = prod / "05-shots" / f"{sid}.mp4"
        if not video.exists():
            missing.append(sid)
        elif ken_burns_blocked(video):
            raise PermissionError(f"{video.name} 是 Ken Burns 路径，不能进入成片")
    if missing:
        raise PermissionError("缺单镜视频：" + ", ".join(missing))
    dest = prod / "06-export" / "ep01.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and ken_burns_blocked(dest):
        dest.unlink()
    work = prod / ".director" / "cut-work"
    work.mkdir(parents=True, exist_ok=True)
    list_path = work / "concat.txt"
    lines = []
    for item in used:
        sid = item["shot_id"]
        src = prod / "05-shots" / f"{sid}.mp4"
        inn = float(item.get("in_point") or 0)
        out = float(item.get("out_point") or duration_for_shot(prod, sid, 4))
        duration = max(0.1, out - inn)
        clip = work / f"{sid}.mp4"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{inn:.3f}", "-i", str(src),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "160k",
            str(clip),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or f"{sid} 修剪失败")
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
    cut["final_file"] = "06-export/ep01.mp4"
    cut["status"] = "ready"
    write_artifact(prod, "cut.json", cut)
    return {"ok": True, "output": "06-export/ep01.mp4", "stdout": proc.stdout, "used": [item.get("shot_id") for item in used]}
