#!/usr/bin/env python3
"""Phase A: multiple Takes, EditSegment export, A/V trim, episode labels."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.jobs import assemble_episode  # noqa: E402
from director.pipeline import default_cut_from_specs, write_artifact  # noqa: E402
from director.takes import (  # noqa: E402
    episode_export_rel,
    record_render_take,
    select_take,
    selected_take,
    take_media_file,
    takes_for_shot,
)


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _color_mp4(dest: Path, color: str, seconds: float = 2) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s=320x180:r=24:d={seconds}",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=" + str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(dest),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TakeIdentity(unittest.TestCase):
    def test_resume_keeps_same_take_and_retry_adds_another(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "05-shots" / "SH001.mp4"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"\x00\x00\x00\x18ftypisomtake-a")
            a = record_render_take(
                prod,
                shot_id="SH001",
                dest=first,
                request_hash="abc" * 16,
                task_id="cgt-1",
                episode=1,
                new_attempt=False,
            )
            first.write_bytes(b"\x00\x00\x00\x18ftypisomtake-a2")
            resumed = record_render_take(
                prod,
                shot_id="SH001",
                dest=first,
                request_hash="abc" * 16,
                task_id="cgt-1",
                episode=1,
                new_attempt=False,
            )
            self.assertEqual(resumed.take_id, a.take_id)
            self.assertEqual(resumed.attempt_id, a.attempt_id)
            first.write_bytes(b"\x00\x00\x00\x18ftypisomtake-b")
            b = record_render_take(
                prod,
                shot_id="SH001",
                dest=first,
                request_hash="abc" * 16,
                task_id="cgt-2",
                episode=1,
                new_attempt=True,
            )
            self.assertNotEqual(b.take_id, a.take_id)
            self.assertNotEqual(b.attempt_id, a.attempt_id)
            self.assertEqual(b.request_hash, a.request_hash)
            rows = takes_for_shot(prod, "SH001", 1)
            self.assertEqual({row.take_id for row in rows}, {a.take_id, b.take_id})
            self.assertTrue((prod / a.dest).is_file())
            self.assertTrue((prod / b.dest).is_file())
            self.assertEqual(selected_take(prod, "SH001", 1).take_id, b.take_id)


class AssembleFromTakes(unittest.TestCase):
    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg required")
    def test_switching_take_changes_export_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            black = prod / "05-shots" / "SH001.mp4"
            _color_mp4(black, "black", 2)
            first = record_render_take(
                prod, shot_id="SH001", dest=black, request_hash="r1" * 16, task_id="t1", episode=1
            )
            white = prod / "05-shots" / "SH001-white.mp4"
            _color_mp4(white, "white", 2)
            second = record_render_take(
                prod,
                shot_id="SH001",
                dest=white,
                request_hash="r1" * 16,
                task_id="t2",
                episode=1,
                new_attempt=True,
            )
            write_artifact(
                prod,
                "cut.json",
                {
                    "timeline": [{
                        "shot_id": "SH001",
                        "take_id": first.take_id,
                        "in_point": 0,
                        "out_point": 1,
                        "used": True,
                    }],
                    "dropped_shot_ids": [],
                    "final_file": "06-export/ep01.mp4",
                },
            )
            out_a = assemble_episode(prod, 1)
            hash_a = _file_hash(prod / out_a["output"])
            self.assertEqual(out_a["takes"], [first.take_id])
            select_take(prod, "SH001", second.take_id, 1)
            out_b = assemble_episode(prod, 1)
            hash_b = _file_hash(prod / out_b["output"])
            self.assertEqual(out_b["takes"], [second.take_id])
            self.assertNotEqual(hash_a, hash_b)

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg required")
    def test_audio_from_other_take_does_not_need_new_video(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            picture = prod / "05-shots" / "SH002.mp4"
            _color_mp4(picture, "red", 2)
            pic = record_render_take(
                prod, shot_id="SH002", dest=picture, request_hash="p" * 32, task_id="tp", episode=1
            )
            sound = prod / "05-shots" / "SH001.mp4"
            _color_mp4(sound, "blue", 2)
            aud = record_render_take(
                prod, shot_id="SH001", dest=sound, request_hash="s" * 32, task_id="ts", episode=1
            )
            write_artifact(
                prod,
                "cut.json",
                {
                    "timeline": [{
                        "shot_id": "SH002",
                        "take_id": pic.take_id,
                        "audio_take_id": aud.take_id,
                        "in_sec": 0,
                        "out_sec": 1,
                        "audio_in_sec": 0.2,
                        "audio_out_sec": 1.2,
                        "used": True,
                    }],
                    "dropped_shot_ids": [],
                    "final_file": "06-export/ep01.mp4",
                },
            )
            result = assemble_episode(prod, 1)
            self.assertTrue((prod / result["output"]).is_file())
            self.assertEqual(take_media_file(prod, pic).stat().st_mtime, (prod / pic.dest).stat().st_mtime)

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg required")
    def test_episode_label_export_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            clip = prod / "05-shots" / "ep02" / "SH001.mp4"
            _color_mp4(clip, "green", 2)
            take = record_render_take(
                prod, shot_id="SH001", dest=clip, request_hash="e" * 32, task_id="te", episode=2
            )
            write_artifact(
                prod,
                "cut.ep02.json",
                {
                    "episode": "ep02",
                    "timeline": [{
                        "shot_id": "SH001",
                        "take_id": take.take_id,
                        "in_point": 0,
                        "out_point": 1,
                        "used": True,
                    }],
                    "dropped_shot_ids": [],
                    "final_file": episode_export_rel(2),
                },
            )
            result = assemble_episode(prod, 2)
            self.assertEqual(result["output"], "06-export/ep02.mp4")
            self.assertTrue((prod / "06-export/ep02.mp4").is_file())
            self.assertFalse((prod / "06-export/ep01.mp4").exists())

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg required")
    def test_same_take_twice_does_not_clobber_work_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            clip = prod / "05-shots" / "SH001.mp4"
            _color_mp4(clip, "gray", 3)
            take = record_render_take(
                prod, shot_id="SH001", dest=clip, request_hash="g" * 32, task_id="tg", episode=1
            )
            write_artifact(
                prod,
                "cut.json",
                {
                    "timeline": [
                        {"shot_id": "SH001", "take_id": take.take_id, "in_sec": 0, "out_sec": 1, "used": True},
                        {"shot_id": "SH001", "take_id": take.take_id, "in_sec": 1, "out_sec": 2, "used": True},
                    ],
                    "dropped_shot_ids": [],
                    "final_file": "06-export/ep01.mp4",
                },
            )
            result = assemble_episode(prod, 1)
            self.assertTrue((prod / result["output"]).is_file())
            work = list((prod / ".director" / "cut-work" / "1").glob("*.mp4"))
            named = [path for path in work if path.stem.endswith(("-v",)) is False]
            self.assertGreaterEqual(len([p for p in work if not p.name.endswith("-v.mp4")]), 2)


class DefaultCutUsesSelectedTake(unittest.TestCase):
    def test_default_cut_writes_take_id_and_episode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            dest = prod / "05-shots" / "SH001.mp4"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"\x00\x00\x00\x18ftypisomxxxx")
            take = record_render_take(
                prod, shot_id="SH001", dest=dest, request_hash="q" * 32, task_id="tq", episode=1
            )
            write_artifact(prod, "shot_specs.json", {"shot_specs": [{"shot_id": "SH001", "duration_sec": 4}]})
            cut = default_cut_from_specs(prod, ["SH001"], 1)
            self.assertEqual(cut["timeline"][0]["take_id"], take.take_id)
            self.assertEqual(cut["final_file"], "06-export/ep01.mp4")
            self.assertEqual(cut["episode"], "1")


if __name__ == "__main__":
    unittest.main()
