#!/usr/bin/env python3
"""Ark portrait library: upload once per byte hash, TOS object always removed, asset:// reaches the payload."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from director import ark_assets  # noqa: E402
from director.volc_openapi import VolcError  # noqa: E402


class FakeVolc:
    def __init__(self, statuses=("Processing", "Active")) -> None:
        self.calls: list[tuple] = []
        self.tos: list[tuple] = []
        self.statuses = list(statuses)

    def ark(self, action, body, **_kw):
        self.calls.append((action, body))
        if action == "CreateAssetGroup":
            return {"Id": "group-1"}
        if action == "CreateAsset":
            return {"Id": f"asset-{len(self.calls)}"}
        if action == "GetAsset":
            return {"Status": self.statuses.pop(0) if self.statuses else "Active"}
        if action == "DeleteAsset":
            return {}
        raise AssertionError(action)

    def tos_request(self, method, key, *a, **k):
        self.tos.append((method, key))
        return 200

    def patches(self):
        return [
            mock.patch.object(ark_assets, "ark_call", self.ark),
            mock.patch.object(ark_assets, "tos_request", self.tos_request),
            mock.patch.object(ark_assets, "tos_presign_get", lambda key, *a: f"https://signed/{key}"),
        ]


class AssetTests(unittest.TestCase):
    def run_with(self, fake, fn):
        for p in fake.patches():
            p.start()
        try:
            return fn()
        finally:
            mock.patch.stopall()

    def test_upload_once_and_clean_bucket(self) -> None:
        fake = FakeVolc()
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp)
            kw = dict(source="04-frames/SH001.jpg", group_name="g ep01", label="SH001-SH001", sleep=lambda s: None)
            url = self.run_with(fake, lambda: ark_assets.ensure_asset(prod, b"jpeg", **kw))
            again = self.run_with(fake, lambda: ark_assets.ensure_asset(prod, b"jpeg", **kw))
            self.assertEqual(url, again)
            self.assertTrue(url.startswith("asset://"))
            actions = [c[0] for c in fake.calls]
            self.assertEqual(actions.count("CreateAsset"), 1)
            self.assertEqual(actions.count("CreateAssetGroup"), 1)
            self.assertEqual([m for m, _ in fake.tos], ["PUT", "DELETE"])
            create = dict(fake.calls)["CreateAsset"]
            self.assertEqual((create["GroupId"], create["AssetType"]), ("group-1", "Image"))
            self.assertTrue(create["URL"].startswith("https://signed/"))
            gone = self.run_with(fake, lambda: ark_assets.release(prod))
            self.assertEqual(len(gone), 1)
            self.assertIsNone(ark_assets.live_asset(ark_assets.read_ledger(prod), ark_assets.read_ledger(prod)["assets"][0]["sha256"]))

    def test_failed_review_raises_and_still_cleans(self) -> None:
        fake = FakeVolc(statuses=("Failed",))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(VolcError):
                self.run_with(fake, lambda: ark_assets.ensure_asset(
                    Path(tmp), b"x", source="a.jpg", group_name="g", label="a", sleep=lambda s: None))
            self.assertEqual(fake.tos[-1][0], "DELETE")


class PayloadTests(unittest.TestCase):
    def test_resolver_replaces_data_url(self) -> None:
        import os

        from video_backends.seedance_ark import SeedanceArk

        with mock.patch.dict(os.environ, {"ARK_API_KEY": "test"}), tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "SH001.jpg"
            from PIL import Image

            Image.new("RGB", (64, 36)).save(frame)
            backend = SeedanceArk(model="doubao-seedance-2-0-mini-260615", resolution="480p")
            backend.asset_resolver = lambda path, data: "asset://asset-x"
            payload = backend.build_payload(frame, "p", 4)
            urls = [c["image_url"]["url"] for c in payload["content"] if c.get("type") == "image_url"]
            self.assertEqual(urls, ["asset://asset-x"])
            self.assertEqual(payload["resolution"], "480p")


if __name__ == "__main__":
    unittest.main()
