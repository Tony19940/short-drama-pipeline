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

from video_backends.wan3 import Wan3  # noqa: E402
from director.video_profiles import get_profile  # noqa: E402


def _image(folder: str, name: str = "first.jpg") -> Path:
    path = Path(folder) / name
    path.write_bytes(b"fakejpg")
    return path


class Wan3Contract(unittest.TestCase):
    def test_profile_is_chinese_and_xor_refs(self) -> None:
        profile = get_profile("wan3.0-video")
        self.assertEqual(profile["id"], "wan_3")
        self.assertEqual(profile["prompt_language"], "zh")
        self.assertTrue(profile["first_last_frame"])
        self.assertEqual(profile["max_ref_images"], 10)
        self.assertEqual(profile["min_shot_sec"], 2)
        self.assertEqual(profile["max_shot_sec"], 30)

    def test_i2v_keeps_first_frame_and_drops_refs(self) -> None:
        env = {
            "DASHSCOPE_API_KEY": "test-key",
            "DASHSCOPE_WORKSPACE_ID": "ws-test",
            "DASHSCOPE_REGION": "cn-beijing",
            "WAN_MODEL": "wan3.0-video",
            "WAN_RESOLUTION": "720P",
            "WAN_AUDIO": "0",
            "WAN_PROMPT_EXTEND": "0",
            "WAN_WATERMARK": "0",
            "WAN_UPLOAD_OSS": "0",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            ref = _image(tmp, "face.jpg")
            backend = Wan3()
            payload = backend.build_payload(image, "琳抬眼", 4, refs=[ref], mode="i2v")
            types = [item.get("type") for item in payload["input"]["media"]]
            params = payload["parameters"]
            self.assertEqual(payload["model"], "wan3.0-video")
            self.assertEqual(types, ["first_frame"])
            self.assertNotIn("reference_image", types)
            self.assertTrue(payload["input"]["media"][0]["url"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(params["duration"], 4)
            self.assertEqual(params["resolution"], "720P")
            self.assertEqual(params["ratio"], "adaptive")
            self.assertFalse(params["audio"])
            self.assertFalse(params["prompt_extend"])
            self.assertFalse(params["watermark"])

    def test_flf_adds_last_frame_without_refs(self) -> None:
        env = {"DASHSCOPE_API_KEY": "test-key", "WAN_UPLOAD_OSS": "0"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            last = _image(tmp, "last.jpg")
            ref = _image(tmp, "face.jpg")
            backend = Wan3()
            payload = backend.build_payload(image, "落幅停住", 5, refs=[ref], mode="flf", last_frame=last)
            types = [item.get("type") for item in payload["input"]["media"]]
            self.assertEqual(types, ["first_frame", "last_frame"])

    def test_refuse_out_of_range_seconds_and_t2v(self) -> None:
        env = {"DASHSCOPE_API_KEY": "test-key", "WAN_UPLOAD_OSS": "0"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            image = _image(tmp)
            backend = Wan3()
            with self.assertRaises(RuntimeError) as ctx:
                backend.build_payload(image, "prompt", 1, mode="i2v")
            self.assertIn("秒数 1 不在 wan3.0-video 档内 [2,30]", str(ctx.exception))
            with self.assertRaises(RuntimeError) as ctx:
                backend.build_payload(image, "prompt", 4, mode="t2v")
            self.assertEqual(str(ctx.exception), "Wan 成片路径不能走文生视频")
            dest = Path(tmp) / "SH027.mp4"
            backend.submit = lambda *a, **k: self.fail("must not submit")  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                backend.render(image, "prompt", 31, dest)
            self.assertTrue(str(ctx.exception).startswith("SH027 秒数 31 不在 "))
            self.assertFalse(dest.with_suffix(".mp4.wan-task.json").exists())


if __name__ == "__main__":
    unittest.main()
