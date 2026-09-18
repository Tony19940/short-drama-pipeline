#!/usr/bin/env python3
"""Classify Seedance create-task face-block without calling Ark."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_seedance_frame import (  # noqa: E402
    FACE_BLOCK_CODE,
    classify_create,
    payload_summary,
    resolve_image,
    task_id_of,
)
from video_backends.seedance_ark import SeedanceArk  # noqa: E402


SH010_BODY = {
    "error": {
        "code": FACE_BLOCK_CODE,
        "message": "The request failed because the input image 'content[1]' may contain real person.",
        "param": "",
        "type": "BadRequest",
    }
}


class CheckSeedanceFrameTests(unittest.TestCase):
    def test_sh010_submit_400_is_face_block(self) -> None:
        verdict, code, exit_code = classify_create(400, SH010_BODY)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(code, FACE_BLOCK_CODE)
        self.assertEqual(exit_code, 1)

    def test_privacy_suffix_on_video_is_still_face_block(self) -> None:
        verdict, code, exit_code = classify_create(
            400, {"error": {"code": "InputVideoSensitiveContentDetected.PrivacyInformation"}}
        )
        self.assertEqual((verdict, exit_code), ("FAIL", 1))
        self.assertTrue(code.endswith(".PrivacyInformation"))

    def test_other_sensitive_is_error_not_face_block(self) -> None:
        verdict, code, exit_code = classify_create(
            400, {"error": {"code": "InputImageSensitiveContentDetected"}}
        )
        self.assertEqual(verdict, "ERROR")
        self.assertEqual(code, "InputImageSensitiveContentDetected")
        self.assertEqual(exit_code, 2)

    def test_create_200_is_pass(self) -> None:
        verdict, code, exit_code = classify_create(200, {"id": "cgt-demo"})
        self.assertEqual((verdict, code, exit_code), ("PASS", "ok", 0))
        self.assertEqual(task_id_of({"id": "cgt-demo"}), "cgt-demo")

    def test_probe_payload_is_first_frame_only_480p_min_duration(self) -> None:
        with mock.patch.dict(os.environ, {"ARK_API_KEY": "test-key", "ARK_RESOLUTION": "720p", "ARK_GENERATE_AUDIO": "1"}):
            backend = SeedanceArk()
            backend.resolution = "480p"
            image = Path(__file__)
            payload = backend.build_payload(image, "probe", backend.min_duration, refs=None, mode="i2v", generate_audio=False)
        summary = payload_summary(payload)
        self.assertEqual(summary["resolution"], "480p")
        self.assertEqual(summary["duration"], 4)
        self.assertEqual(summary["image_roles"], ["first_frame"])
        self.assertFalse(summary["generate_audio"])
        self.assertEqual(backend.min_duration, 4)

    def test_resolve_image_uses_prod(self) -> None:
        path = resolve_image("04-frames/SH010.jpg", str(ROOT / "productions" / "010-gongpai"))
        self.assertTrue(str(path).endswith("010-gongpai/04-frames/SH010.jpg"))

    def test_raw_error_string_still_classifies(self) -> None:
        raw = json.dumps(SH010_BODY, ensure_ascii=False)
        verdict, code, exit_code = classify_create(400, raw)
        self.assertEqual((verdict, code, exit_code), ("FAIL", FACE_BLOCK_CODE, 1))


if __name__ == "__main__":
    unittest.main()
