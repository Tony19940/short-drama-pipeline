"""Explicit review commands shared by the local CLI and director API.

No generator calls these functions. A check only reports; it never signs a pass.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .context import ProductionContext
from .narrative import (digest, file_hash, media_path, number, record_sequence_review,
                        contract_errors)
from .shot_table import design_review_digest, record_human_design_review


def save(ctx: ProductionContext, base: str, data: dict) -> dict:
    path = ctx.artifact_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def record_design(ctx: ProductionContext, payload: dict) -> dict:
    draft = str(payload.get("draft_file") or "")
    if draft:
        path = media_path(ctx.prod, draft)
        if not draft.endswith(".draft.json") or not draft.startswith(".pipeline/"):
            raise ValueError("creative review draft_file must name a .pipeline/*.draft.json")
        table = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(table, dict):
            raise ValueError("creative draft must be an object")
    else:
        table = ctx.read_artifact("shot_list.json", required=True)
    contract = ctx.read_artifact("events.json", required=True)
    issues = contract_errors(contract, [s.get("shot_id") or s.get("id") for s in table.get("shots") or []])
    if issues:
        raise ValueError("; ".join(issues))
    if payload.get("contract_sha256") != digest(contract):
        raise ValueError("creative review must identify the current contract_sha256")
    if payload.get("input_sha256") != design_review_digest(table):
        raise ValueError("provide the current creative input_sha256; table changed or was not viewed")
    reviewed = record_human_design_review(
        table, reviewer=str(payload.get("reviewer") or ""), notes=str(payload.get("notes") or ""),
        scene_findings=payload.get("scene_findings"))
    reviewed["narrative_review"]["events_sha256"] = digest(contract)
    if draft:
        reviewed["narrative_review"]["reviewed_draft"] = draft
        reviewed["status"] = "ready"
    return save(ctx, "shot_list.json", reviewed)


def record_observation(ctx: ProductionContext, payload: dict) -> dict:
    contract = ctx.read_artifact("events.json", required=True)
    table = ctx.read_artifact("shot_list.json", required=True)
    errors = contract_errors(contract, [s.get("shot_id") or s.get("id") for s in table.get("shots") or []])
    if errors:
        raise ValueError("; ".join(errors))
    if payload.get("contract_sha256") != digest(contract):
        raise ValueError("observation must identify the current contract_sha256")
    event = next((e for e in contract.get("events") or [] if e.get("event_id") == payload.get("event_id")), None)
    if not event or payload.get("shot_id") not in event["shot_ids"]:
        raise ValueError("event/shot is outside this contract")
    if not str(payload.get("reviewer") or "").strip() or not str(payload.get("notes") or "").strip():
        raise ValueError("observation needs reviewer and concrete media notes")
    if payload.get("method") not in {"human_video", "visual_inspection", "audio_inspection"}:
        raise ValueError("observation needs a media inspection method")
    actual = file_hash(media_path(ctx.prod, str(payload.get("source") or "")))
    if payload.get("source_sha256") != actual:
        raise ValueError("observation source_sha256 does not match actual media")
    a, b = number(payload.get("start_sec")), number(payload.get("end_sec"))
    if a < 0 or b <= a:
        raise ValueError("observation needs a positive source interval")
    record = {key: payload.get(key) for key in ("event_id", "shot_id", "source", "source_sha256", "reviewer", "notes", "method")}
    record.update(start_sec=a, end_sec=b, status="observed", reviewed_at=int(time.time()))
    current = ctx.read_artifact("event_evidence.json")
    if current.get("contract_sha256") != digest(contract):
        current = {"contract_sha256": digest(contract), "observations": []}
    rows = [r for r in current.get("observations") or [] if not (r.get("event_id") == record["event_id"] and r.get("shot_id") == record["shot_id"])]
    return save(ctx, "event_evidence.json", {**current, "observations": rows + [record]})


def record_sequence(ctx: ProductionContext, payload: dict) -> dict:
    contract = ctx.read_artifact("events.json", required=True)
    cut = ctx.read_artifact("cut.json", required=True)
    row = record_sequence_review(
        ctx.prod, contract, cut, str(payload.get("sequence_id") or ""),
        reviewer=str(payload.get("reviewer") or ""), viewed_file=str(payload.get("viewed_file") or ""),
        viewed_sha256=str(payload.get("viewed_sha256") or ""), answers=payload.get("answers") or [],
        verdict=str(payload.get("verdict") or ""), notes=str(payload.get("notes") or ""),
        episode=ctx.episode_token, blind=payload.get("blind") is True,
        sound_review=str(payload.get("sound_review") or "unknown"), known_issues=payload.get("known_issues") or [])
    current = ctx.read_artifact("sequence_reviews.json")
    rows = [r for r in current.get("reviews") or [] if r.get("sequence_id") != row["sequence_id"]]
    return save(ctx, "sequence_reviews.json", {"schema": "sequence-reviews-v1", "reviews": rows + [row]})
