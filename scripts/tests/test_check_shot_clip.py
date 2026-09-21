#!/usr/bin/env python3
"""Clip QC: mocked logs plus real FFmpeg fixtures."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_shot_clip import SceneCutError, check_clip, scene_cut_count, scene_cuts  # noqa: E402
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

    def test_scene_cut_uses_metadata_print_filter(self) -> None:
        seen: list[list[str]] = []

        def runner(args, **kwargs):
            seen.append(list(args))
            return _Proc("frame:1 pts_time:1.000\nlavfi.scene_score=0.88\n")

        self.assertEqual(scene_cut_count(Path("/tmp/x.mp4"), runner=runner), 1)
        self.assertTrue(any("metadata=mode=print:key=lavfi.scene_score" in part for part in seen[0]), seen)

    def test_decode_failure_is_an_error(self) -> None:
        def runner(args, **kwargs):
            return _Proc("Invalid data found when processing input", code=183)

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            clip = prod / "05-shots" / "SH001.mp4"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"not-a-video")
            result = check_clip(prod, "SH001", runner=runner, extract=False)
        self.assertFalse(result["ok"])
        self.assertTrue(any("could not inspect" in e for e in result["errors"]), result)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required for real media fixtures")
class RealSceneCutFixtures(unittest.TestCase):
    def _run(self, args: list[str]) -> None:
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-1500:] or proc.stdout[-1500:])

    def _write(self, dest: Path, *inputs: str, extra: list[str] | None = None) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for src in inputs:
            cmd += ["-f", "lavfi", "-i", src]
        cmd += extra or []
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
        self._run(cmd)
        return dest

    def test_hard_cut_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = self._write(
                Path(tmp) / "hard.mp4",
                "color=c=black:s=160x90:r=24:d=1",
                "color=c=white:s=160x90:r=24:d=1",
                extra=["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"],
            )
            self.assertGreaterEqual(scene_cut_count(dest), 1)

    def test_solid_clip_has_no_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = self._write(Path(tmp) / "solid.mp4", "color=c=black:s=160x90:r=24:d=2")
            self.assertEqual(scene_cut_count(dest), 0)

    def test_flash_is_detected_as_scene_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = self._write(
                Path(tmp) / "flash.mp4",
                "color=c=black:s=160x90:r=24:d=1",
                "color=c=white:s=160x90:r=24:d=0.04",
                "color=c=black:s=160x90:r=24:d=1",
                extra=["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]"],
            )
            self.assertGreaterEqual(scene_cut_count(dest), 1)

    def test_slow_fade_is_not_a_hard_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fade.mp4"
            self._run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=2",
                    "-vf", "fade=t=in:st=0:d=2:color=white",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
                ]
            )
            self.assertEqual(scene_cut_count(dest), 0)

    def test_garbage_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bad.mp4"
            dest.write_bytes(b"not a video")
            with self.assertRaises(SceneCutError):
                scene_cuts(dest)


if __name__ == "__main__":
    unittest.main()
