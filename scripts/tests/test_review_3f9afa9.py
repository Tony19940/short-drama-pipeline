#!/usr/bin/env python3
"""Acceptance regressions from the 3f9afa9 review. No vendor/network calls."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_seedance_packages as renderer  # noqa: E402
from director.fingerprint import (  # noqa: E402
    snapshot_batch,
    snapshot_content_fingerprint,
    write_confirmed_snapshot,
)
from director.vendor_request import VendorRequest, sha256_file  # noqa: E402
from video_backends.seedance_ark import (  # noqa: E402
    MP4_PROBE_VERSION,
    SeedanceArk,
    looks_like_mp4_file,
)


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _jpg(path: Path, tone: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 72), (tone, 45, 75)).save(path)


def _make_plan(prod: Path, kind: str):
    first = "04-frames/SH001.jpg" if kind in {"first_frame", "first_last"} else ""
    last = "04-frames/SH001-last.jpg" if kind == "first_last" else ""
    refs = ("02-assets/a.jpg", "02-assets/b.jpg") if kind == "reference" else ()
    rels = [rel for rel in (first, last, *refs) if rel]
    for i, rel in enumerate(rels):
        _jpg(prod / rel, 20 + 30 * i)
    req = VendorRequest(
        provider="ark",
        model="doubao-seedance-2-5-260628",
        profile_id="seedance_2_5",
        task_kind=kind,
        ratio="16:9",
        resolution="720p",
        duration_sec=4,
        generate_audio=False,
        prompt="confirmed",
        shot_id="SH001",
        first_frame=first,
        last_frame=last,
        refs=refs,
        media_hashes={rel: sha256_file(prod / rel) for rel in rels},
        production_id=prod.name,
        episode_id="ep01",
    )
    batch = snapshot_batch(episode=1, shot_ids=["SH001"], requests=[req.to_dict()])
    digest = snapshot_content_fingerprint(batch)
    rel = write_confirmed_snapshot(
        prod,
        digest,
        episode=1,
        shot_ids=["SH001"],
        requests=[req.to_dict()],
    )
    plan = renderer.plan_from_snapshot(
        prod,
        rel,
        expected_fingerprint=digest,
        expected_episode=1,
        expected_shot_ids=["SH001"],
    )
    assert plan["ok_count"] == 1, plan
    return req, plan


def _capture_payload(prod: Path, plan: dict):
    captured: list[dict] = []

    def post(*_a, **kwargs):
        captured.append(kwargs["json"])
        raise RuntimeError("payload captured")

    with mock.patch("requests.post", post):
        try:
            renderer.render_plan(prod, plan, skip_existing=True)
        except RuntimeError as exc:
            if "payload captured" not in str(exc):
                raise
        except (PermissionError, FileNotFoundError, SystemExit):
            assert not captured
            return None
    assert len(captured) == 1
    return captured[0]


def _corrupt_mdat(video: Path) -> None:
    data = bytearray(video.read_bytes())
    off = 0
    found = False
    while off + 8 <= len(data):
        size = struct.unpack(">I", data[off : off + 4])[0]
        tag = data[off + 4 : off + 8]
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[off + 8 : off + 16])[0]
            header = 16
        if size == 0:
            size = len(data) - off
        assert size >= header
        if tag == b"mdat":
            data[off + header : off + size] = b"\0" * (size - header)
            found = True
        off += size
    assert found
    video.write_bytes(data)


class ConfirmedPayloadInputs(unittest.TestCase):
    def test_removed_last_frame_keeps_or_refuses_flf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            os.environ["ARK_API_KEY"] = os.environ.get("ARK_API_KEY") or "offline"
            req, plan = _make_plan(prod, "first_last")
            (prod / req.last_frame).unlink()
            payload = _capture_payload(prod, plan)
            if payload is None:
                return
            roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
            self.assertEqual(roles, ["first_frame", "last_frame"])
            media = [item for item in payload["content"] if item.get("type") == "image_url"]
            for rel, item in zip([req.first_frame, req.last_frame], media):
                data = base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
                self.assertEqual(hashlib.sha256(data).hexdigest(), req.media_hash_map()[rel])

    def test_removed_reference_keeps_order_or_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            os.environ["ARK_API_KEY"] = os.environ.get("ARK_API_KEY") or "offline"
            req, plan = _make_plan(prod, "reference")
            (prod / req.refs[0]).unlink()
            payload = _capture_payload(prod, plan)
            if payload is None:
                return
            roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
            self.assertEqual(roles, ["reference_image", "reference_image"])
            media = [item for item in payload["content"] if item.get("type") == "image_url"]
            for rel, item in zip(req.refs, media):
                data = base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
                self.assertEqual(hashlib.sha256(data).hexdigest(), req.media_hash_map()[rel])

    def test_build_payload_refuses_flf_without_last(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = Path(raw) / "first.jpg"
            _jpg(first, 10)
            os.environ["ARK_API_KEY"] = os.environ.get("ARK_API_KEY") or "offline"
            backend = SeedanceArk(model="doubao-seedance-2-5-260628")
            with self.assertRaises(RuntimeError):
                backend.build_payload(first, "x", 4, mode="flf", last_frame=Path(raw) / "missing.jpg")


class Mp4DecodeCheck(unittest.TestCase):
    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg and ffprobe required")
    def test_broken_mdat_must_not_pass_technical_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            video = Path(raw) / "bad.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=24:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(video),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            _corrupt_mdat(video)
            decode = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-xerror",
                    "-i",
                    str(video),
                    "-map",
                    "0:v:0",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(decode.returncode, 0)
            self.assertFalse(looks_like_mp4_file(video))

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg and ffprobe required")
    def test_old_validator_ticket_must_redecode_before_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            video = Path(raw) / "ok.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x90:r=24:d=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            req_hash = "b" * 64
            ticket = {
                "request_hash": req_hash,
                "status": "verified",
                "output_sha256": sha256_file(video),
                "validator": "mp4-probe-v1",
            }
            video.with_suffix(".mp4.ark-task.json").write_text(json.dumps(ticket), encoding="utf-8")
            self.assertTrue(SeedanceArk.clip_matches_request(video, req_hash))
            upgraded = json.loads(video.with_suffix(".mp4.ark-task.json").read_text(encoding="utf-8"))
            self.assertEqual(upgraded["validator"], MP4_PROBE_VERSION)

            broken = Path(raw) / "broken.mp4"
            shutil.copyfile(video, broken)
            _corrupt_mdat(broken)
            bad_ticket = {
                "request_hash": req_hash,
                "status": "verified",
                "output_sha256": sha256_file(broken),
                "validator": "mp4-probe-v1",
            }
            broken.with_suffix(".mp4.ark-task.json").write_text(json.dumps(bad_ticket), encoding="utf-8")
            self.assertFalse(SeedanceArk.clip_matches_request(broken, req_hash))


if __name__ == "__main__":
    unittest.main()
