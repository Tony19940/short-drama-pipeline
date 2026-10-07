"""Registered revision helpers cannot inventory or approve an older episode."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from director.context import ProductionContext, using_context
from director.production import accept_shot_draft, coverage, load_shot_draft, save_shot_draft, save_shots, shot_board
from director.qc import build_qc_report, promote_qc_drafts, snapshot_qc, write_qc_draft
from director.review_contract import contract_path, evaluate_review_contract, freeze_review_contract, load_contract, preview_path
from director.revisions import register_revision
from director.sfx import build_plan, load_shot_table, run_mix, shot_list_path, shot_timeline, snapshot_sfx
from director.video_profiles import UnknownProfileError, resolve_target_model


def put(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


class RevisionAuxiliaryPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prod = Path(self.temp.name) / "show"
        self.prod.mkdir()
        put(self.prod / ".pipeline/shot_list.json", {"shots": [{"shot_id": "SH001"}], "target_model": "seedance_2_0"})
        put(self.prod / ".pipeline/gen_packages.json", {"episode_target_model": "seedance_2_0"})
        put(self.prod / "03-storyboard/shots.json", {"shots": [{"id": "SH001"}]})
        put(self.prod / "03-storyboard/shots.draft.json", {"shots": [{"id": "SH001"}]})
        put(self.prod / ".director/review-contract.json", {"verdict": "pass", "required": "pass"})
        put(self.prod / "08-qc/report.json", {"verdict": "pass"})
        for rel in ("05-shots/SH009.mp4", "06-export/ep01.mp4", "07-dubbing/sfx/ep01-sfx.m4a"):
            path = self.prod / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"legacy media")
        self.table = self.prod / ".pipeline/tables/v2.json"
        put(self.table, {"schema": "shot-table-v2", "target_model": "minimax_h3", "shots": [{"shot_id": "SH009", "duration_sec": 3, "key_sfx": ["雷声"]}]})
        self.cut = self.prod / ".pipeline/cuts/v2.json"
        put(self.cut, {"final_file": "06-export/ep01-v2/final.mp4", "segments": []})
        register_revision(self.prod, {
            "episode_id": "ep01", "revision_id": "v2",
            "artifacts": {"shot_list.json": ".pipeline/tables/v2.json"},
            "frames_dir": "04-frames/v2", "shots_dir": "05-shots/v2/official",
            "cut_file": ".pipeline/cuts/v2.json",
        }, activate=True)

    def test_target_model_uses_current_table_and_never_old_package(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_target_model(self.prod), "minimax_h3")
            put(self.table, {"shots": [{"shot_id": "SH009"}]})
            with self.assertRaises(UnknownProfileError):
                resolve_target_model(self.prod)

    def test_target_model_current_package_overrides_current_table(self):
        put(self.prod / ".pipeline/gen_packages.ep01-v2.json", {"episode_target_model": "seedance_2_0"})
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_target_model(self.prod), "seedance_2_0")

    def test_explicit_task_context_does_not_use_active_model_or_media(self):
        register_revision(self.prod, {
            "episode_id": "ep01", "revision_id": "v3", "artifacts": {"shot_list.json": ".pipeline/tables/v3.json"},
            "frames_dir": "04-frames/v3", "shots_dir": "05-shots/v3", "cut_file": ".pipeline/cuts/v3.json",
        }, activate=True)
        put(self.prod / ".pipeline/tables/v3.json", {"target_model": "seedance_2_0", "shots": [{"shot_id": "SH010"}]})
        with using_context(ProductionContext.resolve(self.prod, 1, "v2")), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_target_model(self.prod), "minimax_h3")
            self.assertEqual(snapshot_sfx(self.prod)["context"]["revision_id"], "v2")

    def test_inventory_uses_current_table_frames_and_clips(self):
        board = shot_board(self.prod)
        self.assertEqual([s["id"] for s in board["shots"]], ["SH009"])
        row = board["shots"][0]
        self.assertEqual(row["parent"]["path"], "04-frames/v2/SH009.jpg")
        self.assertEqual(row["end"]["path"], "04-frames/v2/SH009-last.jpg")
        self.assertFalse(row["video_exists"])
        self.assertEqual(board["source"]["shot_count"], 1)
        self.assertEqual(coverage(self.prod)["source"]["revision_id"], "v2")
        clip = self.prod / "05-shots/v2/official/SH009.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"current")
        self.assertTrue(shot_board(self.prod)["shots"][0]["video_exists"])

    def test_old_editor_actions_fail_before_writing(self):
        official = (self.prod / "03-storyboard/shots.json").read_bytes()
        draft = (self.prod / "03-storyboard/shots.draft.json").read_bytes()
        calls = (lambda: save_shots(self.prod, {"shots": []}), lambda: save_shot_draft(self.prod, {"shots": []}),
                 lambda: accept_shot_draft(self.prod), lambda: load_shot_draft(self.prod))
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(PermissionError, "绑定分镜表"):
                call()
        self.assertEqual((self.prod / "03-storyboard/shots.json").read_bytes(), official)
        self.assertEqual((self.prod / "03-storyboard/shots.draft.json").read_bytes(), draft)

    def test_old_review_actions_fail_before_loading_or_probing(self):
        old = (self.prod / ".director/review-contract.json").read_bytes()
        with patch("director.review_contract.subprocess.check_output", side_effect=AssertionError("must not probe old media")):
            for fn in (contract_path, load_contract, preview_path, freeze_review_contract, evaluate_review_contract):
                with self.subTest(fn=fn.__name__), self.assertRaisesRegex(PermissionError, "段落声画审核"):
                    fn(self.prod)
        self.assertEqual((self.prod / ".director/review-contract.json").read_bytes(), old)

    def test_qc_does_not_read_old_contract_sound_or_report(self):
        with patch("director.qc.load_contract", side_effect=AssertionError("old contract")), \
             patch("director.qc.load_review", side_effect=AssertionError("old review")), \
             patch("director.qc.build_sound_contract", side_effect=AssertionError("old sound")):
            report = build_qc_report(self.prod, evaluate=True)
            self.assertEqual(report["verdict"], "fail")
            self.assertFalse(report["export_exists"])
            self.assertEqual(report["context"]["revision_id"], "v2")
            snap = snapshot_qc(self.prod)
            self.assertIsNone(snap["official"])
            self.assertFalse(snap["export_exists"])

    def test_qc_current_export_is_inconclusive_and_reports_are_namespaced(self):
        output = self.prod / "06-export/ep01-v2/final.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"current")
        with patch("director.narrative.inspect_narrative", return_value={"status": "pass", "errors": [], "pending": []}):
            self.assertEqual(build_qc_report(self.prod)["verdict"], "inconclusive")
            write_qc_draft(self.prod)
            self.assertTrue((self.prod / "08-qc/ep01-v2/report.draft.json").is_file())
            promote_qc_drafts(self.prod)
            self.assertEqual(snapshot_qc(self.prod)["official"]["verdict"], "inconclusive")
        self.assertEqual(json.loads((self.prod / "08-qc/report.json").read_text())["verdict"], "pass")

    def test_sfx_snapshot_and_table_ignore_old_root(self):
        self.assertEqual(shot_list_path(self.prod, 1), self.table)
        self.assertEqual(load_shot_table(self.prod)["shots"][0]["shot_id"], "SH009")
        snap = snapshot_sfx(self.prod)
        self.assertEqual(snap["missing_clips"], ["SH009"])
        self.assertFalse(snap["exists"])
        self.assertEqual(snap["file"], "07-dubbing/sfx/ep01-v2/sfx.m4a")
        self.assertEqual(snap["context"]["revision_id"], "v2")

    def test_sfx_timeline_probes_bound_clip_directory(self):
        new_clip = self.prod / "05-shots/v2/official/SH009.mp4"
        new_clip.parent.mkdir(parents=True)
        new_clip.write_bytes(b"current")
        with patch("director.sfx.probe_duration", return_value=3) as probe:
            timeline, missing = shot_timeline(self.prod, ["SH009"])
        probe.assert_called_once_with(new_clip)
        self.assertEqual(timeline[0]["duration"], 3)
        self.assertFalse(missing)

    def test_old_sfx_mix_is_blocked_before_network_or_media_mutation(self):
        with patch("director.sfx.fetch_kit", side_effect=AssertionError("network")), \
             patch("director.sfx.mix", side_effect=AssertionError("mix")):
            for call in (lambda: build_plan(self.prod), lambda: run_mix(self.prod), lambda: run_mix(self.prod, dry_run=True)):
                with self.subTest(call=call), self.assertRaisesRegex(PermissionError, "EDL"):
                    call()
        self.assertFalse((self.prod / "07-dubbing/sfx/ep01-v2").exists())


if __name__ == "__main__":
    unittest.main()
