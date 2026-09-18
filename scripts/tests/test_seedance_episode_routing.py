#!/usr/bin/env python3
"""Labeled episodes land official clips under 05-shots/<label>/, not 05-shots/SH*.mp4."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.pipeline import episode_shot_dir  # noqa: E402
from render_seedance_packages import (  # noqa: E402
    handoff_markdown_name,
    plan_shot,
    render_seconds_for_package,
)


def _jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (10, 20, 30)).save(path, format="JPEG")


class EpisodeVideoRouting(unittest.TestCase):
    def test_labeled_dest_is_episode_scoped(self) -> None:
        self.assertEqual(episode_shot_dir("ep01-v2"), "05-shots/ep01-v2")
        self.assertEqual(episode_shot_dir(1), "05-shots")
        self.assertEqual(handoff_markdown_name("ep01-v2"), "HANDOFF-VIDEO-EP01-v2.md")
        self.assertEqual(handoff_markdown_name(1), "HANDOFF-VIDEO-EP01.md")

    def test_plan_shot_ep01_v2_does_not_write_unsuffixed_shots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "04-frames" / "ep01-v2" / "SH001.jpg"
            last = prod / "04-frames" / "ep01-v2" / "SH001-last.jpg"
            leftover = prod / "04-frames" / "SH001-last.jpg"
            _jpg(first)
            _jpg(last)
            _jpg(leftover)
            (prod / "05-shots").mkdir()
            (prod / "05-shots" / "SH001.mp4").write_bytes(b"old-lock" * 200)
            pkg = {
                "shot_id": "SH001",
                "gen_mode": "flf2v",
                "keyframe_plan": "first_last",
                "confirmed": True,
                "motion_prompt": "首帧是第0秒，动作尚未发生。本镜只做一件事：纸边发颤。",
                "duration_sec": 1.0,
                "paper_duration_sec": 1.0,
                "render_duration_sec": 4,
                "seedance_min_sec": 4,
                "asset_refs": [],
            }
            frames = {
                "SH001": {
                    "shot_id": "SH001",
                    "first_frame_file": "04-frames/ep01-v2/SH001.jpg",
                    "last_frame_file": "04-frames/ep01-v2/SH001-last.jpg",
                    "qc": {"status": "pass"},
                }
            }
            planned = plan_shot(prod, pkg, frames, {}, episode="ep01-v2")
            self.assertTrue(planned["ok"], planned["errors"])
            self.assertEqual(planned["dest"], "05-shots/ep01-v2/SH001.mp4")
            self.assertEqual(planned["extracted_last"], "05-shots/ep01-v2/SH001-last.jpg")
            self.assertEqual(planned["first_frame"], "04-frames/ep01-v2/SH001.jpg")
            self.assertEqual(planned["last_frame"], "04-frames/ep01-v2/SH001-last.jpg")
            self.assertEqual(planned["duration_sec"], 4)
            self.assertTrue(planned["use_last_frame"])
            self.assertNotEqual(planned["dest"], "05-shots/SH001.mp4")
            self.assertFalse(planned["exists"])

    def test_leftover_29_shot_last_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "04-frames" / "ep01-v2" / "SH001.jpg"
            leftover = prod / "04-frames" / "SH001-last.jpg"
            _jpg(first)
            _jpg(leftover)
            pkg = {
                "shot_id": "SH001",
                "gen_mode": "flf2v",
                "keyframe_plan": "first_last",
                "confirmed": True,
                "motion_prompt": "动一下",
                "duration_sec": 1,
                "render_duration_sec": 4,
                "asset_refs": [],
            }
            frames = {
                "SH001": {
                    "shot_id": "SH001",
                    "first_frame_file": "04-frames/ep01-v2/SH001.jpg",
                    "last_frame_file": "04-frames/SH001-last.jpg",
                    "qc": {"status": "pass"},
                }
            }
            planned = plan_shot(prod, pkg, frames, {}, episode="ep01-v2")
            self.assertFalse(planned["ok"])
            self.assertTrue(any("outside episode folder" in err for err in planned["errors"]))
            self.assertEqual(planned["dest"], "05-shots/ep01-v2/SH001.mp4")

    def test_unlabeled_ep01_still_lands_in_05_shots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "04-frames" / "SH001.jpg"
            _jpg(first)
            pkg = {
                "shot_id": "SH001",
                "gen_mode": "i2v_first",
                "keyframe_plan": "first",
                "confirmed": True,
                "motion_prompt": "动一下",
                "duration_sec": 7,
                "asset_refs": [],
            }
            frames = {
                "SH001": {
                    "shot_id": "SH001",
                    "first_frame_file": "04-frames/SH001.jpg",
                    "qc": {"status": "pass"},
                }
            }
            planned = plan_shot(prod, pkg, frames, {}, episode=1)
            self.assertTrue(planned["ok"], planned["errors"])
            self.assertEqual(planned["dest"], "05-shots/SH001.mp4")
            self.assertEqual(planned["duration_sec"], 7)
            self.assertFalse(planned["use_last_frame"])

    def test_paper_one_second_bumps_to_model_min(self) -> None:
        self.assertEqual(
            render_seconds_for_package(
                {"duration_sec": 1.0, "paper_duration_sec": 1.0, "render_duration_sec": 4, "seedance_min_sec": 4}
            ),
            4,
        )
        self.assertEqual(render_seconds_for_package({"duration_sec": 1.0, "seedance_min_sec": 4}), 4)
        self.assertEqual(render_seconds_for_package({"render_duration_sec": 5, "duration_sec": 5}), 5)


if __name__ == "__main__":
    unittest.main()
