#!/usr/bin/env python3
"""Acceptance regressions from the 10be446 review. No vendor/network calls."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_seedance_packages as renderer  # noqa: E402
from director import video_fallback  # noqa: E402
from director.fingerprint import write_confirmed_snapshot  # noqa: E402
from director.setup_anchors import same_setup  # noqa: E402
from director.station_agents import _repair_writer_lines, frame_desc_shots_ctx  # noqa: E402
from director.vendor_request import vendor_request_from_package  # noqa: E402
from video_backends.seedance_ark import SeedanceArk, SeedanceFaceBlock  # noqa: E402


def _jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 72)).save(path)


def package(**overrides: Any) -> dict[str, Any]:
    return {
        "shot_id": "SH001",
        "target_model": "seedance_2_5",
        "gen_mode": "i2v_first",
        "duration_sec": 8,
        "motion_prompt": "她先听完，再看向桌上的钥匙。",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "generate_audio": False,
        "speech_mode": "post_dub",
        "dialogue_language": "zh",
        "confirmed": True,
        **overrides,
    }


def keyframes() -> dict[str, dict[str, Any]]:
    return {"SH001": {"first_frame_file": "04-frames/SH001.jpg", "qc": {"status": "pass"}}}


class ContractRegressions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.prod = Path(self._tmp.name) / "show"
        (self.prod / "04-frames").mkdir(parents=True)
        (self.prod / "05-shots").mkdir()
        _jpg(self.prod / "04-frames" / "SH001.jpg")
        self.env = mock.patch.dict(os.environ, {"ARK_API_KEY": "offline-review-not-a-real-key"}, clear=False)
        self.env.start()
        self.blocked = mock.patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Network is forbidden in this regression module"),
        )
        self.blocked.start()

    def tearDown(self) -> None:
        self.blocked.stop()
        self.env.stop()
        self._tmp.cleanup()

    def test_explicit_mini_is_not_replaced_by_profile_first_model(self) -> None:
        req = vendor_request_from_package(
            self.prod, package(target_model="doubao-seedance-2-0-mini-260615"), keyframes()["SH001"]
        )
        self.assertEqual(req.model, "doubao-seedance-2-0-mini-260615")

    def test_explicit_fast_is_not_replaced_by_profile_first_model(self) -> None:
        req = vendor_request_from_package(
            self.prod, package(target_model="doubao-seedance-2-0-fast-260128"), keyframes()["SH001"]
        )
        self.assertEqual(req.model, "doubao-seedance-2-0-fast-260128")

    def test_r2v_references_survive_plan_compilation(self) -> None:
        ref = "04-frames/SH001.jpg"
        item = renderer.plan_shot(self.prod, package(gen_mode="r2v", refs=[ref]), keyframes(), {})
        self.assertTrue(item["ok"], item["errors"])
        self.assertEqual(item["vendor_request"]["refs"], [ref])

    def test_large_invalid_existing_file_does_not_short_circuit_validation(self) -> None:
        dest = self.prod / "05-shots" / "SH001.mp4"
        dest.write_bytes(b"not a video\n" * 300)
        item = renderer.plan_shot(self.prod, package(), keyframes(), {})
        self.assertTrue(item["ok"], item["errors"])
        visited: list[bool] = []

        class ReachedValidationBoundary(RuntimeError):
            pass

        def stop_at_backend(_: dict[str, Any]) -> None:
            visited.append(True)
            raise ReachedValidationBoundary("Stop before any vendor side effect")

        with mock.patch.object(renderer, "_backend_for_item", stop_at_backend):
            try:
                renderer.render_plan(self.prod, {"dest_dir": "05-shots", "shots": [item]}, skip_existing=True)
            except (ReachedValidationBoundary, ValueError, PermissionError, RuntimeError, SystemExit):
                return
        self.assertTrue(visited, "Renderer silently accepted/skipped a corrupt >1KiB file")

    def test_legacy_ticket_without_hash_cannot_be_relabelled_as_current_request(self) -> None:
        backend = SeedanceArk(model="doubao-seedance-2-5-260628", min_duration=4, max_duration=30)
        dest = self.prod / "05-shots" / "SH001.mp4"
        backend._write_ticket(dest, {"task_id": "OLD-UNVERIFIED-TASK", "status": "submitted"})
        queried: list[str] = []
        backend.submit = lambda *a, **kw: "NEW-TASK"  # type: ignore[method-assign]

        def wait(task_id: str) -> str:
            queried.append(task_id)
            return "offline://video"

        backend.wait_url = wait  # type: ignore[method-assign]
        backend.download = lambda url, path: path.write_bytes(b"\x00\x00\x00\x18ftypisomstub")  # type: ignore[method-assign]
        try:
            backend.render(self.prod / "04-frames" / "SH001.jpg", "new prompt", 8, dest)
        except (ValueError, PermissionError, RuntimeError):
            self.assertNotIn("OLD-UNVERIFIED-TASK", queried)
            return
        self.assertNotIn("OLD-UNVERIFIED-TASK", queried)
        self.assertNotEqual(backend._read_ticket(dest).get("task_id"), "OLD-UNVERIFIED-TASK")

    def test_face_block_does_not_authorize_a_different_paid_vendor(self) -> None:
        fallback_calls: list[bool] = []

        class FaceBlockedBackend:
            def render(self, *args: Any, **kwargs: Any) -> None:
                raise SeedanceFaceBlock()

        def forbidden_fallback(*args: Any, **kwargs: Any) -> dict[str, str]:
            fallback_calls.append(True)
            return {"backend": "minimax_h3"}

        with mock.patch.object(video_fallback, "official_h3_fallback", forbidden_fallback):
            try:
                video_fallback.render_seedance_or_h3_fallback(
                    FaceBlockedBackend(),
                    self.prod / "04-frames" / "SH001.jpg",
                    "confirmed Seedance-only request",
                    8,
                    self.prod / "05-shots" / "SH001.mp4",
                )
            except (SeedanceFaceBlock, PermissionError, RuntimeError):
                pass
        self.assertFalse(fallback_calls, "A Seedance-only call implicitly authorized H3")

    def test_unknown_explicit_line_id_is_not_repaired_by_matching_text(self) -> None:
        script = {"scenes": [{"scene_id": "S1", "dialogue": [
            {"line_id": "L1", "speaker_id": "A", "character": "A", "line": "不是我拿的。"}
        ]}]}
        shots = [{"shot_id": "SH001", "dialogue_ref": [
            {"line_id": "UNKNOWN-ID", "speaker_id": "A", "character": "A", "line": "不是我拿的。"}
        ]}]
        before = copy.deepcopy(shots)
        try:
            problems = _repair_writer_lines(shots, script, "S1")
        except (ValueError, PermissionError):
            self.assertEqual(shots, before)
            return
        self.assertTrue(problems)
        self.assertEqual(shots, before)

    def test_same_text_different_speakers_does_not_steal_first_speakers_id(self) -> None:
        script = {"scenes": [{"scene_id": "S1", "dialogue": [
            {"line_id": "B1", "speaker_id": "B", "character": "B", "line": "不是我拿的。"},
            {"line_id": "A1", "speaker_id": "A", "character": "A", "line": "不是我拿的。"},
        ]}]}
        shots = [{"shot_id": "SH001", "dialogue_ref": [{"character": "A", "line": "不是我拿的。"}]}]
        before = copy.deepcopy(shots)
        try:
            problems = _repair_writer_lines(shots, script, "S1")
        except (ValueError, PermissionError):
            self.assertEqual(shots, before)
            return
        if problems:
            self.assertEqual(shots, before)
        else:
            line = shots[0]["dialogue_ref"][0]
            self.assertEqual((line.get("line_id"), line.get("speaker_id")), ("A1", "A"))

    def test_distinct_coverage_does_not_auto_inherit_same_setup(self) -> None:
        first = {"scene_id": "S1", "coverage_type": "single", "scale": "medium", "camera_side": "front", "camera_id": "CAM-A"}
        second = {"scene_id": "S1", "coverage_type": "insert", "scale": "insert", "camera_side": "front", "camera_id": "CAM-A"}
        self.assertFalse(same_setup(first, second))

    def test_distinct_camera_does_not_auto_inherit_same_setup(self) -> None:
        first = {"scene_id": "S1", "coverage_type": "single", "scale": "medium", "camera_side": "front", "camera_id": "CAM-A"}
        second = {"scene_id": "S1", "coverage_type": "single", "scale": "medium", "camera_side": "front", "camera_id": "CAM-B"}
        self.assertFalse(same_setup(first, second))

    def test_frame_description_context_retains_director_time_and_setup_contract(self) -> None:
        shot = {
            "shot_id": "SH001",
            "scene_id": "S1",
            "one_action": "她继续伸手。",
            "setup_id": "SETUP-INSERT-1",
            "camera_id": "CAM-INSERT",
            "t0_phase": "mid",
            "action_timing": [{"from_sec": 0.0, "to_sec": 8.0, "text": "保持动作中段，最后才触到钥匙"}],
        }
        row = frame_desc_shots_ctx([shot])[0]
        missing = [key for key in ("setup_id", "camera_id", "t0_phase", "action_timing") if row.get(key) != shot[key]]
        self.assertFalse(missing, f"Frame-description handoff lost {missing}")

    def test_snapshot_keeps_confirmed_prompt_after_package_rewrite(self) -> None:
        req = vendor_request_from_package(self.prod, package(), keyframes()["SH001"])
        rel = write_confirmed_snapshot(
            self.prod,
            req.fingerprint(),
            episode=1,
            shot_ids=["SH001"],
            requests=[req.to_dict()],
        )
        mutated = package(motion_prompt="新的未确认提示词", target_model="doubao-seedance-2-0-mini-260615")
        live = vendor_request_from_package(self.prod, mutated, keyframes()["SH001"])
        self.assertNotEqual(live.prompt, req.prompt)
        plan = renderer.plan_from_snapshot(self.prod, rel)
        self.assertEqual(plan["shots"][0]["prompt"], req.prompt)
        self.assertEqual(plan["shots"][0]["vendor_request"]["model"], req.model)


if __name__ == "__main__":
    unittest.main()
