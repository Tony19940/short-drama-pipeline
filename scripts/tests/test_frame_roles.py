"""Planned frames and extracted video ends cannot share an implicit role."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from director.setup_anchors import resolve_continuity_parent, resolve_continuity_parent_info
from director.context import ProductionContext, using_context
from director.gates import designed_end_frame, i2v_source
from director.revisions import register_revision
from place_codex_frame import (dest_rel, frame_role_info, parent_chain_errors, place,
                               record_generated_end, resolve_generated_end)


class FrameRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prod = Path(self.tmp.name)
        self.src = self.prod / "source.png"
        Image.new("RGB", (640, 360), (30, 40, 50)).save(self.src)
        master = self.prod / "02-assets/scenes/market/master.jpg"
        master.parent.mkdir(parents=True)
        Image.new("RGB", (640, 360)).save(master)
        (self.prod / ".pipeline").mkdir()
        (self.prod / ".pipeline/shot_list.json").write_text(json.dumps({"shots": [
            {"shot_id": "SH001", "scene_id": "market", "setup_id": "A"},
            {"shot_id": "SH002", "scene_id": "market", "setup_id": "A"},
            {"shot_id": "SH003", "scene_id": "market", "setup_id": "B"},
        ]}))
        place(self.prod, "SH001", "first", self.src,
              parent="02-assets/scenes/market/master.jpg", identity_gate="pass")

    def actual(self, *, episode=1, gate="pass"):
        folder = "05-shots" if episode == 1 else f"05-shots/{episode}"
        frame = f"{folder}/SH001-last.jpg"
        video = f"{folder}/SH001.mp4"
        (self.prod / folder).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 360), (90, 80, 70)).save(self.prod / frame)
        # No video is generated in this test: provenance binding is tested with fixture bytes.
        (self.prod / video).write_bytes(b"source-video-fixture")
        record_generated_end(self.prod, "SH001", frame_rel=frame, video_rel=video,
                             extraction_method="ffmpeg -sseof -0.05", offset_sec=-0.05,
                             identity_gate=gate, episode=episode)
        return frame, video

    def test_slots_have_explicit_design_roles(self):
        for slot, path in (("end", "04-frames/SH001-end.jpg"),
                           ("last", "04-frames/SH001-last.jpg")):
            result = place(self.prod, "SH001", slot, self.src, identity_gate="pass")
            self.assertEqual(result["dest"], path)
            self.assertEqual(result["frame_role"], "planned_end")
            self.assertEqual(frame_role_info(self.prod, path)["provenance_status"], "planned")
        self.assertEqual(frame_role_info(self.prod, "04-frames/SH001.jpg")["frame_role"], "planned_start")
        self.assertIsNone(resolve_generated_end(self.prod, "SH001"))
        self.assertEqual(resolve_continuity_parent(self.prod, "SH002"), "04-frames/SH001-end.jpg")
        self.assertEqual(dest_rel("SH002", "end", "ep01-v2"), "04-frames/ep01-v2/SH002-end.jpg")

    def test_explicit_legacy_design_end_survives_checker_and_prompt_consumers(self):
        from check_storyboard import check_end_frame
        from director.prompts import video_mode, designed_end_rel
        from director.gates import designed_end_frame

        rel = "04-frames/SH001-last.jpg"
        shot = {"id": "SH001", "frame": "04-frames/SH001.jpg", "end_frame": rel}
        Image.new("RGB", (640, 360)).save(self.prod / rel)
        with self.assertRaises(SystemExit):
            check_end_frame(self.prod, shot)
        place(self.prod, "SH001", "last", self.src, identity_gate="pass")
        check_end_frame(self.prod, shot)
        self.assertTrue(designed_end_frame(self.prod, shot)["ok"])
        self.assertEqual(designed_end_rel(shot), rel)
        self.assertEqual(video_mode(shot, "designed_frame"), "flf")

    def test_verified_actual_wins_and_is_legal_edit_parent(self):
        place(self.prod, "SH001", "end", self.src, identity_gate="pass")
        actual, _ = self.actual()
        self.assertEqual(resolve_generated_end(self.prod, "SH001"), actual)
        self.assertEqual(resolve_continuity_parent_info(self.prod, "SH002")["frame_role"], "generated_end")
        result = place(self.prod, "SH002", "first", self.src, identity_gate="pass")
        self.assertEqual(result["parent"], actual)
        meta = json.loads((self.prod / result["sidecar"]).read_text())
        self.assertEqual(meta["parent_frame_role"], "generated_end")
        self.assertEqual(meta["parent_provenance_status"], "verified")
        self.assertEqual(parent_chain_errors(self.prod), [])
        self.assertIsNone(resolve_continuity_parent(self.prod, "SH003"))

    def test_source_or_image_changes_invalidate_actual(self):
        actual, video = self.actual()
        (self.prod / video).write_bytes(b"replacement")
        self.assertEqual(frame_role_info(self.prod, actual)["provenance_status"], "stale")
        self.assertIsNone(resolve_generated_end(self.prod, "SH001"))
        self.assertEqual(resolve_continuity_parent(self.prod, "SH002"), "04-frames/SH001.jpg")
        with self.assertRaisesRegex(ValueError, "generated_end"):
            place(self.prod, "SH002", "first", self.src, parent=actual)
        actual, _ = self.actual()
        place(self.prod, "SH002", "first", self.src, parent=actual, identity_gate="pass")
        Image.new("RGB", (640, 360), (1, 2, 3)).save(self.prod / actual)
        self.assertTrue(any("stale" in err for err in parent_chain_errors(self.prod)))

    def test_legacy_last_keeps_filename_but_is_unknown(self):
        rel = "04-frames/SH001-last.jpg"
        Image.new("RGB", (640, 360)).save(self.prod / rel)
        (self.prod / "04-frames/SH001-last.json").write_text(json.dumps({"identity_gate": "pass"}))
        info = resolve_continuity_parent_info(self.prod, "SH002")
        self.assertEqual(info["path"], rel)
        self.assertEqual(info["frame_role"], "unknown")
        self.assertTrue(info["legacy"])
        self.assertTrue(any("legacy" in warning for warning in info["warnings"]))
        result = place(self.prod, "SH002", "first", self.src, identity_gate="pass")
        self.assertTrue(result["warnings"])
        self.assertIsNone(resolve_generated_end(self.prod, "SH001"))

    def test_actual_requires_separate_identity_review_and_episode(self):
        actual, _ = self.actual(gate="unknown")
        self.assertEqual(frame_role_info(self.prod, actual)["provenance_status"], "verified")
        self.assertIsNone(resolve_generated_end(self.prod, "SH001"))
        scoped, _ = self.actual(episode="ep01-v2")
        self.assertEqual(resolve_generated_end(self.prod, "SH001", "ep01-v2"), scoped)
        self.assertIsNone(resolve_generated_end(self.prod, "SH001", "ep02"))

    def test_cannot_register_designed_still_as_actual(self):
        actual, video = self.actual()
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            record_generated_end(self.prod, "SH001", frame_rel="04-frames/SH001.jpg",
                                 video_rel=video, extraction_method="ffmpeg")
        with self.assertRaisesRegex(ValueError, "抽帧方法"):
            record_generated_end(self.prod, "SH001", frame_rel=actual,
                                 video_rel=video, extraction_method="")
        with self.assertRaisesRegex(ValueError, "slot"):
            place(self.prod, "SH001", "generated_end", self.src)

    def test_runtime_does_not_consume_planned_or_unverified_last(self):
        prev = {"id": "SH001", "setup": "close", "characters": ["piseth"],
                "last_frame": "04-frames/SH001-last.jpg"}
        shot = {"id": "SH002", "cut": "continue", "from": "SH001", "setup": "close",
                "characters": ["piseth"], "frame": "04-frames/SH002.jpg"}
        place(self.prod, "SH001", "last", self.src, identity_gate="pass")
        place(self.prod, "SH002", "first", self.src, identity_gate="pass")
        self.assertEqual(i2v_source(self.prod, shot, [prev, shot])["kind"], "designed_frame")
        actual, _ = self.actual(gate="unknown")
        self.assertEqual(i2v_source(self.prod, shot, [prev, shot])["kind"], "designed_frame")
        actual, _ = self.actual()
        source = i2v_source(self.prod, shot, [prev, shot])
        self.assertEqual(source["path"], actual)
        self.assertEqual(source["frame_role"], "generated_end")

    def test_designed_end_uses_role_not_last_filename(self):
        rel = place(self.prod, "SH001", "last", self.src, identity_gate="pass")["dest"]
        shot = {"id": "SH001", "frame": "04-frames/SH001.jpg", "end_frame": rel}
        self.assertTrue(designed_end_frame(self.prod, shot)["ok"])
        self.assertEqual(designed_end_frame(self.prod, shot)["frame_role"], "planned_end")
        (self.prod / "04-frames/SH001-last.json").unlink()
        self.assertFalse(designed_end_frame(self.prod, shot)["ok"])
        actual, _ = self.actual()
        self.assertFalse(designed_end_frame(self.prod, {**shot, "end_frame": actual})["ok"])
        self.assertFalse(designed_end_frame(self.prod, {**shot, "end_frame": shot["frame"]})["ok"])

    def test_registered_custom_dirs_reach_placement_parent_and_runtime(self):
        rows = [
            {"shot_id": "SH001", "scene_id": "market", "setup_id": "A", "setup": "close", "characters": ["piseth"]},
            {"shot_id": "SH002", "scene_id": "market", "setup_id": "A", "setup": "close", "characters": ["piseth"],
             "cut": "continue", "from": "SH001"},
        ]
        table = self.prod / ".pipeline/tables/cel.json"
        table.parent.mkdir()
        table.write_text(json.dumps({"shots": rows}))
        register_revision(self.prod, {
            "episode_id": "ep01", "revision_id": "cel", "artifacts": {"shot_list.json": ".pipeline/tables/cel.json"},
            "frames_dir": "media/design/cel", "shots_dir": "media/videos/cel", "cut_file": ".pipeline/cuts/cel.json",
        }, activate=True)
        ctx = ProductionContext.resolve(self.prod)
        with using_context(ctx):
            self.assertEqual(dest_rel("SH001", "first", prod=self.prod), "media/design/cel/SH001.jpg")
            first = place(self.prod, "SH001", "first", self.src,
                          parent="02-assets/scenes/market/master.jpg", identity_gate="pass")
            end = place(self.prod, "SH001", "end", self.src, identity_gate="pass")
            self.assertEqual(end["parent"], first["dest"])
            self.assertEqual(resolve_continuity_parent(self.prod, "SH002"), end["dest"])
            video = self.prod / "media/videos/cel/SH001.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"custom-video")
            actual = "media/videos/cel/SH001-last.jpg"
            Image.new("RGB", (640, 360)).save(self.prod / actual)
            record_generated_end(self.prod, "SH001", frame_rel=actual,
                                 video_rel=str(video.relative_to(self.prod)), extraction_method="ffmpeg", identity_gate="pass")
            self.assertEqual(resolve_generated_end(self.prod, "SH001"), actual)
            result = place(self.prod, "SH002", "first", self.src, identity_gate="pass")
            self.assertEqual(result["dest"], "media/design/cel/SH002.jpg")
            self.assertEqual(result["parent"], actual)
            source = i2v_source(self.prod, {**rows[1], "id": "SH002"}, [{**rows[0], "id": "SH001"}])
            self.assertEqual(source["path"], actual)
            self.assertTrue(designed_end_frame(self.prod, {"id": "SH001", "end_frame": end["dest"]})["ok"])
            with self.assertRaisesRegex(ValueError, "本版本"):
                place(self.prod, "SH002", "first", self.src, parent="04-frames/SH001.jpg")
            with self.assertRaisesRegex(ValueError, "当前版本"):
                record_generated_end(self.prod, "SH001", frame_rel="05-shots/SH001-last.jpg",
                                     video_rel="05-shots/SH001.mp4", extraction_method="ffmpeg")


if __name__ == "__main__":
    unittest.main()
