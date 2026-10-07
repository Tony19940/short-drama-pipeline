"""Key story events and actual sequence reviews, bound to media and edit bytes.

An event record is a reviewer observation, not a fact inferred from a prompt.
Mechanical checks protect observed intervals; audience comprehension still
requires a review of the resulting sequence. Normal ellipses and intentional
uncertainty are allowed by the sequence contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def media_path(prod: Path, rel: str) -> Path:
    if not rel or Path(rel).is_absolute():
        raise ValueError("media must be a production-relative path")
    path = (Path(prod) / rel).resolve()
    if not path.is_relative_to(Path(prod).resolve()):
        raise ValueError("media path escapes production")
    return path


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("time/speed must be finite")
    return result


def contract_errors(contract: dict, shot_ids: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["sequence contract must be an object"]
    if contract.get("schema") != "narrative-events-v1":
        errors.append("events schema must be narrative-events-v1")
    sequences = contract.get("sequences") or []
    if not isinstance(sequences, list) or any(not isinstance(s, dict) for s in sequences):
        return ["sequences must be a list of objects"]
    if any(not isinstance(s.get("sequence_id"), str) for s in sequences):
        return ["sequence_id must be a string"]
    if not sequences:
        errors.append("sequence contract is empty")
    sequence_ids: set[str] = set()
    known = set(shot_ids or [])
    for item in sequences:
        sid = str(item.get("sequence_id") or "")
        if not sid or sid in sequence_ids:
            errors.append("sequence_id missing or duplicated: " + sid)
        sequence_ids.add(sid)
        ids = item.get("shot_ids") or []
        if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids):
            errors.append(f"{sid} shot_ids must be strings")
            continue
        if not ids or len(ids) != len(set(ids)):
            errors.append(f"{sid} needs distinct shot_ids")
        if known and not set(ids).issubset(known):
            errors.append(f"{sid} refers to shots outside this revision")
        questions = item.get("understanding_questions")
        if not isinstance(questions, list) or not questions or any(not isinstance(q, str) or not q.strip() for q in questions):
            errors.append(f"{sid} needs understanding_questions")
    events = contract.get("events") or []
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
        return errors + ["events must be a list of objects"]
    if any(not isinstance(e.get("event_id"), str) or not isinstance(e.get("sequence_id"), str) for e in events):
        return errors + ["event_id and sequence_id must be strings"]
    seen: set[str] = set()
    for item in events:
        eid = str(item.get("event_id") or "")
        if not eid or eid in seen:
            errors.append("event_id missing or duplicated: " + eid)
        seen.add(eid)
        if item.get("sequence_id") not in sequence_ids:
            errors.append(f"{eid} has unknown sequence_id")
        sequence = next((s for s in sequences if s.get("sequence_id") == item.get("sequence_id")), {})
        ids = item.get("shot_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
            errors.append(f"{eid} shot_ids must be strings")
        elif not set(ids).issubset({x for x in sequence.get("shot_ids") or [] if isinstance(x, str)}):
            errors.append(f"{eid} needs shot_ids within its sequence")
        if item.get("channel", "visual") not in {"visual", "audio"}:
            errors.append(f"{eid} channel must be visual or audio")
        if not item.get("expected_observation"):
            errors.append(f"{eid} needs expected_observation")
        try:
            if number(item.get("min_visible_sec", 0)) < 0:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append(f"{eid} min_visible_sec must be finite and nonnegative")
    for item in events:
        if not isinstance(item.get("depends_on", []), list) or any(not isinstance(d, str) for d in item.get("depends_on", [])):
            errors.append(f"{item.get('event_id')} depends_on must be strings")
            continue
        for dep in item.get("depends_on") or []:
            if dep not in seen or dep == item.get("event_id"):
                errors.append(f"{item.get('event_id')} invalid dependency {dep}")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {e.get("event_id"): e for e in events}
    if errors:
        return errors

    def visit(eid: str) -> None:
        if eid in visiting:
            errors.append("event dependency cycle: " + eid)
            return
        if eid in visited:
            return
        visiting.add(eid)
        for dep in by_id.get(eid, {}).get("depends_on") or []:
            if dep in by_id:
                visit(dep)
        visiting.remove(eid)
        visited.add(eid)

    for eid in by_id:
        visit(eid)
    return errors


def normalize_cut(prod: Path, cut: dict, episode: Any = 1) -> list[dict]:
    """Map supported EDLs to actual source files without changing the cut."""
    from .takes import get_take, resolve_shot_media, take_media_file, episode_key
    from .context import context_for

    ctx = context_for(prod, episode)

    rows = cut.get("timeline") if "timeline" in cut else cut.get("cuts")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("cut needs timeline/cuts objects")
    normalized: list[dict] = []
    for row in rows or []:
        if not row.get("used", True):
            continue
        sid = str(row.get("shot_id") or "")
        source = str(row.get("source") or row.get("video_file") or "")
        if not source:
            take = get_take(prod, str(row.get("take_id") or "")) if row.get("take_id") else None
            if row.get("take_id") and (not take or take.shot_id != sid):
                raise ValueError(f"{sid} invalid picture take")
            if take and episode_key(take.episode_id or 1) != episode_key(ctx.episode_token):
                raise ValueError(f"{sid} picture take belongs to another episode/revision")
            path = take_media_file(prod, take) if take else resolve_shot_media(prod, sid, episode)
            source = str(path.resolve().relative_to(Path(prod).resolve()))
        audio_source = str(row.get("audio_source") or source)
        if row.get("audio_take_id"):
            audio = get_take(prod, str(row["audio_take_id"]))
            if not audio or episode_key(audio.episode_id or 1) != episode_key(ctx.episode_token):
                raise ValueError(f"{sid} invalid audio take")
            audio_source = str(take_media_file(prod, audio).resolve().relative_to(Path(prod).resolve()))
        start = number(row.get("in_sec", row.get("in_point", row.get("start", 0))))
        end = number(row.get("out_sec", row.get("out_point", row.get("video_end", row.get("end", 0)))))
        speed = number(row.get("speed", 1))
        if start < 0 or end <= start or speed <= 0:
            raise ValueError(f"{sid} invalid cut interval/speed")
        audio_in = number(row.get("audio_in_sec", start))
        audio_out = number(row.get("audio_out_sec", row.get("audio_end", end)))
        if audio_in < 0 or audio_out <= audio_in:
            raise ValueError(f"{sid} invalid audio interval")
        fps = int(row.get("fps", 30))
        if fps < 1 or fps > 120:
            raise ValueError(f"{sid} fps must be 1..120")
        ideal = (end - start) / speed
        duration = number(row.get("output_duration_sec", row.get("actual_sec", math.ceil(ideal * fps - 0.00001) / fps)))
        if duration <= 0 or duration > ideal + 1 / fps + 0.001:
            raise ValueError(f"{sid} output duration adds unrecorded video padding")
        normalized.append({
            "shot_id": sid, "source": source, "source_sha256": row.get("source_sha256", ""),
            "in_sec": start, "out_sec": end, "speed": speed,
            "audio_source": audio_source, "audio_in_sec": audio_in, "audio_out_sec": audio_out,
            "audio_source_sha256": row.get("audio_source_sha256", ""),
            "audio_mode": row.get("audio_mode", "source"),
            "output_duration_sec": duration, "fps": fps,
        })
        media_path(prod, source)
        media_path(prod, audio_source)
    return normalized


def check_event_coverage(prod: Path, contract: dict, evidence: dict, cut: dict, episode: Any = 1) -> dict:
    """Check actual observed intervals survive the EDL, including speed and order."""
    errors = contract_errors(contract)
    pending: list[str] = []
    results: list[dict] = []
    hashes: dict[str, str] = {}
    if errors:
        return {"status": "fail", "errors": errors, "pending": [], "events": []}
    try:
        segments = normalize_cut(prod, cut, episode)
    except (ValueError, OSError, TypeError) as exc:
        return {"status": "fail", "errors": errors + [str(exc)], "pending": [], "events": []}
    if not segments:
        errors.append("edit contains no used segments")
    for seg in segments:
        for rel, declared in [(seg["source"], seg["source_sha256"]), (seg["audio_source"], seg["audio_source_sha256"])]:
            try:
                if rel not in hashes:
                    hashes[rel] = file_hash(media_path(prod, rel))
                if declared and declared != hashes[rel]:
                    errors.append(f"{seg['shot_id']} cut source changed: {rel}")
            except (OSError, ValueError) as exc:
                errors.append(f"{seg['shot_id']} source invalid: {exc}")
    if evidence.get("contract_sha256") != digest(contract):
        pending.append("event observations are missing or belong to an older contract")
        records = []
    else:
        records = evidence.get("observations") or []
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        errors.append("event observations must be objects")
        records = []
    occurrences: dict[str, tuple[float, float]] = {}
    for event in contract.get("events") or []:
        eid = event.get("event_id")
        observed = [r for r in records if r.get("event_id") == eid and r.get("status") == "observed"]
        details = {"event_id": eid, "status": "pending", "retained_sec": 0.0}
        local_errors: list[str] = []
        retained: list[tuple[float, float]] = []
        for obs in observed:
            sid = obs.get("shot_id")
            rel = str(obs.get("source") or "")
            if sid not in event.get("shot_ids", []):
                local_errors.append(f"{eid} observation uses an unassigned shot")
                continue
            if not obs.get("reviewer") or not obs.get("reviewed_at") or obs.get("method") not in {"human_video", "visual_inspection", "audio_inspection"}:
                local_errors.append(f"{eid} needs a recorded media observation")
                continue
            try:
                actual = hashes.get(rel) or file_hash(media_path(prod, rel))
                hashes[rel] = actual
                if obs.get("source_sha256") != actual:
                    raise ValueError("observation source hash is stale")
                a, b = number(obs["start_sec"]), number(obs["end_sec"])
                if a < 0 or b <= a:
                    raise ValueError("invalid observation interval")
            except (KeyError, OSError, ValueError, TypeError) as exc:
                local_errors.append(f"{eid}: {exc}")
                continue
            cursor = 0.0
            for seg in segments:
                duration = seg["output_duration_sec"]
                channel = event.get("channel", "visual")
                src = seg["audio_source"] if channel == "audio" else seg["source"]
                inn = seg["audio_in_sec"] if channel == "audio" else seg["in_sec"]
                out = seg["audio_out_sec"] if channel == "audio" else seg["out_sec"]
                if (channel == "audio" or seg["shot_id"] == sid) and src == rel and not (channel == "audio" and seg["audio_mode"] == "silent"):
                    lo, hi = max(a, inn), min(b, out)
                    if hi > lo:
                        retained.append((cursor + (lo - inn) / seg["speed"], min(cursor + duration, cursor + (hi - inn) / seg["speed"])))
                cursor += duration
        retained = sorted((a, b) for a, b in retained if b > a)
        merged: list[list[float]] = []
        for a, b in retained:
            if merged and a <= merged[-1][1] + 0.0001:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        visible = sum(b - a for a, b in merged)
        details["retained_sec"] = round(visible, 4)
        if local_errors:
            details["status"] = "fail"
            errors.extend(local_errors)
        elif event.get("required", True) and observed and (not merged or visible + 0.001 < number(event.get("min_visible_sec", 0))):
            details["status"] = "fail"
            errors.append(f"{eid} required observed event is omitted or too short in this cut")
        elif merged:
            details["status"] = "pass"
            details["edit_interval"] = [merged[0][0], merged[-1][1]]
            occurrences[eid] = (merged[0][0], merged[-1][1])
        elif event.get("required", True):
            pending.append(f"{eid} actual event has not been observed and reviewed")
        else:
            details["status"] = "n/a"
        results.append(details)
    for event in contract.get("events") or []:
        eid = event["event_id"]
        for dep in event.get("depends_on") or []:
            if eid in occurrences and dep in occurrences and occurrences[dep][1] > occurrences[eid][0] + 0.001:
                errors.append(f"{eid} appears before prerequisite {dep} has completed")
    return {"status": "fail" if errors else "pending" if pending else "pass", "errors": errors, "pending": pending,
            "events": results, "source_hashes": hashes, "scope": "observed event retention; not audience comprehension"}


def sequence_fingerprint(prod: Path, contract: dict, cut: dict, sequence_id: str, episode: Any = 1) -> str:
    seq = next((s for s in contract.get("sequences") or [] if s.get("sequence_id") == sequence_id), None)
    if not seq:
        raise ValueError("unknown sequence: " + sequence_id)
    ids = set(seq.get("shot_ids") or [])
    rows = [r for r in normalize_cut(prod, cut, episode) if r["shot_id"] in ids]
    if not rows:
        raise ValueError("sequence has no used media")
    for row in rows:
        row["source_sha256"] = file_hash(media_path(prod, row["source"]))
        row["audio_source_sha256"] = file_hash(media_path(prod, row["audio_source"]))
    return digest({"sequence": seq, "events": [e for e in contract.get("events") or [] if e.get("sequence_id") == sequence_id], "edit": rows})


def record_sequence_review(prod: Path, contract: dict, cut: dict, sequence_id: str, *, reviewer: str,
                           viewed_file: str, answers: list[str], verdict: str, notes: str,
                           episode: Any = 1, viewed_sha256: str = "", blind: bool = True,
                           sound_review: str = "unknown", known_issues: list[str] | None = None) -> dict:
    """Explicit reviewer action; never called by a generator or a normalizer."""
    seq = next((s for s in contract.get("sequences") or [] if s.get("sequence_id") == sequence_id), None)
    if not seq or not reviewer.strip() or not notes.strip():
        raise ValueError("sequence review needs sequence, reviewer and notes")
    if verdict not in {"pass", "fail", "inconclusive"}:
        raise ValueError("review verdict must be pass, fail or inconclusive")
    if not isinstance(answers, list) or len(answers) != len(seq.get("understanding_questions") or []) or any(not isinstance(a, str) or not a.strip() for a in answers):
        raise ValueError("answer every understanding question after viewing")
    actual = file_hash(media_path(prod, viewed_file))
    if not viewed_sha256 or actual != viewed_sha256:
        raise ValueError("review must provide the hash of the actual viewed file")
    expected = sequence_fingerprint(prod, contract, cut, sequence_id, episode)
    receipt = read_export_receipt(prod, viewed_file)
    if receipt.get("media_sha256") != actual or receipt.get("sequences", {}).get(sequence_id) != expected:
        raise ValueError("viewed movie is not a recorded export of this sequence/edit")
    if verdict == "pass" and (not blind or sound_review not in {"pass", "n/a"} or known_issues):
        raise ValueError("pass needs blind comprehension, applicable sound review and no unresolved issues")
    return {"sequence_id": sequence_id, "status": verdict, "reviewer": reviewer.strip(), "reviewed_at": int(time.time()),
            "input_sha256": expected,
            "viewed_file": viewed_file, "viewed_sha256": actual, "answers": answers, "notes": notes,
            "blind": blind, "sound_review": sound_review, "known_issues": known_issues or []}


def check_sequence_reviews(prod: Path, contract: dict, cut: dict, reviews: dict, episode: Any = 1) -> list[str]:
    pending: list[str] = []
    rows = reviews.get("reviews") or []
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return ["sequence reviews must be objects"]
    ids = [r.get("sequence_id") for r in rows]
    if any(not isinstance(s, str) for s in ids) or len(ids) != len(set(ids)) or set(ids) - {s["sequence_id"] for s in contract.get("sequences") or []}:
        return ["sequence review IDs are duplicated or outside this contract"]
    for seq in contract.get("sequences") or []:
        sid = seq["sequence_id"]
        row = next((r for r in rows if r.get("sequence_id") == sid), {})
        try:
            expected = sequence_fingerprint(prod, contract, cut, sid, episode)
            answers = row.get("answers") or []
            if row.get("status") != "pass" or not row.get("reviewer") or not row.get("reviewed_at") or not row.get("notes"):
                raise ValueError("no completed review")
            if row.get("input_sha256") != expected:
                raise ValueError("edit or input evidence changed")
            if not row.get("blind") or row.get("sound_review") not in {"pass", "n/a"} or row.get("known_issues"):
                raise ValueError("comprehension/sound review incomplete")
            if len(answers) != len(seq.get("understanding_questions") or []) or any(not str(a).strip() for a in answers):
                raise ValueError("understanding answers incomplete")
            if file_hash(media_path(prod, row.get("viewed_file", ""))) != row.get("viewed_sha256"):
                raise ValueError("viewed movie changed")
            receipt = read_export_receipt(prod, row["viewed_file"])
            if receipt.get("media_sha256") != row["viewed_sha256"] or receipt.get("sequences", {}).get(sid) != expected:
                raise ValueError("viewed movie is not bound to this edit")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            pending.append(f"{sid}: {exc}")
    return pending


def read_export_receipt(prod: Path, rel: str) -> dict:
    path = media_path(prod, rel).with_suffix(".receipt.json")
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def write_export_receipt(prod: Path, contract: dict, cut: dict, rel: str, episode: Any = 1) -> dict:
    """Called by the exporter after it has rendered this EDL, never by a reviewer."""
    movie = media_path(prod, rel)
    body = {"schema": "edit-export-receipt-v1", "media": rel, "media_sha256": file_hash(movie),
            "cut_sha256": digest(cut), "created_at": int(time.time()), "sequences": {}}
    present = {r["shot_id"] for r in normalize_cut(prod, cut, episode)}
    for seq in contract.get("sequences") or []:
        if set(seq.get("shot_ids") or []).issubset(present):
            body["sequences"][seq["sequence_id"]] = sequence_fingerprint(prod, contract, cut, seq["sequence_id"], episode)
    path = movie.with_suffix(".receipt.json")
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    return body


def inspect_narrative(prod: Path, episode: Any = 1, revision_id: str = "", cut: dict | None = None) -> dict:
    from .context import ProductionContext

    ctx = ProductionContext.resolve(prod, episode, revision_id)
    contract = ctx.read_artifact("events.json")
    if not contract:
        return {"status": "pending", "errors": [], "pending": ["missing narrative sequence contract"], "events": []}
    evidence = ctx.read_artifact("event_evidence.json")
    actual_cut = cut if cut is not None else ctx.read_artifact("cut.json")
    report = check_event_coverage(prod, contract, evidence, actual_cut, ctx.episode_token)
    if actual_cut:
        report["pending"].extend(check_sequence_reviews(prod, contract, actual_cut, ctx.read_artifact("sequence_reviews.json"), ctx.episode_token))
    if not report["errors"] and report["pending"]:
        report["status"] = "pending"
    report["revision"] = ctx.to_dict()
    return report


def require_event_coverage(prod: Path, episode: Any = 1, revision_id: str = "", cut: dict | None = None) -> dict:
    from .context import ProductionContext

    ctx = ProductionContext.resolve(prod, episode, revision_id)
    contract = ctx.read_artifact("events.json")
    if not contract:
        raise PermissionError("缺段落合同；先定义核心证据和理解问题")
    report = check_event_coverage(prod, contract, ctx.read_artifact("event_evidence.json"), cut if cut is not None else ctx.read_artifact("cut.json"), ctx.episode_token)
    if report["status"] != "pass":
        raise PermissionError("叙事事件未通过：" + "; ".join((report["errors"] + report["pending"])[:5]))
    return report


def require_sequence_reviews(prod: Path, episode: Any = 1, revision_id: str = "", cut: dict | None = None) -> dict:
    report = inspect_narrative(prod, episode, revision_id, cut)
    if report["status"] != "pass":
        raise PermissionError("段落声画审阅未通过：" + "; ".join((report["errors"] + report["pending"])[:5]))
    return report


def require_design_review(prod: Path, episode: Any = 1, revision_id: str = "") -> None:
    from .context import ProductionContext
    from .shot_table import design_review_errors

    ctx = ProductionContext.resolve(prod, episode, revision_id)
    if ctx.mode == "registered":
        table = ctx.read_artifact("shot_list.json", required=True)
        errors = design_review_errors(table)
        contract = ctx.read_artifact("events.json")
        errors.extend(contract_errors(contract, [s.get("shot_id") or s.get("id") for s in table.get("shots") or []]))
        if (table.get("narrative_review") or {}).get("events_sha256") != digest(contract):
            errors.append("narrative event contract review is missing or stale")
        if errors:
            raise PermissionError("创作合同尚未人工审阅：" + "; ".join(errors[:3]))


def require_cut_media_reviews(prod: Path, cut: dict, episode: Any = 1) -> None:
    """The exact picture and sound takes used by an edit must have been reviewed."""
    from .context import ProductionContext
    from .pipeline import assert_clips_passed

    ctx = ProductionContext.resolve(prod, episode)
    segments = normalize_cut(prod, cut, ctx.episode_token)
    ids = list(dict.fromkeys(s["shot_id"] for s in segments))
    assert_clips_passed(prod, ctx.episode_token, selected_shot_ids=ids)
    if ctx.mode != "registered":
        return
    rows = {r.get("shot_id"): r for r in ctx.read_artifact("clips.json").get("clips") or []}
    for seg in segments:
        row = rows.get(seg["shot_id"], {})
        review = row.get("review") or row.get("qc") or {}
        hashes = dict(review.get("media_hashes") or {})
        video = row.get("video_file") or row.get("file")
        single = review.get("video_sha256") or review.get("media_hash")
        if video and single:
            hashes.setdefault(video, single)
        required = [seg["source"]]
        if seg["audio_mode"] != "silent":
            required.append(seg["audio_source"])
        for rel in required:
            if hashes.get(rel) != file_hash(media_path(prod, rel)):
                raise PermissionError(f"{seg['shot_id']} 剪辑采用的素材没有当前字节的审核：{rel}")
