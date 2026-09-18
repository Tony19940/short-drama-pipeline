#!/usr/bin/env python3
"""--force archives an existing official mp4 before overwrite. No live API."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_seedance_packages import archive_existing_official  # noqa: E402


class ArchiveExistingOfficial(unittest.TestCase):
    def test_force_copies_official_mp4_into_archive_before_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "05-shots" / "SH001.mp4"
            dest.parent.mkdir()
            dest.write_bytes(b"old-official-clip" * 200)
            sidecar = dest.with_suffix(dest.suffix + ".clip.json")
            sidecar.write_text('{"backend":"old"}\n', encoding="utf-8")
            archived = archive_existing_official(dest, now=datetime(2026, 9, 10, 22, 40, 0))
            self.assertIsNotNone(archived)
            self.assertEqual(archived.name, "SH001-20260910-224000.mp4")
            self.assertEqual(archived.parent.name, "archive-before-force")
            self.assertTrue(archived.exists())
            self.assertEqual(archived.read_bytes(), dest.read_bytes())
            self.assertTrue((archived.parent / "SH001-20260910-224000.mp4.clip.json").exists())
            self.assertTrue(dest.exists())

    def test_skips_smoke_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            smoke = Path(tmp) / "05-shots" / "smoke-h3" / "SH001.mp4"
            smoke.parent.mkdir(parents=True)
            smoke.write_bytes(b"smoke" * 400)
            self.assertIsNone(archive_existing_official(smoke, now=datetime(2026, 9, 10, 22, 40, 0)))
            missing = Path(tmp) / "05-shots" / "SH002.mp4"
            missing.parent.mkdir(parents=True, exist_ok=True)
            self.assertIsNone(archive_existing_official(missing))


if __name__ == "__main__":
    unittest.main()
