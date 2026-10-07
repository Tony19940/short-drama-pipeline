#!/usr/bin/env python3
"""Scoped quality evidence regressions; temporary files, no vendor calls."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from director.fingerprint import consume_render_fingerprint, require_task_inputs
from director.pipeline import (
    assert_clips_passed, assert_keyframes_passed, assert_packages_confirmed,
    packages_confirmed, validate_clips, validate_keyframes, validate_packages,
)
from director.qc_layers import evaluate_clip_layers, layers_allow_auto_pass
from director.store import load_approvals, save_approvals


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def qc() -> dict:
    return {key: "pass" for key in (
        "status", "face", "costume", "location", "left_right", "composition",
        "aspect_ratio", "light_matches_spec", "state_match",
    )}


def package(sid="SH001") -> dict:
    return {"shot_id": sid, "gen_mode": "i2v_first", "asset_refs": ["LOC_TEST"],
            "image_prompt": "下午的粉摊", "motion_prompt": "男子伸手付钱", "confirmed": True,
            "target_model": "seedance_2_0_mini", "prompt_language": "zh", "keyframe_plan": "first"}


class QualityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prod = Path(self.temp.name) / "test-show"
        self.prod.mkdir()

    def setup_records(self, *, registered=False, second=False):
        token = "ep01-v3" if registered else ""
        suffix = f".{token}" if token else ""
        self.kf_name = f"keyframes{suffix}.json"
        self.pkg_name = f"gen_packages{suffix}.json"
        self.clip_name = f"clips{suffix}.json"
        if registered:
            write(self.prod / ".pipeline/revisions.json", {
                "schema": "production-revisions-v1", "active": {"ep01": "v3"},
                "revisions": [{"episode_id": "ep01", "revision_id": "v3", "artifact_token": token}],
            })
        shots = [{"shot_id": "SH001", "scale": "wide"}]
        if second:
            shots.append({"shot_id": "SH002", "scale": "wide"})
        write(self.prod / f".pipeline/shot_list{suffix}.json", {"shots": shots})
        rel = f"04-frames/{token + '/' if token else ''}SH001.jpg"
        path = self.prod / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reviewed first picture")
        self.first_rel = rel
        frame = {"shot_id": "SH001", "first_frame_file": rel, "qc": qc()}
        if registered:
            frame["review"] = {"media_hashes": {rel: hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.frames = {"reviewed_by": "human-reviewer", "keyframes": [frame]}
        self.packages = {"packages": [package()]}
        write(self.prod / f".pipeline/{self.pkg_name}", self.packages)
        write(self.prod / f".pipeline/{self.kf_name}", self.frames)
        return frame

    def test_missing_quality_records_never_count_as_pass(self):
        write(self.prod / ".pipeline/shot_list.json", {"shots": [{"shot_id": "SH001"}]})
        for assertion in (assert_packages_confirmed, assert_keyframes_passed, assert_clips_passed):
            with self.subTest(assertion=assertion.__name__), self.assertRaisesRegex(PermissionError, "missing"):
                assertion(self.prod)

    def test_scoped_gate_checks_selected_shots_without_requiring_entire_episode(self):
        self.setup_records(second=True)
        with self.assertRaisesRegex(PermissionError, "missing shots: SH002"):
            assert_keyframes_passed(self.prod)
        assert_packages_confirmed(self.prod, selected_shot_ids=["SH001"])
        assert_keyframes_passed(self.prod, selected_shot_ids=["SH001"])
        with self.assertRaisesRegex(PermissionError, "not in the current shot_list"):
            assert_keyframes_passed(self.prod, selected_shot_ids=["SH999"])

    def test_duplicate_or_incomplete_rows_are_rejected(self):
        data = {"packages": [package(), package()]}
        errors = validate_packages(data, expected_shot_ids=["SH001", "SH002"])
        self.assertTrue(any("duplicate" in err for err in errors))
        self.assertTrue(any("missing shots: SH002" in err for err in errors))
        self.assertFalse(packages_confirmed({"packages": [dict(package(), confirmed="true")]}))

    def test_registered_revision_never_accepts_legacy_only_approval(self):
        self.setup_records(registered=True)
        legacy = copy.deepcopy(self.frames)
        write(self.prod / ".pipeline/keyframes.json", legacy)
        (self.prod / f".pipeline/{self.kf_name}").unlink()
        with self.assertRaisesRegex(PermissionError, "missing keyframes"):
            assert_keyframes_passed(self.prod)

    def test_registered_frame_reviews_bind_current_bytes(self):
        self.setup_records(registered=True)
        assert_keyframes_passed(self.prod)
        (self.prod / self.first_rel).write_bytes(b"new unreviewed picture")
        with self.assertRaisesRegex(PermissionError, "hash is stale"):
            assert_keyframes_passed(self.prod)

    def test_first_and_last_need_separate_review_binding(self):
        frame = self.setup_records(registered=True)
        last = self.first_rel.replace(".jpg", "-last.jpg")
        (self.prod / last).write_bytes(b"last picture")
        frame["last_frame_file"] = last
        frame["qc"]["out_to_readable"] = "pass"
        self.packages["packages"][0]["keyframe_plan"] = "first_last"
        errors = validate_keyframes(self.frames, packages=self.packages, prod=self.prod, require_media_binding=True)
        self.assertTrue(any("last_frame review is not bound" in err for err in errors), errors)

    def test_clip_layers_cannot_hide_failure_behind_top_level_pass(self):
        clip = self.prod / "05-shots/SH001.mp4"
        clip.parent.mkdir()
        clip.write_bytes(b"test clip")
        item = {"shot_id": "SH001", "video_file": "05-shots/SH001.mp4", "qc": {"status": "pass"},
                "review": {"reviewed_by": "human", "media_hash": hashlib.sha256(clip.read_bytes()).hexdigest()},
                "layers": {"technical": {"status": "pass"}, "visual": {"status": "pass"}, "performance": {"status": "unknown"}}}
        data = {"clips": [item]}
        self.assertEqual(validate_clips(data, prod=self.prod, require_media_binding=True), [])
        item["required_layers"] = ["performance"]
        self.assertTrue(validate_clips(data, prod=self.prod, require_media_binding=True))
        item["layers"]["performance"]["status"] = "pass"
        self.assertEqual(validate_clips(data, prod=self.prod, require_media_binding=True), [])
        item["layers"]["technical"]["status"] = "fail"
        self.assertTrue(validate_clips(data, prod=self.prod, require_media_binding=True))

    def test_technical_failure_prevents_helper_pass_with_valid_visual_review(self):
        layers = evaluate_clip_layers(technical_ok=False, visual_review={"status": "pass", "media_hash": "abc"}, media_hash="abc")
        self.assertFalse(layers_allow_auto_pass(layers))

    def test_pending_text_and_malformed_record_shapes_fail_without_exception(self):
        pending = {"clips": [{"shot_id": "SH001", "video_file": "05-shots/SH001.mp4", "qc": {"status": "pass"}, "review": "pending episode listening"}]}
        self.assertTrue(any("pending/invalid" in error for error in validate_clips(pending, require_media_binding=True)))
        for data in ([], {"clips": "pending"}, {"clips": ["SH001"]}, {"clips": [{"shot_id": "SH001", "qc": "pass", "generation_budget": "eight"}]}):
            with self.subTest(data=data):
                self.assertTrue(validate_clips(data))
        self.assertTrue(validate_keyframes({"keyframes": ["SH001"]}))
        self.assertTrue(validate_packages({"packages": "pending"}))

    def test_generation_uses_the_reviewed_request_frame_not_unused_shot_default(self):
        self.setup_records(registered=True)
        require_task_inputs(self.prod, [{"id": "SH001", "frame": "04-frames/unused.jpg"}])

    def test_clearing_review_after_prepare_blocks_consume(self):
        self.setup_records()
        self.frames["keyframes"][0]["qc"]["status"] = "fail"
        write(self.prod / ".pipeline/keyframes.json", self.frames)
        save_approvals(self.prod, {"render": {"fingerprint": "prepared", "shot_ids": ["SH001"], "consumed": False}})
        with mock.patch("director.fingerprint._selected", return_value=[{"id": "SH001"}]):
            with self.assertRaisesRegex(PermissionError, "keyframe not passed"):
                consume_render_fingerprint(self.prod, "prepared", ["SH001"])
        self.assertFalse(load_approvals(self.prod)["render"]["consumed"])


if __name__ == "__main__":
    unittest.main()
