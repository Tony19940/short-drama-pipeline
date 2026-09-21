#!/usr/bin/env python3
"""6.2 for pipeline productions: gen_packages + locked keyframes -> Seedance clips.

Does not read or write 03-storyboard/shots.json. Designed 04-frames/*-last.jpg
stills are never overwritten with an extracted last frame.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import load_dotenv, productions_root, safe_under
from director.pipeline import (
    episode_artifact_name,
    episode_frame_dir,
    episode_label,
    episode_number,
    episode_shot_dir,
    packages_confirmed,
    read_artifact,
    raise_if,
    uses_pipeline,
    validate_keyframes,
    validate_packages,
)
from director.prompts import MAX_ZH_PROMPT_CHARS
from director.speech import DEFAULT_DIALOGUE_LANGUAGE, DEFAULT_SPEECH_MODE, SpeechLanguageError, check_dialogue_language
from director.vendor_request import (
    DurationOutOfRange,
    GEN_MODE_TO_TASK,
    UnsupportedTaskKind,
    VendorRequest,
    resolve_render_seconds,
    seedance_mode_for_task,
    task_kind_for_gen_mode,
    task_needs_first_frame,
    vendor_request_from_package,
)

TASK_TO_GEN = {value: key for key, value in GEN_MODE_TO_TASK.items()}
from director.video_fallback import render_seedance_or_h3_fallback
from video_backends.seedance_ark import SeedanceArk

SEEDANCE_MODE = {
    "i2v_first": "i2v",
    "flf2v": "flf",
}
FACE_TYPES = {"character", "costume_state"}
MAX_REFS = 4
ARCHIVE_SKIP_TOKENS = ("/smoke", "smoke-", "h3-staging", "animatic", "archive-")
ARCHIVE_DIRNAME = "archive-before-force"


def archive_existing_official(dest: Path, *, now: Optional[datetime] = None) -> Optional[Path]:
    """Copy an official 05-shots/SHxxx.mp4 aside before --force overwrite.

    Smoke, h3-staging, animatic, and files already inside an archive/ stay put.
    Sidecars like ``SHxxx.mp4.clip.json`` are copied next to the archived mp4.
    """
    if dest.suffix.lower() != ".mp4":
        return None
    if not dest.exists() or dest.stat().st_size <= 1024:
        return None
    posix = dest.as_posix().lower()
    if any(token in posix for token in ARCHIVE_SKIP_TOKENS):
        return None
    if dest.parent.name == ARCHIVE_DIRNAME:
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    archive_dir = dest.parent / ARCHIVE_DIRNAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"{dest.stem}-{stamp}{dest.suffix}"
    if archived.exists():
        archived = archive_dir / f"{dest.stem}-{stamp}-{os.getpid()}{dest.suffix}"
    shutil.copy2(dest, archived)
    for sidecar in dest.parent.glob(dest.name + ".*"):
        if not sidecar.is_file():
            continue
        extra = sidecar.name[len(dest.name) :]
        shutil.copy2(sidecar, archive_dir / f"{archived.name}{extra}")
    return archived


def _prod(path: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raw = (ROOT / raw).resolve()
    return raw


def _text(value) -> str:
    return str(value or "").strip()


def render_seconds_for_package(pkg: dict) -> int:
    """Legal Seedance/H3 seconds. Paper can be 1–3s; render bumps to model min. Over-max errors."""
    return resolve_render_seconds(pkg)


def handoff_markdown_name(episode) -> str:
    label = episode_label(episode)
    if not label:
        return f"HANDOFF-VIDEO-EP{episode_number(episode):02d}.md"
    return f"HANDOFF-VIDEO-{label.replace('ep', 'EP', 1)}.md"


def _rel_under_episode(rel: str, folder: str) -> bool:
    posix = _text(rel).replace("\\", "/")
    return bool(posix) and posix.startswith(folder.rstrip("/") + "/")


def _packages(prod: Path, episode: int = 1) -> list[dict]:
    data = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    return list(data.get("packages") or data.get("gen_packages") or [])


def _keyframes(prod: Path, episode: int = 1) -> dict[str, dict]:
    data = read_artifact(prod, episode_artifact_name("keyframes.json", episode))
    return {item.get("shot_id"): item for item in (data.get("keyframes") or []) if item.get("shot_id")}


def _assets(prod: Path) -> dict[str, dict]:
    data = read_artifact(prod, "assets.json")
    return {item.get("asset_id"): item for item in (data.get("assets") or []) if item.get("asset_id")}


def _shot_ids(table: dict) -> list[str]:
    return [_text(item.get("shot_id")) for item in (table.get("shots") or []) if _text(item.get("shot_id"))]


def _hardest(table: dict) -> list[str]:
    return [_text(item.get("shot_id")) for item in (table.get("shots") or []) if item.get("hardest")]


def identity_ref_paths(prod: Path, pkg: dict, assets: dict[str, dict], first: Path) -> list[Path]:
    refs: list[Path] = []
    seen: set[Path] = set()
    first_resolved = first.resolve()
    for asset_id in pkg.get("asset_refs") or []:
        item = assets.get(asset_id) or {}
        if item.get("type") not in FACE_TYPES:
            continue
        rel = _text(item.get("file"))
        if not rel:
            continue
        path = safe_under(prod, rel)
        if not path.exists() or path.resolve() == first_resolved:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        refs.append(path)
        if len(refs) >= MAX_REFS:
            break
    return refs


def seedance_mode(gen_mode: str) -> str:
    try:
        return seedance_mode_for_task(task_kind_for_gen_mode(gen_mode))
    except UnsupportedTaskKind as exc:
        raise SystemExit(str(exc)) from exc


def plan_shot(prod: Path, pkg: dict, frames: dict[str, dict], assets: dict[str, dict], episode=1) -> dict:
    sid = _text(pkg.get("shot_id"))
    kf = frames.get(sid) or {}
    qc = kf.get("qc") or {}
    frame_prefix = episode_frame_dir(episode)
    shot_prefix = episode_shot_dir(episode)
    gen_mode = _text(pkg.get("gen_mode"))
    plan = _text(pkg.get("keyframe_plan"))
    try:
        kind = task_kind_for_gen_mode(gen_mode or "i2v_first")
    except UnsupportedTaskKind:
        kind = ""
    first_rel = _text(kf.get("first_frame_file")) or _text(pkg.get("first_frame"))
    if not first_rel and task_needs_first_frame(kind):
        first_rel = f"{frame_prefix}/{sid}.jpg"
    last_rel = _text(kf.get("last_frame_file")) or _text(pkg.get("last_frame"))
    first = safe_under(prod, first_rel) if first_rel else None
    last = safe_under(prod, last_rel) if last_rel else None
    dest_rel = f"{shot_prefix}/{sid}.mp4"
    extracted_rel = f"{shot_prefix}/{sid}-last.jpg"
    errors: list[str] = []
    if not pkg.get("confirmed"):
        errors.append("package not confirmed")
    needs_first = task_needs_first_frame(kind) if kind else gen_mode not in {"video_extend", "edit", "r2v"}
    if needs_first and _text(qc.get("status")) != "pass":
        errors.append("keyframe not passed")
    if first_rel and not _rel_under_episode(first_rel, frame_prefix):
        errors.append(f"first_frame outside episode folder: {first_rel}")
    if last_rel and not _rel_under_episode(last_rel, frame_prefix):
        errors.append(f"last_frame outside episode folder: {last_rel}")
    source_rel = _text(pkg.get("source_video") or pkg.get("reference_video") or kf.get("source_video"))
    if gen_mode in {"video_extend", "edit"} and not source_rel:
        errors.append("extend/edit missing source_video")
    elif source_rel and not safe_under(prod, source_rel).exists():
        errors.append(f"missing source video {source_rel}")
    pkg_refs = [_text(item) for item in (pkg.get("refs") or []) if _text(item)]
    if gen_mode == "r2v" and not pkg_refs:
        errors.append("reference missing refs")
    for rel in pkg_refs:
        if not safe_under(prod, rel).exists():
            errors.append(f"missing reference {rel}")
    if needs_first and (first is None or not first.exists()):
        errors.append(f"missing first frame {first_rel}")
    wants_last = gen_mode == "flf2v" or plan == "first_last"
    if wants_last:
        if not last_rel:
            errors.append("flf2v / first_last missing last_frame_file")
        elif last is None or not last.exists():
            errors.append(f"missing last frame {last_rel}")
    elif last_rel:
        # first-only shots must not send a leftover designed last (including 29-shot 04-frames/).
        last_rel = ""
        last = None
    prompt = _text(pkg.get("motion_prompt"))
    if not prompt:
        errors.append("missing motion_prompt")
    speech_mode = _text(pkg.get("speech_mode")) or DEFAULT_SPEECH_MODE
    dialogue_language = _text(pkg.get("dialogue_language")) or DEFAULT_DIALOGUE_LANGUAGE
    lines = [_text(item) for item in (pkg.get("dialogue_lines") or []) if _text(item)]
    if not lines and _text(pkg.get("dialogue_line")):
        lines = [_text(pkg.get("dialogue_line"))]
    try:
        # first_frame path: Khmer needs reference_audio, which Ark rejects next to first_frame.
        check_dialogue_language(dialogue_language, speech_mode=speech_mode, shot_id=sid)
    except SpeechLanguageError as exc:
        errors.append(str(exc))
    native_speech = speech_mode == "seedance_native" and bool(lines)
    seconds = 0
    try:
        seconds = render_seconds_for_package(pkg)
    except DurationOutOfRange as exc:
        errors.append(str(exc))
    mode = ""
    request = None
    try:
        mode = seedance_mode(gen_mode)
        request = vendor_request_from_package(
            prod,
            {
                **pkg,
                "first_frame": first_rel,
                "last_frame": last_rel if wants_last else "",
                "source_video": source_rel,
                "refs": pkg_refs,
            },
            kf,
            episode=episode,
            refs=pkg_refs,
        )
    except (UnsupportedTaskKind, SystemExit, ValueError) as exc:
        errors.append(str(exc))
    refs = identity_ref_paths(prod, pkg, assets, first) if first is not None and first.exists() else []
    vendor_refs = list(request.refs) if request is not None else pkg_refs
    dest_path = prod / dest_rel
    request_hash = request.fingerprint() if request is not None else ""
    reusable = bool(request_hash) and SeedanceArk.clip_matches_request(dest_path, request_hash)
    return {
        "shot_id": sid,
        "gen_mode": gen_mode,
        "seedance_mode": mode,
        "vendor_request": request.to_dict() if request is not None else None,
        "keyframe_plan": plan,
        "prompt": prompt,
        "prompt_chars": len(prompt),
        "duration_sec": seconds,
        "paper_duration_sec": pkg.get("paper_duration_sec"),
        "render_duration_sec": seconds,
        "first_frame": first_rel,
        "last_frame": last_rel if wants_last else "",
        "source_video": source_rel,
        "request_hash": request_hash,
        "use_last_frame": bool(wants_last and last_rel),
        "refs": vendor_refs or [str(path.relative_to(prod)) for path in refs],
        "allow_h3_fallback": bool(request.allow_h3_fallback) if request is not None else False,
        "dest": dest_rel,
        "extracted_last": extracted_rel,
        "overwrite_designed_last": False,
        "hardest": False,
        "generate_audio": bool(pkg.get("generate_audio", True)),
        "speech_mode": speech_mode,
        "dialogue_language": dialogue_language,
        "dialogue_lines": lines,
        "native_speech": native_speech,
        # H3 fallback has no native dialogue: a face-blocked shot with lines loses them.
        "loses_lines_on_h3": native_speech,
        "errors": errors,
        "ok": not errors,
        "exists": dest_path.exists() and dest_path.stat().st_size > 1024,
        "reusable": reusable,
    }


def build_plan(prod: Path, only: Optional[list[str]] = None, episode=1) -> dict:
    if not uses_pipeline(prod):
        raise SystemExit("这个项目不是 pipeline 岗，不要走 render_seedance_packages.py")
    packages = _packages(prod, episode)
    frames = _keyframes(prod, episode)
    assets = _assets(prod)
    table_name = episode_artifact_name("shot_list.json", episode)
    pkg_name = episode_artifact_name("gen_packages.json", episode)
    spec_name = episode_artifact_name("shot_specs.json", episode)
    kf_name = episode_artifact_name("keyframes.json", episode)
    table = read_artifact(prod, table_name)
    pkg_errors = validate_packages(read_artifact(prod, pkg_name), read_artifact(prod, "assets.json"), read_artifact(prod, spec_name))
    if pkg_errors:
        raise SystemExit("生成包未过校验：" + pkg_errors[0])
    if not packages_confirmed(read_artifact(prod, pkg_name)):
        raise SystemExit("生成包还没 confirmed=true")
    raise_if(
        validate_keyframes(
            read_artifact(prod, kf_name),
            packages=read_artifact(prod, pkg_name),
            specs=read_artifact(prod, spec_name),
            table=table,
            prod=prod,
        )
    )
    order = _shot_ids(table) or [_text(item.get("shot_id")) for item in packages]
    by_id = {_text(item.get("shot_id")): item for item in packages}
    want = set(only or [])
    hardest = set(_hardest(table))
    shots = []
    for sid in order:
        if want and sid not in want:
            continue
        pkg = by_id.get(sid)
        if not pkg:
            shots.append({"shot_id": sid, "ok": False, "errors": ["missing gen_package"]})
            continue
        item = plan_shot(prod, pkg, frames, assets, episode=episode)
        item["hardest"] = sid in hardest
        shots.append(item)
    missing = sorted(want - {item["shot_id"] for item in shots}) if want else []
    if missing:
        raise SystemExit("没有这些镜头：" + ", ".join(missing))
    dest_dir = episode_shot_dir(episode)
    return {
        "prod": str(prod.relative_to(ROOT)) if ROOT in prod.parents or prod == ROOT else str(prod),
        "episode": episode_label(episode) or episode_number(episode),
        "episode_no": episode_number(episode),
        "episode_label": episode_label(episode),
        "dest_dir": dest_dir,
        "shots": shots,
        "count": len(shots),
        "ok_count": sum(1 for item in shots if item.get("ok")),
        "first_last_count": sum(1 for item in shots if item.get("use_last_frame")),
        "missing_first": sum(1 for item in shots if any("missing first" in err for err in (item.get("errors") or []))),
        "hardest": [item["shot_id"] for item in shots if item.get("hardest")],
        "native_speech_count": sum(1 for item in shots if item.get("native_speech")),
        "h3_line_loss": [item["shot_id"] for item in shots if item.get("loses_lines_on_h3")],
        "max_prompt_chars": max((int(item.get("prompt_chars") or 0) for item in shots), default=0),
        "writes_shots_json": False,
        "overwrites_designed_last": False,
        "overwrites_unsuffixed_shots": dest_dir == "05-shots",
    }


def _extract_last(video: Path, dest: Path) -> None:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    # -0.05 can miss the last packet on short H3-scaled clips (ffmpeg 234).
    for seek in ("-0.05", "-0.5", "-1"):
        rc = subprocess.call(
            ["ffmpeg", "-y", "-sseof", seek, "-i", str(video), "-frames:v", "1", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if rc == 0 and dest.exists() and dest.stat().st_size > 0:
            return
    print(f"  warn: could not extract last frame from {video.name}; official clip kept", flush=True)


def plan_from_snapshot(prod: Path, snapshot_rel: str, only: Optional[list[str]] = None) -> dict:
    """Paid path: execute the confirmed requests. Do not recompile packages."""
    from director.fingerprint import load_confirmed_snapshot, snapshot_requests
    from director.vendor_request import media_hash

    snap = load_confirmed_snapshot(prod, snapshot_rel)
    episode = snap.get("episode") or 1
    dest_dir = episode_shot_dir(episode)
    want = set(only or [])
    shots = []
    for request in snapshot_requests(snap):
        if want and request.shot_id not in want:
            continue
        errors: list[str] = []
        for rel, digest in request.media_hash_map().items():
            live = media_hash(prod, rel)
            if digest and live != digest:
                errors.append(f"{rel} changed since confirm")
            if rel and not (prod / rel).exists():
                errors.append(f"missing {rel}")
        dest_rel = f"{dest_dir}/{request.shot_id}.mp4"
        item = {
            "shot_id": request.shot_id,
            "gen_mode": TASK_TO_GEN.get(request.task_kind, request.task_kind),
            "seedance_mode": request.seedance_mode(),
            "vendor_request": request.to_dict(),
            "prompt": request.prompt,
            "prompt_chars": len(request.prompt),
            "duration_sec": request.duration_sec,
            "first_frame": request.first_frame,
            "last_frame": request.last_frame,
            "source_video": request.source_video,
            "request_hash": request.fingerprint(),
            "use_last_frame": bool(request.last_frame),
            "refs": list(request.refs),
            "dest": dest_rel,
            "extracted_last": f"{dest_dir}/{request.shot_id}-last.jpg",
            "overwrite_designed_last": False,
            "hardest": False,
            "generate_audio": request.generate_audio,
            "allow_h3_fallback": request.allow_h3_fallback,
            "errors": errors,
            "ok": not errors,
            "exists": (prod / dest_rel).exists() and (prod / dest_rel).stat().st_size > 1024,
            "reusable": SeedanceArk.clip_matches_request(prod / dest_rel, request.fingerprint()),
        }
        shots.append(item)
    missing = sorted(want - {item["shot_id"] for item in shots}) if want else []
    if missing:
        raise SystemExit("快照里没有这些镜头：" + ", ".join(missing))
    return {
        "prod": str(prod),
        "episode": episode,
        "episode_no": episode_number(episode),
        "episode_label": episode_label(episode),
        "dest_dir": dest_dir,
        "from_snapshot": snapshot_rel,
        "shots": shots,
        "count": len(shots),
        "ok_count": sum(1 for item in shots if item.get("ok")),
        "first_last_count": sum(1 for item in shots if item.get("use_last_frame")),
        "missing_first": 0,
        "hardest": [],
        "native_speech_count": 0,
        "h3_line_loss": [],
        "max_prompt_chars": max((int(item.get("prompt_chars") or 0) for item in shots), default=0),
        "writes_shots_json": False,
        "overwrites_designed_last": False,
        "overwrites_unsuffixed_shots": dest_dir == "05-shots",
    }


def _backend_for_item(item: dict) -> SeedanceArk:
    req = item.get("vendor_request") or {}
    if req.get("model") and req.get("profile_id"):
        from director.video_profiles import get_profile

        profile = get_profile(req["profile_id"])
        return SeedanceArk(
            model=req["model"],
            resolution=req.get("resolution") or "720p",
            min_duration=int(profile.get("min_shot_sec") or 4),
            max_duration=int(profile.get("max_shot_sec") or 15),
            generate_audio=bool(req.get("generate_audio", True)),
        )
    return SeedanceArk()


def render_plan(prod: Path, plan: dict, *, skip_existing: bool = True) -> None:
    load_dotenv()
    out_dir = prod / (plan.get("dest_dir") or episode_shot_dir(plan.get("episode") or 1))
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in plan["shots"]:
        sid = item["shot_id"]
        if not item.get("ok"):
            raise SystemExit(f"{sid} 还不能出片：" + "; ".join(item.get("errors") or []))
        dest = prod / item["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = VendorRequest.from_dict(item["vendor_request"]) if item.get("vendor_request") else None
        if skip_existing and request is not None and SeedanceArk.clip_matches_request(dest, request.fingerprint()):
            print(f"  {sid} reusable {item['dest']}, skip")
            continue
        if skip_existing and item.get("exists") and request is None:
            raise SystemExit(f"{sid} existing clip has no confirmed request; refuse to skip")
        if not skip_existing:
            archived = archive_existing_official(dest)
            if archived:
                print(f"  archived existing {dest.name} -> {archived}", flush=True)
        image = safe_under(prod, request.first_frame if request else item.get("first_frame")) if (request and request.first_frame) or item.get("first_frame") else dest
        last = None
        if request and request.last_frame:
            last = safe_under(prod, request.last_frame)
        elif item.get("use_last_frame") and item.get("last_frame"):
            last = safe_under(prod, item["last_frame"])
        source = None
        if request and request.source_video:
            source = safe_under(prod, request.source_video)
        elif item.get("source_video"):
            source = safe_under(prod, item["source_video"])
        refs = [safe_under(prod, rel) for rel in ((request.refs if request else item.get("refs")) or []) if rel]
        backend = _backend_for_item(item)
        allow_h3 = bool(item.get("force_h3_fallback") or item.get("allow_h3_fallback") or (request and request.allow_h3_fallback))
        if item.get("force_h3_fallback"):
            from director.video_fallback import official_h3_fallback

            record = official_h3_fallback(
                image,
                request.prompt if request else item["prompt"],
                int(request.duration_sec if request else item["duration_sec"]),
                dest,
                last_frame=last,
                mode=request.seedance_mode() if request else item["seedance_mode"],
                force=not skip_existing,
            )
        else:
            record = render_seedance_or_h3_fallback(
                backend,
                image,
                request.prompt if request else item["prompt"],
                int(request.duration_sec if request else item["duration_sec"]),
                dest,
                refs=refs,
                mode=request.seedance_mode() if request else item["seedance_mode"],
                last_frame=last,
                force=not skip_existing,
                generate_audio=request.generate_audio if request else item.get("generate_audio", True),
                source_video=source,
                allow_h3_fallback=allow_h3,
                request=request,
                request_hash=request.fingerprint() if request else str(item.get("request_hash") or ""),
                ratio=request.submit_ratio if request else None,
                watermark=request.watermark if request else None,
                prod=prod,
            )
        item["clip"] = record
        try:
            from director.takes import persist_take, take_from_render

            persist_take(
                prod,
                take_from_render(
                    shot_id=sid,
                    dest=dest,
                    request_hash=str(item.get("request_hash") or ""),
                    episode_id=str(plan.get("episode_label") or ""),
                    qc={"backend": (record or {}).get("backend")},
                ),
            )
        except OSError:
            pass
        extracted = prod / item["extracted_last"]
        _extract_last(dest, extracted)
        print(f"  extracted last {extracted.relative_to(prod)} (designed still untouched)")


def write_manifest(prod: Path, plan: dict, *, force: bool = False) -> Path:
    episode = plan.get("episode_label") or plan.get("episode") or 1
    name = episode_artifact_name("seedance_render_plan.json", episode)
    dest = prod / ".pipeline" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = dict(plan)
    body["status"] = "dry-run"
    body["force"] = bool(force)
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def write_markdown(prod: Path, plan: dict, *, force: bool = False) -> Path:
    episode = plan.get("episode_label") or plan.get("episode") or 1
    dest = prod / "03-storyboard" / handoff_markdown_name(episode)
    rel_prod = plan.get("prod") or str(prod)
    dest_dir = plan.get("dest_dir") or episode_shot_dir(episode)
    ep_flag = episode_label(episode) or str(episode_number(episode))
    cmd = (
        "python3 scripts/render_seedance_packages.py \\\n"
        f"  --prod {rel_prod} \\\n"
        f"  --episode {ep_flag}"
    )
    title_ep = handoff_markdown_name(episode).replace("HANDOFF-VIDEO-", "").replace(".md", "")
    title = f"# {title_ep} 6.2 出片准备（Seedance 2.0 Mini 720p）"
    native_count = plan.get("native_speech_count") or 0
    loss = plan.get("h3_line_loss") or []
    loss_ids = "、".join(loss) if loss else "无"
    prompt_limit = MAX_ZH_PROMPT_CHARS
    lines = [
        title,
        "",
        "本文件是正式出片前的交接，不是成片。**不要写 `shots.json`。**",
        "",
        "## 一键出片",
        "",
        "会提交 Seedance。先 `--dry-run` 核对 67 镜、0 缺帧、dest 在分集目录。",
        "",
        "```bash",
        "set -a && source .env && set +a",
        "export ARK_API_KEY=你的方舟密钥",
        "export ARK_SEEDANCE_MODEL=doubao-seedance-2-0-mini-260615   # 或控制台接入点",
        "export ARK_RESOLUTION=720p",
        "export MINIMAX_API_KEY=人脸拦截才用的官方 H3 密钥   # 缺了则该镜 fail：face-blocked, no H3 key",
        cmd,
        "```",
        "",
        "核对不发任务：同一条命令加 `--dry-run`。只重跑一镜加 `--only SH001`。",
        "已知该镜已被脸拦、跳过 Seedance：加 `--h3-fallback`（必须带 `--only`，禁止整集倒给 H3）。",
        f"抽出的尾帧写到 `{dest_dir}/SHxxx-last.jpg`，不覆盖 `04-frames/` 设计尾帧。",
        "",
        "## 范围",
        "",
        f"- 镜头数：{plan['count']}",
        f"- 可派：{plan['ok_count']}",
        f"- 首尾帧（flf / first_last）：{plan.get('first_last_count') if plan.get('first_last_count') is not None else '—'}",
        f"- 成片目录：`{dest_dir}/SHxxx.mp4`（新建分集夹，不覆盖 `05-shots/SH001.mp4`–`SH029.mp4`）",
        f"- 最难：{', '.join(plan['hardest']) or '—'}",
        "- 模型 / 分辨率：Seedance 2.0 Mini **720p**（`1280×720`）。只在 create 被判人脸拦截（`PrivacyInformation`）时，这一镜改走官方 MiniMax-H3 768p，本机 ffmpeg 缩到 1280×720。配额 / 超时 / 风控词 / poll 失败不 fallback。",
        "- 秒数：纸面 `paper_duration_sec` 可短于 4（开场 1s、反应 2s）。提交用 `render_duration_sec`（不足 4 秒抬到模型下限）。成片按纸面 2–4 秒裁，assemble 是另一次 PM 指令。",
        f"- 声音：**Seedance 原声中文唇同步**（`speech_mode=seedance_native`，`dialogue_language=zh`，`generate_audio=true`）。台词以引号原句写进提示词的 `audio_block`，说话人带 `voice_card`，其余在画角色嘴闭着；无音乐、无字幕。有原声对白的镜：{native_count}（下表「原声对白」列 ★）。**H3 fallback 不会有原声对白**：★ 镜若被脸拦改走 H3，对白会丢，得后期补配——{loss_ids}。高棉语不能原生口播（`km` 走 reference_audio，与 first_frame 互斥），本轮不选。",
        "- 旧声音资产：旧 `07-dubbing/sfx/ep01-sfx.m4a` 是 29 镜 191s，对不上 67 镜 v2；旧 SRT 也没重映射，不要叠。新 SFX 床 / SRT 是成片后另一次 PM 指令。",
        f"- 提示词：中文 ≤{prompt_limit} 字软上限（本集最长 {plan.get('max_prompt_chars') or '—'} 字）。每镜前缀同场一致的 GEO 空间锁，动作从 0.0s 起就在动，只写正向句。",
        "- **不要**对无后缀 `05-shots/SH*.mp4` 用 `--force`。`--episode 1` 仍指向 29 镜锁画。本命令必须带 `--episode ep01-v2`。",
        "- 成片后的 assemble / 剪辑 / 新 SFX 床是另一次 PM 指令。本命令只落到分集目录。",
        "",
        "| 镜 | 模式 | 渲秒 | 纸面秒 | 首帧 | 设计尾帧 | 身份参考 | 原声对白 | 最难 | 状态 |",
        "|---|---|---:|---:|---|---|---|---|---|---|",
    ]
    for item in plan["shots"]:
        refs = ", ".join(f"`{rel}`" for rel in item.get("refs") or []) or "—"
        last = item.get("last_frame") or "—"
        status = "可派" if item.get("ok") else "; ".join(item.get("errors") or ["blocked"])
        if item.get("exists"):
            status = "已有 mp4，--force 将先归档再覆盖" if force else "已有 mp4，将跳过"
        paper = item.get("paper_duration_sec")
        paper_s = "—" if paper in (None, "") else paper
        spoken = "★ " + " / ".join(item.get("dialogue_lines") or []) if item.get("native_speech") else "—"
        lines.append(
            f"| {item['shot_id']} | {item.get('gen_mode')}→{item.get('seedance_mode')} | {item.get('duration_sec')} | {paper_s} | `{item.get('first_frame')}` | `{last}` | {refs} | {spoken} | {'是' if item.get('hardest') else ''} | {status} |"
        )
    lines.extend(
        [
            "",
            "flf 镜只交首尾帧：Ark 拒 last_frame 和 reference_image 混用。身份参考只给 i2v 镜，且正式出片不上传护照图（人脸拦）。",
            "首帧 = 动作起点：可以已经起手，结果不在首帧里；motion 从 0.0s 就在动（`action_timing` 两拍：0.0–1.5s 起手 / 1.5s–落幅，气还没平）。",
            "",
            "## 剩下的 blocker",
            "",
            "- 帧：无。67 首帧 + 21 尾帧都在 `04-frames/ep01-v2/`，包不引用无后缀 `04-frames/SH*-last.jpg`。",
            "- 出片本身：等 PM 跑上面那条命令。本交接没有提交 Ark / H3。",
            "- 原声对白：靠 Seedance 一次出对；★ 镜被脸拦走 H3 就没有对白，要另补配音。",
            "- 成片后：assemble、新 SFX、SRT 重映射都还没做，需要另下指令。",
            "",
        ]
    )
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="已有 mp4 也重跑")
    parser.add_argument(
        "--h3-fallback",
        action="store_true",
        help="skip Seedance; official MiniMax-H3 + local scale to 1280x720 for --only shots",
    )
    parser.add_argument(
        "--episode",
        default="1",
        help="集数或标签：1、2、ep01-v2。标签成片落到 05-shots/<label>/，不覆盖无后缀 05-shots/",
    )
    parser.add_argument(
        "--from-snapshot",
        default="",
        help="confirmed request snapshot (.pipeline/confirmed-requests/<hash>.json). Worker must pass this.",
    )
    args = parser.parse_args()
    prod = _prod(args.prod)
    if not prod.is_dir():
        raise SystemExit(f"没有这个项目：{prod}")
    if args.from_snapshot:
        plan = plan_from_snapshot(prod, args.from_snapshot, args.only)
    else:
        plan = build_plan(prod, args.only, episode=args.episode)
    summary_keys = (
        "prod",
        "episode",
        "dest_dir",
        "count",
        "ok_count",
        "first_last_count",
        "missing_first",
        "hardest",
        "native_speech_count",
        "h3_line_loss",
        "max_prompt_chars",
        "writes_shots_json",
        "overwrites_designed_last",
        "overwrites_unsuffixed_shots",
    )
    if not args.only:
        manifest = write_manifest(prod, plan, force=args.force)
        handoff = write_markdown(prod, plan, force=args.force)
        print(json.dumps({k: plan[k] for k in summary_keys}, ensure_ascii=False, indent=2))
        print(f"wrote {manifest.relative_to(ROOT)}")
        print(f"wrote {handoff.relative_to(ROOT)}")
    else:
        print(json.dumps({k: plan[k] for k in summary_keys}, ensure_ascii=False, indent=2))
        print("only=" + ",".join(args.only) + "; left full seedance_render_plan / HANDOFF-VIDEO alone")
    blocked = [item for item in plan["shots"] if not item.get("ok")]
    if blocked:
        raise SystemExit("还不能出片：" + ", ".join(item["shot_id"] + "(" + ";".join(item["errors"]) + ")" for item in blocked))
    if args.dry_run:
        print("dry-run only; no Ark task submitted")
        return
    if args.h3_fallback:
        if not args.only:
            raise SystemExit("--h3-fallback needs --only SHxxx (do not dump a whole episode onto H3)")
        for item in plan["shots"]:
            item["force_h3_fallback"] = True
    render_plan(prod, plan, skip_existing=not args.force)


if __name__ == "__main__":
    main()
