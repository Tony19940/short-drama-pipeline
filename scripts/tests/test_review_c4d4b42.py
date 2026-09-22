#!/usr/bin/env python3
"""Regressions from the c4d4b42 review. No vendor calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.animatic import (  # noqa: E402
    animatic_approval_path,
    animatic_approval_status,
    plan_animatic,
    write_animatic_approval,
)
from director.jobs import _trim_segment_av, assemble_episode  # noqa: E402
from director.pipeline import read_artifact, write_artifact  # noqa: E402
from director.scene_plan import performance_intent_of  # noqa: E402
from director.takes import (  # noqa: E402
    EditSegment,
    record_render_take,
    resolve_segment_takes,
    select_take,
)


class StrictTakeRefs(unittest.TestCase):
    def test_unknown_picture_and_audio_do_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            dest = prod / "05-shots" / "SH001.mp4"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"\x00\x00\x00\x18ftypisomtake")
            take = record_render_take(prod, shot_id="SH001", dest=dest, request_hash="a" * 32, task_id="t", episode=1)
            select_take(prod, "SH001", take.take_id, 1)
            with self.assertRaises(PermissionError):
                resolve_segment_takes(prod, EditSegment("s", "missing-picture", "SH001", 0, 1), 1)
            with self.assertRaises(PermissionError):
                resolve_segment_takes(
                    prod,
                    EditSegment("s", take.take_id, "SH001", 0, 1, audio_take_id="missing-audio"),
                    1,
                )
            with self.assertRaises(PermissionError):
                resolve_segment_takes(prod, EditSegment("s", take.take_id, "SH099", 0, 1), 1)
            with self.assertRaises(PermissionError):
                select_take(prod, "SH001", take.take_id, 2)

    def test_record_does_not_rewrite_a_ready_cut(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "05-shots" / "SH001.mp4"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"\x00\x00\x00\x18ftypisom-old")
            old = record_render_take(prod, shot_id="SH001", dest=first, request_hash="r" * 32, task_id="old", episode=1)
            write_artifact(
                prod,
                "cut.json",
                {
                    "status": "ready",
                    "timeline": [{"segment_id": "seg-1", "shot_id": "SH001", "take_id": old.take_id, "used": True}],
                    "dropped_shot_ids": [],
                    "final_file": "06-export/ep01.mp4",
                },
            )
            first.write_bytes(b"\x00\x00\x00\x18ftypisom-new")
            record_render_take(prod, shot_id="SH001", dest=first, request_hash="r" * 32, task_id="new", episode=1, new_attempt=True)
            cut = read_artifact(prod, "cut.json")
            self.assertEqual(cut["timeline"][0]["take_id"], old.take_id)
            self.assertEqual(cut["status"], "ready")


class AudioDoesNotGoSilent(unittest.TestCase):
    def test_bad_audio_is_an_error(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg required")
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            video = prod / "v.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=black:s=160x90:r=24:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            audio = prod / "bad.mp4"
            audio.write_bytes(b"\x00\x00\x00\x18ftyp" + b"\x00" * 2000)
            with self.assertRaises(RuntimeError):
                _trim_segment_av(
                    video_src=video,
                    video_in=0,
                    video_out=1,
                    audio_src=audio,
                    audio_in=0,
                    audio_out=1,
                    dest=prod / "out.mp4",
                    audio_mode="source",
                )
            self.assertFalse((prod / "out.mp4").exists())


class BeatRefsAndRehearsal(unittest.TestCase):
    def test_string_beat_ids_do_not_crash(self) -> None:
        intent = performance_intent_of({"beat_ids": ["b1", "b2"], "covers": ["b1"]})
        self.assertEqual(intent["beat_ids"], ["b1", "b2"])
        scene = {"scene_id": "SC", "beats": [{"beat_id": "b1", "text": "伸手"}]}
        bound = performance_intent_of({"beat_ids": ["b1"]}, scene)
        self.assertEqual(bound["beat_ids"], ["b1"])
        with self.assertRaises(ValueError):
            performance_intent_of({"beat_ids": ["missing"]}, scene)

    def test_absolute_beats_keep_gaps_and_t0_is_first(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "04-frames").mkdir(parents=True)
            Image.new("RGB", (40, 20), (1, 1, 1)).save(prod / "04-frames" / "SH001.jpg")
            Image.new("RGB", (40, 20), (9, 9, 9)).save(prod / "04-frames" / "SH001-last.jpg")
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{
                        "shot_id": "SH001",
                        "duration_sec": 8,
                        "one_action": "交出钥匙",
                        "action_timing": [
                            {"from_sec": 2, "to_sec": 4, "text": "A"},
                            {"from_sec": 6, "to_sec": 8, "text": "B"},
                        ],
                    }],
                },
            )
            plan = plan_animatic(prod, 1)
            self.assertEqual([(item["from_sec"], item["to_sec"], item["beat"]) for item in plan], [
                (0.0, 2.0, "空档"),
                (2.0, 4.0, "A"),
                (4.0, 6.0, "空档"),
                (6.0, 8.0, "B"),
            ])
            self.assertEqual(plan[0]["part"], "first")
            self.assertNotEqual(plan[1]["image"], "04-frames/SH001-last.jpg")
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{
                        "shot_id": "SH001",
                        "duration_sec": 8,
                        "one_action": "交出钥匙",
                        "action_timing": [{"from_sec": 0, "to_sec": 8, "text": "一直伸手"}],
                    }],
                },
            )
            single = plan_animatic(prod, 1)
            self.assertEqual(len(single), 1)
            self.assertEqual(single[0]["part"], "first")
            self.assertEqual(single[0]["image"], "04-frames/SH001.jpg")

    def test_beat_text_change_stales_approval_and_label_path_works(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "04-frames").mkdir(parents=True)
            Image.new("RGB", (40, 20)).save(prod / "04-frames" / "SH001.jpg")
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{
                        "shot_id": "SH001",
                        "duration_sec": 4,
                        "one_action": "听",
                        "action_timing": [{"from_sec": 0, "to_sec": 4, "text": "交出钥匙"}],
                    }],
                },
            )
            write_animatic_approval(prod, 1, reviewer="tonyteacher")
            self.assertTrue(animatic_approval_status(prod, 1)["ok"])
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{
                        "shot_id": "SH001",
                        "duration_sec": 4,
                        "one_action": "听",
                        "action_timing": [{"from_sec": 0, "to_sec": 4, "text": "藏起钥匙"}],
                    }],
                },
            )
            self.assertTrue(animatic_approval_status(prod, 1)["stale"])
            path = animatic_approval_path(prod, "ep01-v2")
            self.assertTrue(str(path).endswith("ep01-v2.approval.json"))
            write_artifact(
                prod,
                "shot_list.ep01-v2.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{"shot_id": "SH001", "duration_sec": 4, "one_action": "听"}],
                },
            )
            (prod / "04-frames" / "ep01-v2").mkdir(parents=True)
            Image.new("RGB", (40, 20)).save(prod / "04-frames" / "ep01-v2" / "SH001.jpg")
            body = write_animatic_approval(prod, "ep01-v2", reviewer="tonyteacher")
            self.assertEqual(body["episode"], "ep01-v2")
            self.assertTrue(animatic_approval_status(prod, "ep01-v2")["ok"])


class AssembleRefusesBadTake(unittest.TestCase):
    def test_missing_take_does_not_export_another(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            dest = prod / "05-shots" / "SH001.mp4"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"\x00\x00\x00\x18ftypisomxxxx")
            take = record_render_take(prod, shot_id="SH001", dest=dest, request_hash="z" * 32, task_id="z", episode=1)
            write_artifact(
                prod,
                "cut.json",
                {
                    "timeline": [{
                        "shot_id": "SH001",
                        "take_id": "does-not-exist",
                        "in_point": 0,
                        "out_point": 1,
                        "used": True,
                    }],
                    "dropped_shot_ids": [],
                    "final_file": "06-export/ep01.mp4",
                    "status": "draft",
                },
            )
            with self.assertRaises(PermissionError):
                assemble_episode(prod, 1)
            self.assertFalse((prod / "06-export" / "ep01.mp4").exists())
            self.assertTrue((prod / take.dest).is_file())


if __name__ == "__main__":
    unittest.main()
