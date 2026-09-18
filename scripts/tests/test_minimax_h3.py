#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from video_backends.minimax_h3 import MiniMaxH3  # noqa: E402


def _image(folder: str, name: str = "first.jpg") -> Path:
    path = Path(folder) / name
    path.write_bytes(b"fakejpg")
    return path


class MiniMaxH3Contract(unittest.TestCase):
    def test_i2v_keeps_first_frame_and_drops_refs(self) -> None:
        env = {
            "MINIMAX_API_KEY": "test-key",
            "MINIMAX_BASE_URL": "https://api.minimaxi.com",
            "MINIMAX_MODEL": "MiniMax-H3",
            "MINIMAX_RESOLUTION": "768P",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            ref = _image(tmp, "face.jpg")
            backend = MiniMaxH3()
            payload = backend.build_payload(image, "琳抬眼", 4, refs=[ref], mode="i2v")
            roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
            self.assertEqual(payload["model"], "MiniMax-H3")
            self.assertEqual(payload["duration"], 4)
            self.assertEqual(payload["resolution"], "768P")
            self.assertFalse(payload["aigc_watermark"])
            self.assertEqual(roles, ["first_frame"])
            self.assertNotIn("reference_image", roles)
            self.assertNotIn("ratio", payload)
            self.assertEqual(backend.estimate_cny(4), 2.0)

    def test_flf_adds_last_frame_without_refs(self) -> None:
        env = {"MINIMAX_API_KEY": "test-key"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            last = _image(tmp, "last.jpg")
            ref = _image(tmp, "face.jpg")
            backend = MiniMaxH3()
            payload = backend.build_payload(image, "落幅停住", 5, refs=[ref], mode="flf", last_frame=last)
            roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
            self.assertEqual(roles, ["first_frame", "last_frame"])

    def test_refuse_out_of_range_seconds_and_t2v(self) -> None:
        env = {"MINIMAX_API_KEY": "test-key"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            backend = MiniMaxH3()
            with self.assertRaises(RuntimeError) as ctx:
                backend.build_payload(image, "prompt", 3, mode="i2v")
            self.assertIn("秒数 3 不在 MiniMax-H3 档内 [4,15]", str(ctx.exception))
            with self.assertRaises(RuntimeError) as ctx:
                backend.build_payload(image, "prompt", 4, mode="t2v")
            self.assertEqual(str(ctx.exception), "H3 成片路径不能走文生视频")
            dest = Path(tmp) / "SH027.mp4"
            backend.submit = lambda *a, **k: self.fail("must not submit")  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                backend.render(image, "prompt", 16, dest)
            self.assertTrue(str(ctx.exception).startswith("SH027 秒数 16 不在 "))
            self.assertFalse(dest.with_suffix(".mp4.h3-task.json").exists())

    def test_h3_max_rejects_4s_and_2k(self) -> None:
        env = {
            "MINIMAX_API_KEY": "test-key",
            "MINIMAX_MODEL": "MiniMax-H3-Max",
            "MINIMAX_RESOLUTION": "2K",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            backend = MiniMaxH3()
            self.assertEqual(backend.min_duration, 5)
            with self.assertRaises(RuntimeError):
                backend.build_payload(image, "prompt", 4, mode="i2v")
            with self.assertRaises(RuntimeError) as ctx:
                backend._normalize_resolution("2K")
            self.assertIn("2K", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
