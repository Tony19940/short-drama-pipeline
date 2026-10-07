#!/usr/bin/env python3
"""Actual local rehearsal movies and hash-bound approvals; no cloud requests."""
from __future__ import annotations

import json
import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from director.animatic import (
    animatic_approval_path, animatic_approval_status, animatic_input_fingerprint,
    animatic_rel, build_animatic, require_animatic_approval, write_animatic_approval,
    plan_animatic,
)


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "real movie regression needs FFmpeg")
class AnimaticMediaEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prod = Path(self.temp.name) / "test-show"
        self.prod.mkdir()
        patch = mock.patch.multiple("director.animatic", WIDTH=320, HEIGHT=180, STRIP_H=32)
        patch.start()
        self.addCleanup(patch.stop)
        self.table_file = self.prod / ".pipeline/shot_list.json"
        self.frame = self.prod / "04-frames/SH001.jpg"
        self.frame.parent.mkdir(parents=True)
        Image.new("RGB", (160, 90), "tan").save(self.frame)
        self.table = {"schema": "shot-table-v2", "shots": [{"shot_id": "SH001", "duration_sec": 0.5, "one_action": "伸手"}]}
        write(self.table_file, self.table)

    def approve(self, *, audio_file=None):
        result = build_animatic(self.prod, audio_file=audio_file)
        approval = write_animatic_approval(self.prod, reviewer="human-reviewer", notes="Watched the actual built rehearsal and checked this beat.")
        return result, approval

    def audio_fixture(self):
        path = self.prod / "voice.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(8000)))
        return "voice.wav"

    def test_input_without_movie_cannot_authorize_generation(self):
        with self.assertRaisesRegex(PermissionError, "MP4"):
            write_animatic_approval(self.prod, reviewer="human", notes="Inputs look good.")
        body = write_animatic_approval(self.prod, reviewer="human", notes="Only the input plan was reviewed.", input_only=True)
        self.assertTrue(body["input_only"])
        self.assertFalse(animatic_approval_status(self.prod)["ok"])
        with self.assertRaisesRegex(PermissionError, "input_only"):
            require_animatic_approval(self.prod)

    def test_built_movie_and_review_notes_are_both_required(self):
        build_animatic(self.prod)
        with self.assertRaisesRegex(PermissionError, "notes"):
            write_animatic_approval(self.prod, reviewer="human")
        with self.assertRaisesRegex(PermissionError, "reviewer"):
            write_animatic_approval(self.prod, reviewer="", notes="Watched it.")
        result, approval = self.approve()
        self.assertTrue(approval["media_sha256"])
        self.assertTrue((self.prod / result["sidecar"]).is_file())
        require_animatic_approval(self.prod)

    def test_review_input_change_requires_rebuild_before_approval(self):
        build_animatic(self.prod)
        self.table["shots"][0]["one_action"] = "握住"
        write(self.table_file, self.table)
        with self.assertRaisesRegex(PermissionError, "构建证据已过期"):
            write_animatic_approval(self.prod, reviewer="human", notes="Trying the stale movie.")

    def test_replacing_or_removing_approved_movie_invalidates_approval(self):
        result, _ = self.approve()
        movie = self.prod / result["file"]
        movie.write_bytes(movie.read_bytes() + b"different movie bytes")
        self.assertTrue(animatic_approval_status(self.prod)["stale"])
        with self.assertRaises(PermissionError):
            require_animatic_approval(self.prod)
        movie.unlink()
        self.assertFalse(animatic_approval_status(self.prod)["ok"])

    def test_missing_state_picture_cannot_be_approved(self):
        self.frame.unlink()
        result = build_animatic(self.prod)
        self.assertEqual(result["missing"], ["SH001"])
        with self.assertRaisesRegex(PermissionError, "缺图"):
            write_animatic_approval(self.prod, reviewer="human", notes="Watched a missing-picture card.")

    def test_dialogue_table_cannot_use_silent_rehearsal_as_voice_review(self):
        self.table["shots"][0]["dialogue_ref"] = [{"line": "我来付钱。"}]
        write(self.table_file, self.table)
        build_animatic(self.prod)
        with self.assertRaisesRegex(PermissionError, "静音稿"):
            write_animatic_approval(self.prod, reviewer="human", notes="No voice exists in this movie.")
        self.approve(audio_file=self.audio_fixture())
        require_animatic_approval(self.prod)

    def test_build_and_review_bind_same_audio_input_and_changes_stale(self):
        self.table["sound_required"] = True
        write(self.table_file, self.table)
        result, approval = self.approve(audio_file=self.audio_fixture())
        receipt = json.loads((self.prod / result["sidecar"]).read_text())
        expected = animatic_input_fingerprint(self.prod, audio_file="voice.wav")
        self.assertEqual(receipt["input_fingerprint"], expected)
        self.assertEqual(approval["fingerprint"], expected)
        require_animatic_approval(self.prod)
        audio = self.prod / "voice.wav"
        audio.write_bytes(audio.read_bytes() + b"changed source bytes")
        self.assertTrue(animatic_approval_status(self.prod)["stale"])

    def test_active_registered_revision_uses_its_table_frame_and_movie_path(self):
        write(self.prod / ".pipeline/revisions.json", {
            "schema": "production-revisions-v1", "active": {"ep01": "v3"},
            "revisions": [{"episode_id": "ep01", "revision_id": "v3", "artifact_token": "ep01-v3",
                           "artifacts": {"shot_list.json": ".pipeline/revisions/v3/shots.json"},
                           "frames_dir": "04-frames/custom-v3"}],
        })
        frame = self.prod / "04-frames/custom-v3/SH001.jpg"
        frame.parent.mkdir(parents=True)
        Image.new("RGB", (160, 90), "blue").save(frame)
        write(self.prod / ".pipeline/revisions/v3/shots.json", self.table)
        result, approval = self.approve()
        self.assertEqual(result["episode"], "ep01-v3")
        self.assertIn("ep01-v3.animatic.mp4", result["file"])
        self.assertEqual(result["plan"][0]["image"], "04-frames/custom-v3/SH001.jpg")
        self.assertEqual(approval["episode"], "ep01-v3")
        self.assertEqual(approval["file"], animatic_rel(1, prod=self.prod))
        self.assertTrue(animatic_approval_path(self.prod).name.startswith("ep01-v3"))
        require_animatic_approval(self.prod)

    def test_new_planned_end_has_priority_over_legacy_last(self):
        end = self.prod / "04-frames/SH001-end.jpg"
        last = self.prod / "04-frames/SH001-last.jpg"
        Image.new("RGB", (160, 90), "blue").save(end)
        Image.new("RGB", (160, 90), "red").save(last)
        write(end.with_suffix(".json"), {"frame_role": "planned_end"})
        plan = plan_animatic(self.prod)
        self.assertEqual(plan[-1]["image"], "04-frames/SH001-end.jpg")
        self.assertEqual(plan[-1]["frame_role"], "planned_end")
        self.approve()
        require_animatic_approval(self.prod)

    def test_generated_end_cannot_be_presented_as_a_planned_end(self):
        end = self.prod / "04-frames/SH001-end.jpg"
        Image.new("RGB", (160, 90), "blue").save(end)
        write(end.with_suffix(".json"), {"frame_role": "generated_end"})
        self.assertTrue(plan_animatic(self.prod)[-1]["missing"])
        build_animatic(self.prod)
        with self.assertRaisesRegex(PermissionError, "缺图"):
            write_animatic_approval(self.prod, reviewer="human", notes="Actual end is not a target-design card.")


if __name__ == "__main__":
    unittest.main()
