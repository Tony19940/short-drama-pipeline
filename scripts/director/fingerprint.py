"""One-shot production confirmations. Changing media bytes or the vendor request voids them."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from .gates import designed_end_frame, i2v_source, parent_still, require_fresh_gate, run_check
from .pipeline import episode_artifact_name, read_artifact, uses_pipeline
from .prompts import compile_h3_fields, compile_video_prompt, identity_refs, still_refs, video_mode
from .shot_repo import select_shots
from .store import exclusive_state_lock, load_approvals, save_approvals
from .vendor_request import (
    COMPILER_VERSION,
    VendorRequest,
    media_hash,
    task_kind_for_gen_mode,
    task_needs_first_frame,
    task_needs_last_frame,
    task_needs_refs,
    task_needs_source_video,
    vendor_request_from_package,
)

SNAPSHOT_DIR = ".pipeline/confirmed-requests"


def _shots(prod: Path, episode: Any = 1) -> list[dict]:
    from .shot_repo import list_shots

    return list_shots(prod, episode)


def _selected(prod: Path, shot_ids: Optional[list[str]], episode: Any = 1) -> list[dict]:
    return select_shots(prod, shot_ids, episode)


def _file_hash(prod: Path, rel: str) -> str:
    return media_hash(prod, rel)


def shot_spec(prod: Path, shot: dict, shots: list[dict]) -> dict:
    parent = parent_still(prod, shot, shots)
    source = i2v_source(prod, shot, shots)
    refs = still_refs(prod, shot)
    compiled = compile_video_prompt(shot, silent=True, refs=refs)
    fields = compile_h3_fields(shot, silent=True, refs=refs)
    mode = video_mode(shot, source.get("kind") or "designed_frame", refs)
    dest = f"05-shots/{shot['id']}.mp4"
    end = designed_end_frame(prod, shot)
    if not end["ok"]:
        raise PermissionError(end["reason"])
    media = {
        "parent": _file_hash(prod, parent.get("path") or ""),
        "source": _file_hash(prod, source.get("path") or ""),
        "frame": _file_hash(prod, shot.get("frame") or f"04-frames/{shot['id']}.jpg"),
        "end_frame": _file_hash(prod, end.get("path") or ""),
        "refs": {rel: _file_hash(prod, rel) for rel in refs},
    }
    return {
        "id": shot["id"],
        "parent": parent.get("path") or "",
        "source": source.get("path") or "",
        "source_kind": source.get("kind") or "",
        "refs": list(refs),
        "identity_refs": identity_refs(refs),
        "mode": mode,
        "dest": dest,
        "frame": shot.get("frame") or f"04-frames/{shot['id']}.jpg",
        "end_frame": end.get("path") or "",
        "compiled": compiled,
        "h3": fields,
        "media_hashes": media,
        "compiler_version": COMPILER_VERSION,
    }


def _pipeline_specs(prod: Path, shot_ids: Optional[list[str]], episode: Any = 1) -> list[dict]:
    selected = _selected(prod, shot_ids, episode)
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    frames = {
        item.get("shot_id"): item
        for item in (read_artifact(prod, episode_artifact_name("keyframes.json", episode)).get("keyframes") or [])
        if item.get("shot_id")
    }
    by_id = {item.get("shot_id"): item for item in (packages.get("packages") or packages.get("gen_packages") or [])}
    specs = []
    for shot in selected:
        sid = shot["id"]
        pkg = by_id.get(sid)
        if not pkg:
            raise ValueError(f"{sid} 没有生成包")
        request = vendor_request_from_package(prod, pkg, frames.get(sid) or {}, episode=episode)
        from .pipeline import episode_shot_dir

        specs.append({
            "id": sid,
            "vendor_request": request.to_dict(),
            "fingerprint": request.fingerprint(),
            "dest": f"{episode_shot_dir(episode)}/{sid}.mp4",
        })
    return specs


def confirmed_snapshot_rel(fingerprint: str) -> str:
    return f"{SNAPSHOT_DIR}/{str(fingerprint).strip()}.json"


def snapshot_canonical_payload(data: dict) -> dict:
    payload = {
        "compiler_version": str(data.get("compiler_version") or ""),
        "episode": str(data.get("episode") if data.get("episode") not in (None, "") else ""),
        "shot_ids": list(data.get("shot_ids") or []),
        "requests": list(data.get("requests") or []),
    }
    if data.get("shots"):
        payload["shots"] = list(data.get("shots") or [])
    return payload


def snapshot_batch(
    *,
    episode: Any,
    shot_ids: list[str],
    requests: Optional[list[dict]] = None,
    shots: Optional[list[dict]] = None,
    compiler_version: str = COMPILER_VERSION,
) -> dict:
    batch = {
        "compiler_version": compiler_version,
        "episode": str(episode if episode not in (None, "") else ""),
        "shot_ids": list(shot_ids),
        "requests": list(requests or []),
    }
    if shots:
        batch["shots"] = list(shots)
    return batch


def _legacy_shot_rows(specs: list[dict]) -> list[dict]:
    keys = ("id", "parent", "source", "refs", "mode", "dest", "compiled", "end_frame", "media_hashes")
    return [{key: item[key] for key in keys if key in item} for item in specs]


def _batch_from_specs(episode: Any, specs: list[dict]) -> dict:
    requests = [item.get("vendor_request") for item in specs if item.get("vendor_request")]
    return snapshot_batch(
        episode=episode,
        shot_ids=[item["id"] for item in specs],
        requests=requests,
        shots=None if requests else _legacy_shot_rows(specs),
    )


def snapshot_content_fingerprint(data: dict) -> str:
    raw = json.dumps(snapshot_canonical_payload(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def confirmed_media_path(prod: Path, digest: str) -> Path:
    digest = str(digest or "").strip()
    return Path(prod) / SNAPSHOT_DIR / "media" / digest[:2] / digest


def persist_confirmed_media(prod: Path, requests: list[dict]) -> None:
    for req in requests:
        if not isinstance(req, dict):
            continue
        hashes = req.get("media_hashes") or {}
        if not isinstance(hashes, dict):
            continue
        for rel, digest in hashes.items():
            digest = str(digest or "").strip()
            rel = str(rel or "").strip()
            if not digest or not rel:
                continue
            dest = confirmed_media_path(prod, digest)
            if dest.is_file():
                continue
            src = Path(prod) / rel
            if not src.is_file():
                raise PermissionError(f"cannot freeze {rel}")
            data = src.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise PermissionError(f"{rel} changed while writing snapshot")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)


def read_confirmed_media_bytes(prod: Path, rel: str, digest: str) -> bytes:
    digest = str(digest or "").strip()
    stored = confirmed_media_path(prod, digest) if digest else Path()
    if digest and stored.is_file():
        data = stored.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            return data
    src = Path(prod) / str(rel or "")
    if not src.is_file():
        raise RuntimeError(f"missing confirmed media {rel}")
    data = src.read_bytes()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"{rel} changed since confirm")
    return data


def write_confirmed_snapshot(
    prod: Path,
    fingerprint: str,
    *,
    episode: Any,
    shot_ids: list[str],
    requests: list[dict],
    extra: Optional[dict] = None,
) -> str:
    body = {
        "compiler_version": COMPILER_VERSION,
        "episode": str(episode if episode not in (None, "") else ""),
        "shot_ids": list(shot_ids),
        "requests": list(requests),
        "at": int(time.time()),
    }
    if extra:
        for key, value in extra.items():
            if key != "fingerprint":
                body[key] = value
    live = snapshot_content_fingerprint(body)
    if fingerprint and fingerprint != live:
        raise PermissionError("snapshot fingerprint does not match canonical payload")
    body["fingerprint"] = live
    persist_confirmed_media(prod, list(requests))
    rel = confirmed_snapshot_rel(live)
    dest = Path(prod) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return rel


def load_confirmed_snapshot(
    prod: Path,
    fingerprint_or_rel: str,
    *,
    expected_fingerprint: Optional[str] = None,
    expected_episode: Any = None,
    expected_shot_ids: Optional[list[str]] = None,
) -> dict:
    raw = str(fingerprint_or_rel or "").strip()
    if not raw:
        raise PermissionError("missing confirmed snapshot")
    path = Path(raw)
    if not path.is_absolute():
        rel = raw if raw.endswith(".json") or "/" in raw else confirmed_snapshot_rel(raw)
        path = Path(prod) / rel
    if not path.is_file():
        raise PermissionError(f"confirmed snapshot missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError(f"confirmed snapshot unreadable: {path}") from exc
    if not isinstance(data, dict) or not data.get("requests"):
        raise PermissionError("confirmed snapshot has no requests")
    if str(data.get("compiler_version") or "") != COMPILER_VERSION:
        raise PermissionError("snapshot compiler_version is missing or incompatible")
    live = snapshot_content_fingerprint(data)
    stored = str(data.get("fingerprint") or "")
    if stored != live:
        raise PermissionError("snapshot content does not match fingerprint")
    expected = str(expected_fingerprint or "").strip()
    if expected and expected != live:
        raise PermissionError("snapshot fingerprint does not match the job")
    if expected_episode not in (None, "") and str(data.get("episode")) != str(expected_episode):
        raise PermissionError("snapshot episode does not match the job")
    if expected_shot_ids is not None and list(data.get("shot_ids") or []) != list(expected_shot_ids):
        raise PermissionError("snapshot shot list does not match the job")
    return data


def snapshot_requests(data: dict) -> list[VendorRequest]:
    return [VendorRequest.from_dict(item) for item in (data.get("requests") or []) if isinstance(item, dict)]


def require_task_inputs(prod: Path, selected: list[dict], episode: Any = 1) -> None:
    """Gate inputs by task_kind. Extend/edit/reference do not invent a first frame."""
    from .pipeline import episode_artifact_name, episode_frame_dir, read_artifact, uses_pipeline

    if not uses_pipeline(prod):
        shots = _shots(prod, episode)
        for shot in selected:
            dest = prod / (shot.get("frame") or f"{episode_frame_dir(episode)}/{shot['id']}.jpg")
            if not dest.exists():
                raise PermissionError(f"{shot['id']} 还没有锁定首帧")
            source = i2v_source(prod, shot, shots)
            if not source["exists"]:
                raise PermissionError(f"{shot['id']} 缺 I2V 源：{source['reason']}")
        return
    pkg_data = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    packages = {
        item.get("shot_id"): item
        for item in (pkg_data.get("packages") or pkg_data.get("gen_packages") or [])
    }
    frames = {
        item.get("shot_id"): item
        for item in (read_artifact(prod, episode_artifact_name("keyframes.json", episode)).get("keyframes") or [])
        if item.get("shot_id")
    }
    for shot in selected:
        sid = shot["id"]
        pkg = packages.get(sid) or {}
        kf = frames.get(sid) or {}
        kind = task_kind_for_gen_mode(str(pkg.get("gen_mode") or "i2v_first"))
        if task_needs_first_frame(kind):
            rel = str(shot.get("frame") or kf.get("first_frame_file") or pkg.get("first_frame") or f"{episode_frame_dir(episode)}/{sid}.jpg")
            if not (Path(prod) / rel).exists():
                raise PermissionError(f"{sid} 还没有锁定首帧")
        if task_needs_last_frame(kind):
            last = str(kf.get("last_frame_file") or pkg.get("last_frame") or "")
            if not last or not (Path(prod) / last).exists():
                raise PermissionError(f"{sid} 缺尾帧")
        if task_needs_refs(kind):
            refs = [str(item).strip() for item in (pkg.get("refs") or []) if str(item).strip()]
            if not refs:
                raise PermissionError(f"{sid} reference 缺参考图")
            for rel in refs:
                if not (Path(prod) / rel).exists():
                    raise PermissionError(f"{sid} 缺参考 {rel}")
        if task_needs_source_video(kind):
            src = str(pkg.get("source_video") or pkg.get("reference_video") or kf.get("source_video") or "")
            if not src or not (Path(prod) / src).exists():
                raise PermissionError(f"{sid} {kind} 缺 source_video")


def fingerprint_for(prod: Path, shot_ids: Optional[list[str]] = None, episode: Any = 1) -> tuple[str, list[dict]]:
    if uses_pipeline(prod):
        specs = _pipeline_specs(prod, shot_ids, episode)
    else:
        shots = _shots(prod, episode)
        selected = _selected(prod, shot_ids, episode)
        specs = [shot_spec(prod, shot, shots) for shot in selected]
    return snapshot_content_fingerprint(_batch_from_specs(episode, specs)), specs


def prepare_render(
    prod: Path,
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode: Any = 1,
) -> dict:
    require_fresh_gate(prod, "C")
    from .pipeline import assert_keyframes_passed, assert_packages_confirmed, uses_pipeline
    if uses_pipeline(prod):
        require_fresh_gate(prod, "C2")
        assert_packages_confirmed(prod, episode)
        assert_keyframes_passed(prod, episode)
    check = run_check(prod)
    if not check["ok"]:
        raise PermissionError(check["stderr"] or check["stdout"] or "check_prod 未过，不能出视频")
    selected = _selected(prod, shot_ids, episode)
    require_task_inputs(prod, selected, episode)
    fingerprint, specs = fingerprint_for(prod, [shot["id"] for shot in selected], episode)
    batch = _batch_from_specs(episode, specs)
    snapshot = write_confirmed_snapshot(
        prod,
        fingerprint,
        episode=episode,
        shot_ids=batch["shot_ids"],
        requests=batch["requests"],
        extra={"shots": batch["shots"]} if batch.get("shots") else None,
    )
    with exclusive_state_lock(prod, "approvals"):
        approvals = load_approvals(prod)
        approvals["render"] = {
            "fingerprint": fingerprint,
            "shot_ids": [shot["id"] for shot in selected],
            "review_track": bool(review_track),
            "consumed": False,
            "episode": episode,
            "snapshot": snapshot,
            "at": int(time.time()),
        }
        save_approvals(prod, approvals)
    return {
        "ok": True,
        "fingerprint": fingerprint,
        "shot_ids": [shot["id"] for shot in selected],
        "count": len(specs),
        "review_track": bool(review_track),
        "shots": specs,
        "note": "改分镜、换父图、换图字节或失败重试都会作废这份确认。不扣积分。",
    }


def consume_render_fingerprint(
    prod: Path,
    fingerprint: Optional[str],
    shot_ids: Optional[list[str]] = None,
    review_track: bool = False,
    episode: Any = 1,
) -> dict:
    if not fingerprint:
        raise PermissionError("出片需要先 prepare 并确认指纹")
    with exclusive_state_lock(prod, "approvals"):
        live, _specs = fingerprint_for(prod, shot_ids, episode)
        if live != fingerprint:
            raise PermissionError("指纹已过期：分镜、父图、参考图或厂商请求已变，请重新 prepare")
        approvals = load_approvals(prod)
        rec = approvals.get("render") or {}
        if rec.get("fingerprint") != fingerprint:
            raise PermissionError("没有这份出片确认，请先 prepare")
        if rec.get("consumed"):
            raise PermissionError("这份确认已用过，失败重试必须重新 prepare")
        want = [shot["id"] for shot in _selected(prod, shot_ids, episode)]
        if rec.get("shot_ids") != want:
            raise PermissionError("确认的镜头和这次派出的不一致")
        rec["consumed"] = True
        rec["used_at"] = int(time.time())
        rec["review_track"] = bool(review_track)
        batch = _batch_from_specs(episode, _specs)
        rec["snapshot"] = write_confirmed_snapshot(
            prod,
            fingerprint,
            episode=episode,
            shot_ids=batch["shot_ids"],
            requests=batch["requests"],
            extra={"shots": batch["shots"]} if batch.get("shots") else None,
        )
        approvals["render"] = rec
        save_approvals(prod, approvals)
        return {
            "fingerprint": fingerprint,
            "snapshot": rec["snapshot"],
            "episode": rec.get("episode", episode),
            "shot_ids": list(rec.get("shot_ids") or want),
        }
