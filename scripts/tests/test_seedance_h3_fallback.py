#!/usr/bin/env python3
"""Official Seedance face-block → MiniMax-H3 fallback. No live API."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_seedance_frame import FACE_BLOCK_CODE, classify_create  # noqa: E402
from director.video_fallback import (  # noqa: E402
    NO_H3_KEY,
    OFFICIAL_SIZE,
    official_h3_fallback,
    render_seedance_or_h3_fallback,
    scale_h3_cmd,
    write_clip_record,
)
from video_backends.seedance_ark import SeedanceArk, SeedanceFaceBlock  # noqa: E402


def _image(folder: str, name: str = "first.jpg") -> Path:
    path = Path(folder) / name
    path.write_bytes(b"fakejpg")
    return path


class ScaleAndRecord(unittest.TestCase):
    def test_scale_command_is_1280x720_lanczos(self) -> None:
        src = Path("/tmp/in.mp4")
        dest = Path("/tmp/out.mp4")
        cmd = scale_h3_cmd(src, dest)
        self.assertIn("1280:720", " ".join(cmd))
        self.assertIn("lanczos", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=1280:720:flags=lanczos")
        self.assertEqual(cmd[-1], str(dest))

    def test_clip_record_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "SH010.mp4"
            dest.write_bytes(b"x" * 2048)
            body = write_clip_record(dest)
            self.assertEqual(body["backend"], "minimax_h3")
            self.assertEqual(body["fallback_from"], "seedance")
            self.assertEqual(body["scaled_to"], "1280x720")
            self.assertTrue(dest.with_suffix(dest.suffix + ".clip.json").exists())


class OfficialH3Fallback(unittest.TestCase):
    def test_missing_key_is_clear_error(self) -> None:
        env = {"MINIMAX_API_KEY": ""}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIMAX_API_KEY", None)
            dest = Path(tmp) / "05-shots" / "SH010.mp4"
            dest.parent.mkdir()
            with self.assertRaises(RuntimeError) as ctx:
                official_h3_fallback(_image(tmp), "动一下", 4, dest, render_fn=lambda *a, **k: None)
            self.assertEqual(str(ctx.exception), NO_H3_KEY)

    def test_uses_official_h3_never_compshare(self) -> None:
        env = {"MINIMAX_API_KEY": "test-key", "COMPSHARE_API_KEY": "sk-ml-test"}
        called = {"h3": 0, "compshare": 0, "scale": []}

        def fake_h3(image, prompt, seconds, dest, **kwargs):
            called["h3"] += 1
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"h3" * 2000)
            self.assertNotIn("compshare", str(dest).lower())

        def fake_scale(src, dest):
            called["scale"].append((src, dest))
            dest.write_bytes(b"scaled" * 400)
            return scale_h3_cmd(src, dest)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            dest = Path(tmp) / "05-shots" / "SH010.mp4"
            dest.parent.mkdir()
            with mock.patch("video_backends.compshare_h3.CompShareH3") as comp:
                comp.side_effect = AssertionError("CompShare must not be selected")
                record = official_h3_fallback(
                    _image(tmp),
                    "动一下",
                    4,
                    dest,
                    render_fn=fake_h3,
                    scale_fn=fake_scale,
                )
            self.assertEqual(called["h3"], 1)
            self.assertEqual(record["backend"], "minimax_h3")
            self.assertEqual(record["fallback_from"], "seedance")
            self.assertEqual(record["scaled_to"], OFFICIAL_SIZE)
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 1024)
            self.assertEqual(called["scale"][0][0].name, "SH010.mp4")
            self.assertIn("h3-staging", str(called["scale"][0][0]))


class SeedanceOrH3(unittest.TestCase):
    def test_face_block_calls_h3(self) -> None:
        env = {"MINIMAX_API_KEY": "test-key", "ARK_API_KEY": "ark"}
        h3 = {"n": 0}

        class Boom:
            def render(self, *args, **kwargs):
                raise SeedanceFaceBlock(FACE_BLOCK_CODE)

        def fake_h3(*args, **kwargs):
            h3["n"] += 1
            dest = args[3]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"h3" * 2000)

        def fake_scale(src, dest):
            dest.write_bytes(b"scaled" * 400)
            return scale_h3_cmd(src, dest)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            dest = Path(tmp) / "05-shots" / "SH010.mp4"
            dest.parent.mkdir()
            record = render_seedance_or_h3_fallback(
                Boom(),
                _image(tmp),
                "动一下",
                4,
                dest,
                render_fn=fake_h3,
                scale_fn=fake_scale,
            )
        self.assertEqual(h3["n"], 1)
        self.assertEqual(record["backend"], "minimax_h3")
        self.assertEqual(record["fallback_from"], "seedance")

    def test_other_400_does_not_call_h3(self) -> None:
        h3 = {"n": 0}

        class Boom:
            def render(self, *args, **kwargs):
                raise RuntimeError("Ark 400: InputTextSensitiveContentDetected")

        def fake_h3(*args, **kwargs):
            h3["n"] += 1

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "05-shots" / "SH010.mp4"
            dest.parent.mkdir()
            with self.assertRaises(RuntimeError) as ctx:
                render_seedance_or_h3_fallback(
                    Boom(),
                    _image(tmp),
                    "动一下",
                    4,
                    dest,
                    render_fn=fake_h3,
                    scale_fn=lambda s, d: [],
                )
            self.assertIn("Ark 400", str(ctx.exception))
        self.assertEqual(h3["n"], 0)
        self.assertFalse(dest.exists())

    def test_smoke_dest_does_not_fallback(self) -> None:
        h3 = {"n": 0}

        class Boom:
            def render(self, *args, **kwargs):
                raise SeedanceFaceBlock(FACE_BLOCK_CODE)

        def fake_h3(*args, **kwargs):
            h3["n"] += 1

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "05-shots" / "smoke" / "SH010.mp4"
            dest.parent.mkdir(parents=True)
            with self.assertRaises(SeedanceFaceBlock):
                render_seedance_or_h3_fallback(
                    Boom(),
                    _image(tmp),
                    "动一下",
                    4,
                    dest,
                    render_fn=fake_h3,
                    scale_fn=lambda s, d: [],
                )
        self.assertEqual(h3["n"], 0)


class SubmitClassifies(unittest.TestCase):
    def test_official_default_resolution_is_720p(self) -> None:
        with mock.patch.dict(os.environ, {"ARK_API_KEY": "test-key"}, clear=False):
            old = os.environ.pop("ARK_RESOLUTION", None)
            try:
                backend = SeedanceArk()
            finally:
                if old is not None:
                    os.environ["ARK_RESOLUTION"] = old
        self.assertEqual(backend.resolution, "720p")


    def test_submit_face_block_raises_typed_error(self) -> None:
        env = {"ARK_API_KEY": "test-key"}
        body = {
            "error": {
                "code": FACE_BLOCK_CODE,
                "message": "The request failed because the input image may contain real person.",
            }
        }

        class Resp:
            status_code = 400
            text = '{"error":{"code":"InputImageSensitiveContentDetected.PrivacyInformation"}}'

            def json(self):
                return body

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            backend = SeedanceArk()
            with mock.patch("video_backends.seedance_ark.requests.post", return_value=Resp()):
                with self.assertRaises(SeedanceFaceBlock) as ctx:
                    backend.submit(_image(tmp), "动一下", 4)
            self.assertEqual(ctx.exception.code, FACE_BLOCK_CODE)

    def test_submit_other_400_is_not_face_block(self) -> None:
        env = {"ARK_API_KEY": "test-key"}

        class Resp:
            status_code = 400
            text = '{"error":{"code":"InputTextSensitiveContentDetected","message":"prompt"}}'

            def json(self):
                return {"error": {"code": "InputTextSensitiveContentDetected"}}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=False):
            backend = SeedanceArk()
            with mock.patch("video_backends.seedance_ark.requests.post", return_value=Resp()):
                with self.assertRaises(RuntimeError) as ctx:
                    backend.submit(_image(tmp), "动一下", 4)
            self.assertNotIsInstance(ctx.exception, SeedanceFaceBlock)
            self.assertIn("Ark 400", str(ctx.exception))
            verdict, _code, exit_code = classify_create(400, Resp().json())
            self.assertEqual((verdict, exit_code), ("ERROR", 2))


if __name__ == "__main__":
    unittest.main()
