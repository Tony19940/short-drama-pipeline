"""Actual event retention and viewer evidence. No vendor requests."""
import copy
import json
import sys
import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from director.context import ProductionContext
from director.narrative import (digest, file_hash, check_event_coverage, contract_errors,
    write_export_receipt, record_sequence_review, check_sequence_reviews, normalize_cut,
    require_design_review, require_cut_media_reviews, speed_findings)
from director.revisions import register_revision
from director.review_actions import record_design
from director.shot_table import design_review_digest
from director.jobs import assemble_episode
from render_seedance_packages import render_plan


class NarrativeEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prod = Path(self.tmp.name) / "test-show"
        self.prod.mkdir()
        self.source = "05-shots/v2/SH015.mp4"
        self.media(self.source, b"actual video bytes")
        self.contract = {"schema": "narrative-events-v1", "sequences": [{
            "sequence_id": "first-return", "shot_ids": ["SH015"],
            "understanding_questions": ["What caused the money to appear?"],
            "allowed_uncertainty": ["the magical mechanism is unknown"]}],
            "events": [{"event_id": "coin-flash", "sequence_id": "first-return", "shot_ids": ["SH015"],
                        "expected_observation": "copper coin flashes", "channel": "visual", "required": True,
                        "min_visible_sec": 0.5}]}
        self.evidence = {"contract_sha256": digest(self.contract), "observations": [{
            "event_id": "coin-flash", "shot_id": "SH015", "source": self.source,
            "source_sha256": file_hash(self.prod / self.source), "start_sec": 1.0, "end_sec": 1.6,
            "status": "observed", "reviewer": "frame inspector", "reviewed_at": 1,
            "method": "visual_inspection", "notes": "actual source interval reviewed"}]}
        self.cut = {"timeline": [{"shot_id": "SH015", "source": self.source, "in_sec": 1, "out_sec": 2}]}

    def media(self, rel, data):
        path = self.prod / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def report(self, cut=None):
        return check_event_coverage(self.prod, self.contract, self.evidence, cut or self.cut)

    def write(self, rel, data):
        return self.media(rel, json.dumps(data).encode())

    def register(self):
        register_revision(self.prod, {"episode_id": "ep01", "revision_id": "v2", "artifact_token": "ep01-v2",
            "shots_dir": "05-shots/v2", "artifacts": {"shot_list.json": ".pipeline/table-v2.json"}}, activate=True)
        self.write(".pipeline/table-v2.json", {"shots": [{"shot_id": "SH015", "in_from": "dark", "out_to": "flash"}]})
        self.write(".pipeline/events.ep01-v2.json", self.contract)

    def test_regression_sh015_trigger_trimmed_away_is_rejected(self):
        self.cut["timeline"][0].update(in_sec=0.1, out_sec=0.6)
        report = self.report()
        self.assertEqual(report["status"], "fail")
        self.assertIn("omitted", report["errors"][0])

    def test_retained_interval_accounts_for_speed(self):
        self.assertEqual(self.report()["status"], "pass")
        self.cut["timeline"][0]["speed"] = 4
        self.assertEqual(self.report()["status"], "fail")

    def test_changed_source_invalidates_observation(self):
        self.media(self.source, b"replacement video")
        self.assertEqual(self.report()["status"], "fail")

    def test_missing_observation_is_pending_not_automatic_pass(self):
        self.evidence["observations"] = []
        self.assertEqual(self.report()["status"], "pending")

    def test_contract_change_invalidates_evidence(self):
        self.contract["events"][0]["expected_observation"] = "coin glows then money appears"
        self.assertEqual(self.report()["status"], "pending")

    def test_unrequired_ellipsis_can_be_omitted(self):
        self.contract["events"][0]["required"] = False
        self.evidence = {"contract_sha256": digest(self.contract), "observations": []}
        self.assertEqual(self.report()["status"], "pass")

    def test_audio_event_cannot_pass_when_muted(self):
        self.contract["events"][0]["channel"] = "audio"
        self.evidence["contract_sha256"] = digest(self.contract)
        self.evidence["observations"][0]["method"] = "audio_inspection"
        self.cut["timeline"][0]["audio_mode"] = "silent"
        self.assertEqual(self.report()["status"], "fail")

    def test_reverse_dependency_is_rejected(self):
        self.contract["events"].append({**self.contract["events"][0], "event_id": "money-appears", "depends_on": ["coin-flash"]})
        self.evidence["contract_sha256"] = digest(self.contract)
        self.evidence["observations"].append({**self.evidence["observations"][0], "event_id": "money-appears", "start_sec": 1.05, "end_sec": 1.6})
        self.assertTrue(any("before prerequisite" in e for e in self.report()["errors"]))

    def test_one_frame_visual_event_is_below_readable_floor(self):
        # 011 set every event to 0.03s: one frame proves existence, not that a viewer can read it.
        self.contract["events"][0]["min_visible_sec"] = 0.03
        errors = contract_errors(self.contract)
        self.assertTrue(any("readable floor" in e for e in errors), errors)
        self.contract["events"][0]["brief_reason"] = "intentional two-frame glint; the next shot carries the reveal"
        self.assertEqual(contract_errors(self.contract), [])

    def test_missing_min_visible_defaults_to_readable_floor(self):
        del self.contract["events"][0]["min_visible_sec"]
        self.assertEqual(contract_errors(self.contract), [])
        self.evidence["contract_sha256"] = digest(self.contract)
        self.evidence["observations"][0].update(start_sec=1.0, end_sec=1.2)
        report = self.report()
        self.assertEqual(report["status"], "fail")
        self.assertIn("too short", report["errors"][0])

    def test_floor_applies_to_required_visual_events_only(self):
        self.contract["events"][0]["min_visible_sec"] = 0.03
        self.contract["events"][0]["channel"] = "audio"
        self.assertEqual(contract_errors(self.contract), [])
        self.contract["events"][0]["channel"] = "visual"
        self.contract["events"][0]["required"] = False
        self.assertEqual(contract_errors(self.contract), [])

    def test_speed_change_needs_a_reason(self):
        row = self.cut["timeline"][0]
        self.assertEqual(speed_findings(self.cut), [])
        row["speed"] = 1.1
        self.assertEqual(speed_findings(self.cut), [])
        row["speed"] = 2
        self.assertTrue(any("SH015 speed 2x" in f for f in speed_findings(self.cut)))
        row["speed"] = 0.5
        self.assertTrue(speed_findings(self.cut))
        row["speed_reason"] = "slow motion on the trigger, designed in the scene card"
        self.assertEqual(speed_findings(self.cut), [])
        row.pop("speed_reason")
        row["used"] = False
        self.assertEqual(speed_findings(self.cut), [])

    def test_formal_assembly_blocks_uncapped_speed_before_ffmpeg(self):
        self.register()
        self.cut["timeline"][0]["speed"] = 2
        self.write(".pipeline/cut.ep01-v2.json", self.cut)
        with patch("director.jobs.subprocess.run") as runner:
            with self.assertRaisesRegex(PermissionError, "变速"):
                assemble_episode(self.prod)
            runner.assert_not_called()

    def test_cycle_and_malformed_contract_rejected(self):
        self.contract["events"][0]["depends_on"] = ["coin-flash"]
        self.assertTrue(contract_errors(self.contract))
        self.assertTrue(contract_errors({"sequences": ["bad"]}))

    def test_paths_cannot_escape_production(self):
        self.cut["timeline"][0]["source"] = "../other.mp4"
        self.assertEqual(self.report()["status"], "fail")

    def test_wrong_picture_take_rejected_before_rendering(self):
        self.cut["timeline"][0].pop("source")
        self.cut["timeline"][0]["take_id"] = "nonexistent"
        with self.assertRaisesRegex(ValueError, "invalid picture take"):
            normalize_cut(self.prod, self.cut)

    def review(self):
        viewed = "06-export/preview.mp4"
        self.media(viewed, b"assembled movie bytes")
        write_export_receipt(self.prod, self.contract, self.cut, viewed)
        return record_sequence_review(self.prod, self.contract, self.cut, "first-return",
            reviewer="viewer", viewed_file=viewed, viewed_sha256=file_hash(self.prod / viewed),
            answers=["The coin flashes before new money appears; the mechanism is still unknown."],
            verdict="pass", notes="Viewed the full sequence with sound, without reading the script.",
            blind=True, sound_review="pass")

    def test_sequence_pass_requires_actual_export_receipt_and_hash(self):
        self.media("06-export/other.mp4", b"unrelated movie")
        with self.assertRaisesRegex(ValueError, "recorded export"):
            record_sequence_review(self.prod, self.contract, self.cut, "first-return", reviewer="viewer",
                viewed_file="06-export/other.mp4", viewed_sha256=file_hash(self.prod / "06-export/other.mp4"),
                answers=["answer"], verdict="pass", notes="watched", sound_review="pass")
        row = self.review()
        self.assertEqual(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}), [])

    def test_review_invalidates_when_edit_changes(self):
        row = self.review()
        self.cut["timeline"][0]["in_sec"] = 1.1
        self.assertTrue(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}))

    def test_review_invalidates_when_sound_source_changes(self):
        rel = "05-shots/voice.wav"
        self.media(rel, b"sound one")
        self.cut["timeline"][0]["audio_source"] = rel
        row = self.review()
        self.media(rel, b"sound two")
        self.assertTrue(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}))

    def test_review_invalidates_when_viewed_movie_changes(self):
        row = self.review()
        self.media(row["viewed_file"], b"new export")
        self.assertTrue(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}))

    def test_legacy_declared_pass_is_not_registered_creative_review(self):
        self.register()
        with self.assertRaisesRegex(PermissionError, "人工审阅"):
            require_design_review(self.prod)
        ctx = ProductionContext.resolve(self.prod)
        table = ctx.read_artifact("shot_list.json")
        record_design(ctx, {"reviewer": "director", "notes": "The causal reveal is readable; hidden money remains a risk for animatic review.", "input_sha256": design_review_digest(table), "contract_sha256": digest(self.contract)})
        require_design_review(self.prod)
        table = ctx.read_artifact("shot_list.json")
        table["shots"][0]["out_to"] = "changed result"
        self.write(".pipeline/table-v2.json", table)
        with self.assertRaisesRegex(PermissionError, "stale"):
            require_design_review(self.prod)

    def test_formal_assembly_blocks_missing_clip_review_before_ffmpeg(self):
        self.register()
        self.write(".pipeline/cut.ep01-v2.json", self.cut)
        with patch("director.jobs.subprocess.run") as runner:
            with self.assertRaisesRegex(PermissionError, "missing clips"):
                assemble_episode(self.prod)
            runner.assert_not_called()

    def test_used_take_requires_its_own_media_review(self):
        self.register()
        reviewed = "05-shots/v2/reviewed.mp4"
        self.media(reviewed, b"another take")
        self.write(".pipeline/clips.ep01-v2.json", {"clips": [{"shot_id": "SH015", "video_file": reviewed,
            "qc": {"status": "pass"}, "layers": {"technical": {"status": "pass"}, "visual": {"status": "pass"}},
            "review": {"reviewed_by": "reviewer", "media_hash": file_hash(self.prod / reviewed)}}]})
        with self.assertRaisesRegex(PermissionError, "采用的素材"):
            require_cut_media_reviews(self.prod, self.cut)

    def test_paid_cli_refuses_without_gate_before_any_backend(self):
        with patch("render_seedance_packages._backend_for_item") as backend:
            with self.assertRaises(PermissionError):
                render_plan(self.prod, {"shots": [{"shot_id": "SH015"}]})
            backend.assert_not_called()

    def test_changed_package_cannot_submit_old_snapshot_even_after_other_reviews_pass(self):
        class Request:
            def __init__(self, body):
                self.body = body
            def fingerprint(self):
                return self.body["fingerprint"]
            def media_hash_map(self):
                return {}
        with ExitStack() as stack:
            for target in ("director.gates.require_fresh_gate", "director.pipeline.assert_packages_confirmed",
                           "director.pipeline.assert_keyframes_passed", "director.narrative.require_design_review"):
                stack.enter_context(patch(target))
            stack.enter_context(patch("director.show_policy.load_show_policy", return_value=SimpleNamespace(animatic_required=False)))
            stack.enter_context(patch("director.fingerprint.fingerprint_for", return_value=("new-batch", [
                {"id": "SH015", "vendor_request": {"fingerprint": "new-request"}}])))
            stack.enter_context(patch("render_seedance_packages.VendorRequest.from_dict", side_effect=Request))
            backend = stack.enter_context(patch("render_seedance_packages._backend_for_item"))
            with self.assertRaisesRegex(PermissionError, "不同于确认快照"):
                render_plan(self.prod, {"from_snapshot": "snapshot.json", "shots": [{"shot_id": "SH015",
                    "dest": "05-shots/SH015.mp4", "vendor_request": {"fingerprint": "old-request"}}]})
            backend.assert_not_called()

    def test_shortened_output_frame_duration_cannot_count_event_after_its_end(self):
        self.cut["timeline"][0]["output_duration_sec"] = 0.1
        self.assertEqual(self.report()["status"], "fail")

    def test_repeated_or_foreign_sequence_approval_is_not_accepted(self):
        row = self.review()
        self.assertTrue(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row, row]}))

    def test_draft_review_can_be_accepted_without_a_circular_lock_requirement(self):
        self.register()
        ctx = ProductionContext.resolve(self.prod)
        table = ctx.read_artifact("shot_list.json")
        table["shots"][0]["out_to"] = "new, reviewed creative choice"
        self.write(".pipeline/shot_list.draft.json", table)
        reviewed = record_design(ctx, {"draft_file": ".pipeline/shot_list.draft.json", "reviewer": "director fixture",
            "notes": "Explicit review of this draft and the event contract", "input_sha256": design_review_digest(table),
            "contract_sha256": digest(self.contract)})
        self.assertEqual(reviewed["status"], "ready")
        require_design_review(self.prod)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg required")
    def test_actual_export_remains_pending_until_source_bound_viewer_review(self):
        self.register()
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=160x90:r=30:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.prod / self.source)],
            capture_output=True, check=True, timeout=20)
        self.evidence["observations"][0]["source_sha256"] = file_hash(self.prod / self.source)
        self.write(".pipeline/event_evidence.ep01-v2.json", self.evidence)
        self.write(".pipeline/cut.ep01-v2.json", self.cut)
        self.write(".pipeline/clips.ep01-v2.json", {"clips": [{"shot_id": "SH015", "video_file": self.source,
            "qc": {"status": "pass"}, "layers": {"technical": {"status": "pass"}, "visual": {"status": "pass"}},
            "review": {"reviewed_by": "reviewer fixture", "media_hash": file_hash(self.prod / self.source)}}]})
        output = assemble_episode(self.prod)
        self.assertEqual(output["status"], "pending_sequence_review")
        self.assertFalse(output["approved"])
        row = record_sequence_review(self.prod, self.contract, self.cut, "first-return", reviewer="viewer fixture",
            viewed_file=output["output"], viewed_sha256=file_hash(self.prod / output["output"]), answers=["fixture answer"],
            verdict="pass", notes="explicit offline review fixture", sound_review="pass", blind=True)
        self.assertEqual(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}), [])
        self.cut["timeline"][0]["in_sec"] = 0.1
        self.cut["timeline"][0]["out_sec"] = 0.6
        self.assertTrue(check_sequence_reviews(self.prod, self.contract, self.cut, {"reviews": [row]}))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg required")
    def test_speed_is_applied_to_actual_render_as_well_as_event_math(self):
        self.register()
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "color=c=blue:s=160x90:r=30:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.prod / self.source)],
            capture_output=True, check=True, timeout=20)
        self.cut["timeline"][0].update(in_sec=0, out_sec=2, speed=2)
        self.write(".pipeline/cut.ep01-v2.json", self.cut)
        original = (self.prod / ".pipeline/cut.ep01-v2.json").read_bytes()
        output = assemble_episode(self.prod, candidate=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(self.prod / output["output"])],
                               capture_output=True, text=True, check=True, timeout=10)
        self.assertAlmostEqual(float(json.loads(probe.stdout)["format"]["duration"]), 1.0, delta=0.12)
        self.assertEqual(output["status"], "candidate")
        self.assertEqual((self.prod / ".pipeline/cut.ep01-v2.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
