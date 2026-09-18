#!/usr/bin/env python3
"""Clip QC without calling ffmpeg."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_shot_clip import check_clip, scene_cut_count  # noqa: E402
from director.pipeline import write_artifact  # noqa: E402


class _Proc:
    def __init__(self, text: str = "", code: int = 0) -> None:
        self.stderr = text
        self.stdout = ""
        self.returncode = code


class CheckShotClipTests(unittest.TestCase):
    def test_scene_cut_count_parses_showinfo(self) -> None:
        def runner(args, **kwargs):
            return _Proc("n: 0 scene_score: 0.51\nn: 12 scene_score: 0.44")

        self.assertEqual(scene_cut_count(Path("/tmp/x.mp4"), runner=runner), 2)

    def test_internal_cut_fails(self) -> None:
        def runner(args, **kwargs):
            return _Proc("scene_score: 0.9")

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            clip = prod / "05-shots" / "SH001.mp4"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"fake")
            result = check_clip(prod, "SH001", runner=runner, extract=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["scene_cuts"], 1)
        self.assertTrue(any("internal scene cut" in e for e in result["errors"]), result)

    def test_clean_clip_extracts_last_and_warns_feet(self) -> None:
        def runner(args, **kwargs):
            if "-frames:v" in args:
                dest = Path(args[-1])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"jpeg")
            return _Proc("")

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            clip = prod / "05-shots" / "SH001.mp4"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"fake")
            write_artifact(
                prod,
                "frame_descriptions.json",
                {"items": [{"shot_id": "SH001", "forbidden": ["脚", "汉字"]}]},
            )
            result = check_clip(prod, "SH001", runner=runner, extract=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["last_frame"], "08-qc/clips/SH001-last.jpg")
        self.assertTrue(any("脚/鞋" in w for w in result["warnings"]), result)


if __name__ == "__main__":
    unittest.main()
