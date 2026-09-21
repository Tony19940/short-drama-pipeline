#!/usr/bin/env python3
"""Acceptance regressions from the 5b90f73 review. No vendor/network calls."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
    confirmed_snapshot_rel,
    snapshot_content_fingerprint,
    write_confirmed_snapshot,
)
from director.jobs import enqueue_render_confirmed  # noqa: E402
from director.pipeline import compile_packages_from_specs  # noqa: E402
from director.prompts import compile_keyframe_prompt_zh  # noqa: E402
from director.vendor_request import COMPILER_VERSION, vendor_request_from_package  # noqa: E402
from video_backends.seedance_ark import SeedanceArk, looks_like_mp4_file  # noqa: E402


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _make_color_mp4(dest: Path, color: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s=320x180:r=24:d=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )


def _request(prod: Path):
    image = prod / "04-frames" / "SH001.jpg"
    image.parent.mkdir(parents=True)
    (prod / "05-shots").mkdir(exist_ok=True)
    Image.new("RGB", (128, 72), (20, 20, 20)).save(image)
    return vendor_request_from_package(
        prod,
        {
            "shot_id": "SH001",
            "target_model": "seedance_2_5",
            "gen_mode": "i2v_first",
            "duration_sec": 4,
            "motion_prompt": "A confirmed action",
            "aspect_ratio": "16:9",
            "generate_audio": False,
            "first_frame": "04-frames/SH001.jpg",
        },
        {"first_frame_file": "04-frames/SH001.jpg"},
    )


def _write_snap(prod: Path, req):
    batch = {
        "compiler_version": COMPILER_VERSION,
        "episode": "1",
        "shot_ids": [req.shot_id],
        "requests": [req.to_dict()],
    }
    fingerprint = snapshot_content_fingerprint(batch)
    rel = write_confirmed_snapshot(
        prod,
        fingerprint,
        episode=1,
        shot_ids=[req.shot_id],
        requests=[req.to_dict()],
    )
    return fingerprint, rel


class MediaAndReuse(unittest.TestCase):
    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg and ffprobe required")
    def test_truncated_mp4_must_fail_technical_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            original = Path(raw) / "ok.mp4"
            _make_color_mp4(original, "black")
            broken = Path(raw) / "truncated.mp4"
            broken.write_bytes(original.read_bytes()[:1400])
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", str(broken)],
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(probe.returncode, 0)
            self.assertFalse(looks_like_mp4_file(broken))

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg and ffprobe required")
    def test_output_replacement_must_invalidate_reuse(self) -> None:
        from director.vendor_request import sha256_file

        with tempfile.TemporaryDirectory() as raw:
            first = Path(raw) / "a.mp4"
            other = Path(raw) / "b.mp4"
            _make_color_mp4(first, "black")
            _make_color_mp4(other, "white")
            dest = Path(raw) / "SH001.mp4"
            shutil.copyfile(first, dest)
            req_hash = "a" * 64
            ticket = {
                "request_hash": req_hash,
                "status": "verified",
                "output_sha256": sha256_file(dest),
            }
            dest.with_suffix(".mp4.ark-task.json").write_text(json.dumps(ticket), encoding="utf-8")
            self.assertTrue(SeedanceArk.clip_matches_request(dest, req_hash))
            shutil.copyfile(other, dest)
            self.assertNotEqual(sha256_file(dest), ticket["output_sha256"])
            self.assertFalse(SeedanceArk.clip_matches_request(dest, req_hash))


class SnapshotIntegrity(unittest.TestCase):
    def test_media_change_before_plan_still_uses_frozen_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            req = _request(prod)
            confirmed = req.media_hash_map()[req.first_frame]
            _, rel = _write_snap(prod, req)
            (prod / req.first_frame).write_bytes(b"changed before planning")
            plan = renderer.plan_from_snapshot(prod, rel)
            self.assertTrue(plan["shots"][0]["ok"], plan["shots"][0]["errors"])
            os.environ["ARK_API_KEY"] = os.environ.get("ARK_API_KEY") or "offline"
            backend = SeedanceArk()
            seen: list[str] = []

            def render_spy(image, prompt, seconds, dest, **kw):
                import base64

                body = backend._data_url(image)
                seen.append(hashlib.sha256(base64.b64decode(body.split(",", 1)[1])).hexdigest())

            backend.render = render_spy  # type: ignore[method-assign]
            frozen = type(req).from_dict(plan["shots"][0]["vendor_request"])
            try:
                backend.render_request(frozen, prod / "SH001.mp4", prod=prod)
            except (ValueError, PermissionError, RuntimeError):
                pass
            self.assertEqual(seen, [confirmed])

    def test_media_change_after_plan_must_not_reach_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            os.environ["ARK_API_KEY"] = os.environ.get("ARK_API_KEY") or "offline"
            req = _request(prod)
            _, rel = _write_snap(prod, req)
            plan = renderer.plan_from_snapshot(prod, rel)
            self.assertTrue(plan["shots"][0]["ok"], plan["shots"][0]["errors"])
            frozen = type(req).from_dict(plan["shots"][0]["vendor_request"])
            Image.new("RGB", (128, 72), (200, 200, 200)).save(prod / req.first_frame)
            backend = SeedanceArk()
            reached: list[tuple[str, str]] = []

            def render_spy(image, prompt, seconds, dest, **kw):
                body = backend._data_url(image)
                payload = body.split(",", 1)[1]
                import base64

                reached.append((kw["request_hash"], hashlib.sha256(base64.b64decode(payload)).hexdigest()))

            backend.render = render_spy  # type: ignore[method-assign]
            try:
                backend.render_request(frozen, prod / "SH001.mp4", prod=prod)
            except (ValueError, PermissionError, RuntimeError):
                pass
            bad = [
                (h, media)
                for h, media in reached
                if h == frozen.fingerprint() and media != frozen.media_hash_map()[req.first_frame]
            ]
            self.assertFalse(bad)

    def test_edited_snapshot_must_be_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            req = _request(prod)
            _, rel = _write_snap(prod, req)
            path = prod / rel
            data = json.loads(path.read_text(encoding="utf-8"))
            data["requests"][0]["prompt"] = "Unconfirmed replacement"
            path.write_text(json.dumps(data), encoding="utf-8")
            try:
                plan = renderer.plan_from_snapshot(prod, rel)
            except (ValueError, PermissionError, RuntimeError, SystemExit):
                return
            self.assertEqual(plan["ok_count"], 0)

    def test_enqueue_must_keep_fingerprint_and_snapshot_paired(self) -> None:
        fp_a, fp_b = "a" * 64, "b" * 64
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            with mock.patch("director.jobs.require_fresh_gate", lambda *a, **k: None), mock.patch(
                "director.jobs.run_check", lambda *a, **k: {"ok": True}
            ), mock.patch("director.jobs.select_shots", lambda *a, **k: [{"id": "SH001"}]), mock.patch(
                "director.fingerprint.consume_render_fingerprint", lambda *a, **k: fp_a
            ), mock.patch(
                "director.fingerprint.require_task_inputs", lambda *a, **k: None
            ), mock.patch(
                "director.jobs.gpu_configured", lambda: False
            ), mock.patch(
                "director.jobs.default_render_backend", lambda: "seedance"
            ), mock.patch(
                "director.jobs.video_ready", lambda: False
            ), mock.patch(
                "director.jobs._append_job", lambda prod, job: job
            ):
                try:
                    job = enqueue_render_confirmed(prod, fp_a, ["SH001"])
                except (ValueError, PermissionError, RuntimeError):
                    return
            self.assertEqual(job["snapshot"], confirmed_snapshot_rel(job["fingerprint"]))
            self.assertNotEqual(job["snapshot"], confirmed_snapshot_rel(fp_b))


class CompileKeepsExactModel(unittest.TestCase):
    def _compile(self, model: str) -> tuple[dict, object]:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "02-assets").mkdir()
            table = {
                "schema": "shot-table-v2",
                "target_model": model,
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "SC01",
                        "duration_sec": 4,
                        "one_action": "她听完",
                        "dialogue_ref": [],
                        "left": "琳",
                        "right": "门",
                        "eyeline": "看门",
                    }
                ],
            }
            specs = {
                "shot_specs": [
                    {
                        "shot_id": "SH001",
                        "duration_sec": 4,
                        "action_now": "听",
                        "dialogue_line": "",
                        "left": "琳",
                        "right": "门",
                        "eyeline": "看门",
                    }
                ]
            }
            data = compile_packages_from_specs(prod, target_model=model, table=table, specs=specs)
            pkg = data["packages"][0]
            (prod / "04-frames").mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72)).save(prod / "04-frames" / "SH001.jpg")
            req = vendor_request_from_package(prod, pkg, {"first_frame_file": "04-frames/SH001.jpg"})
            return pkg, req

    def test_compile_packages_keeps_mini_id(self) -> None:
        model = "doubao-seedance-2-0-mini-260615"
        pkg, req = self._compile(model)
        self.assertEqual(pkg["target_model"], model)
        self.assertEqual(pkg["vendor_model"], model)
        self.assertEqual(pkg["capability_profile_id"], "seedance_2_0")
        self.assertEqual(req.model, model)

    def test_compile_packages_keeps_fast_id(self) -> None:
        model = "doubao-seedance-2-0-fast-260128"
        pkg, req = self._compile(model)
        self.assertEqual(pkg["target_model"], model)
        self.assertEqual(pkg["vendor_model"], model)
        self.assertEqual(pkg["capability_profile_id"], "seedance_2_0")
        self.assertEqual(req.model, model)


class KeyframePhasePrompt(unittest.TestCase):
    def _prompt(self, phase: str) -> str:
        spec = {"shot_size": "medium", "in_from": "手已伸出", "action_now": "继续伸手", "t0_phase": phase}
        shot = {"t0_phase": phase, "one_action": "继续伸手", "in_from": "手已伸出"}
        return compile_keyframe_prompt_zh(spec, shot)

    def test_onset_prompt_keeps_start_lock(self) -> None:
        text = self._prompt("onset")
        self.assertIn("画动作起点", text)
        self.assertIn("首帧只画起手", text)

    def test_mid_prompt_does_not_repeat_onset_lock(self) -> None:
        text = self._prompt("mid")
        self.assertIn("动作中段", text)
        self.assertNotIn("首帧只画起手", text)
        self.assertNotIn("只画起手", text)
        self.assertNotIn("画动作起点", text)

    def test_hold_prompt_does_not_repeat_onset_lock(self) -> None:
        text = self._prompt("hold")
        self.assertIn("停住听", text)
        self.assertNotIn("首帧只画起手", text)
        self.assertNotIn("画动作起点", text)

    def test_land_prompt_does_not_repeat_onset_lock(self) -> None:
        text = self._prompt("land")
        self.assertIn("已近落幅", text)
        self.assertNotIn("首帧只画起手", text)
        self.assertNotIn("画动作起点", text)


if __name__ == "__main__":
    unittest.main()
