"""Truthful design review declarations and explicit human review fingerprints."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from director.shot_table import (
    design_review_digest, design_review_errors, record_human_design_review,
    sanitize_shot_table, validate_shot_table,
)
from director.station_agents import _sanitize_design, _sanitize_writer
from test_shot_table import good_shots, table


class HumanDesignReview(unittest.TestCase):
    def test_sanitizers_do_not_invent_review_or_completed_steps(self):
        for normalized in (sanitize_shot_table({"shots": []}), _sanitize_design({"shots": []})):
            self.assertEqual(normalized["visible_change_without_dialogue"], "not_reviewed")
            self.assertNotIn("design_steps_done", normalized)
        writer = _sanitize_writer({"scenes": [{}]})
        self.assertEqual(writer["scenes"][0]["mute_test"], "not_reviewed")
        self.assertEqual(writer["scenes"][0]["preach_check"], "not_reviewed")
        self.assertEqual(_sanitize_writer({"scenes": [{"mute_test": "pass"}]})["scenes"][0]["mute_test"], "pass")

    def test_draft_unknown_is_warning_and_lock_requires_human_evidence(self):
        data = table(good_shots(), visible_change_without_dialogue="unknown", status="draft")
        errors, warnings = validate_shot_table(data)
        self.assertFalse(any("review" in e for e in errors), errors)
        self.assertTrue(any("not reviewed" in w for w in warnings), warnings)
        errors, _ = validate_shot_table(data, require_review=True)
        self.assertTrue(any("human pass" in e for e in errors), errors)
        data["status"] = "locked"
        self.assertTrue(any("human pass" in e for e in validate_shot_table(data)[0]))

    def test_explicit_human_review_is_content_bound(self):
        original = table(good_shots(), status="draft")
        reviewed = record_human_design_review(original, reviewer="director", notes="空手与断槽同框先于盘问，省略不影响理解", reviewed_at=123)
        self.assertNotIn("narrative_review", original)
        self.assertEqual(design_review_errors(reviewed), [])
        reviewed["status"] = "locked"
        reviewed["updated_at"] = 456
        reviewed["shots"][0]["video_status"] = "downloaded"
        self.assertEqual(design_review_errors(reviewed), [])
        changed = copy.deepcopy(reviewed)
        changed["shots"][0]["out_to"] = "关键证据被藏住"
        self.assertNotEqual(design_review_digest(changed), design_review_digest(reviewed))
        self.assertTrue(any("stale" in e for e in design_review_errors(changed)))

    def test_model_or_candidate_choice_cannot_supply_human_pass(self):
        reviewed = record_human_design_review(table(good_shots()), reviewer="director", notes="本场揭示可读", reviewed_at=123)
        reviewed["narrative_review"]["source"] = "critic"
        self.assertTrue(any("source must be human" in e for e in design_review_errors(reviewed)))
        with self.assertRaises(ValueError):
            record_human_design_review({}, reviewer="director", notes="")


if __name__ == "__main__":
    unittest.main()
