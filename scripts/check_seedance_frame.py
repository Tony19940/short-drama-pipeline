#!/usr/bin/env python3
"""Ask Seedance 2.0 mini whether a first-frame jpg trips the real-person face block.

There is no official precheck API that shares this classifier. The create-task
POST is the check: HTTP 400 + InputImageSensitiveContentDetected.PrivacyInformation
means face-block (no task id, not billed). HTTP 200 means the face check passed;
this script then DELETE-cancels so a pass probe does not wait for a full clip.
Running tasks cannot be cancelled and a 4s 480p render may still bill.

Exit: 0 pass, 1 face-block, 2 other error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import load_dotenv
from video_backends.seedance_ark import (  # noqa: F401
    FACE_BLOCK_CODE,
    SeedanceArk,
    SeedanceFaceBlock,
    ark_error_code,
    classify_create,
)

PROBE_PROMPT = "数字电影CG，固定机位，画面微动，不要说话，不要字幕水印。"


def resolve_image(image: str, prod: str | None) -> Path:
    raw = Path(image)
    if raw.is_absolute():
        return raw
    if prod:
        return (Path(prod) / image).resolve()
    cwd = (Path.cwd() / image).resolve()
    if cwd.exists():
        return cwd
    return (ROOT / image).resolve()


def payload_summary(payload: dict) -> dict:
    roles = [item.get("role") for item in payload.get("content") or [] if item.get("type") == "image_url"]
    text_items = [item for item in payload.get("content") or [] if item.get("type") == "text"]
    return {
        "model": payload.get("model"),
        "duration": payload.get("duration"),
        "resolution": payload.get("resolution"),
        "ratio": payload.get("ratio"),
        "generate_audio": payload.get("generate_audio"),
        "watermark": payload.get("watermark"),
        "image_roles": roles,
        "text_len": len(str((text_items[0] or {}).get("text") or "")) if text_items else 0,
    }


def task_id_of(body: dict) -> str:
    return str(body.get("id") or (body.get("data") or {}).get("id") or body.get("task_id") or "").strip()


def print_result(verdict: str, code: str, extra: str = "") -> None:
    line = f"{verdict} {code}".strip()
    print(line, flush=True)
    if extra:
        print(extra, file=sys.stderr, flush=True)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Seedance 2.0 mini first-frame face-block probe")
    parser.add_argument("--image", required=True, help="first-frame jpg (repo- or --prod-relative)")
    parser.add_argument("--prod", help="production dir; --image is relative to it")
    parser.add_argument("--dry-run", action="store_true", help="print payload summary only; no network")
    args = parser.parse_args()

    image = resolve_image(args.image, args.prod)
    if not image.is_file():
        print_result("ERROR", "missing_image", f"no such file: {image}")
        return 2

    backend = SeedanceArk()
    backend.resolution = "480p"
    seconds = backend.min_duration
    payload = backend.build_payload(
        image,
        PROBE_PROMPT,
        seconds,
        refs=None,
        mode="i2v",
        generate_audio=False,
    )
    summary = payload_summary(payload)
    if args.dry_run:
        print_result("DRY-RUN", "ok")
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
        return 0

    started = time.time()
    http_status, body = backend.create_task(payload)
    elapsed = time.time() - started
    verdict, code, exit_code = classify_create(http_status, body)
    note = f"http={http_status} {elapsed:.1f}s model={backend.model} {summary['resolution']}/{summary['duration']}s first_frame_only"

    if verdict != "PASS":
        print_result(verdict, code, note)
        return exit_code

    task_id = task_id_of(body)
    cancel_note = "create 200, no task id"
    if task_id:
        cancel_http, _cancel_body = backend.cancel_task(task_id)
        status = ""
        query_http, query_body = backend.query_task(task_id)
        if query_http < 400:
            status = str(query_body.get("status") or "").lower()
        if status == "cancelled" or status == "canceled":
            cancel_note = f"cancelled {task_id}"
        elif status == "running":
            cancel_note = (
                f"cancel missed; {task_id} still running — 4s 480p may bill "
                f"(DELETE only works while queued; http={cancel_http})"
            )
        elif status:
            cancel_note = f"cancel http={cancel_http} status={status} {task_id}"
        else:
            cancel_note = f"cancel http={cancel_http} query http={query_http} {task_id}"
    print_result("PASS", code, f"{note}; {cancel_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
