#!/usr/bin/env python3
"""Phase B/C: scene plan, distinct schemes, beat animatic, high-risk control, searchable notes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.animatic import plan_animatic  # noqa: E402
from director.control_path import control_note, recommended_control  # noqa: E402
from director.design_critic import deterministic_pick, schemes_are_distinct  # noqa: E402
from director.model_notes import record_outcome, search_outcomes  # noqa: E402
from director.pipeline import write_artifact  # noqa: E402
from director.scene_plan import performance_intent_of, scene_plan_of  # noqa: E402
from director.show_policy import load_show_policy  # noqa: E402


class ScenePlanOnWriter(unittest.TestCase):
    def test_scene_plan_keeps_line_and_beat_ids(self) -> None:
        scene = {
            "scene_id": "SC01",
            "scene_job": "她要拿到钥匙",
            "whose_scene": "琳",
            "start_state": "门关着",
            "end_state": "钥匙在手里",
            "action": "她伸手去够",
            "resistance": "门缝太窄",
            "beats": [{"beat_id": "b-key", "text": "手指碰到钥匙", "line_id": "L2"}],
            "dialogue": [{"line_id": "L2", "line": "给我。"}],
            "key_sounds": ["铁片轻响"],
        }
        plan = scene_plan_of(scene)
        self.assertEqual(plan["scene_id"], "SC01")
        self.assertEqual(plan["goals"], ["她要拿到钥匙"])
        self.assertEqual(plan["viewpoint"], "琳")
        self.assertEqual(plan["beats"][0]["beat_id"], "b-key")
        self.assertEqual(plan["line_ids"], ["L2"])
        self.assertEqual(plan["sound_events"], ["铁片轻响"])
        intent = performance_intent_of(
            {"in_from": "手已伸出", "t0_phase": "mid", "stimulus": "给我。", "action_timing": [{"from_sec": 0, "to_sec": 2, "text": "继续伸"}]},
            scene,
        )
        self.assertEqual(intent["t0_phase"], "mid")
        self.assertEqual(intent["stimulus"], "给我。")
        self.assertEqual(intent["beats"][0]["to_sec"], 2)


class DistinctSchemes(unittest.TestCase):
    def test_schemes_need_viewpoint_or_rhythm_not_temperature(self) -> None:
        same = {"shots": [{"coverage_type": "master", "duration_sec": 4, "shot_job": "交代"}]}
        other = {"shots": [{"coverage_type": "pov", "duration_sec": 4, "shot_job": "她看见"}]}
        self.assertFalse(schemes_are_distinct(same, dict(same)))
        self.assertTrue(schemes_are_distinct(same, other))

    def test_pick_prefers_landed_shot_over_fewer_warnings(self) -> None:
        card = {"the_shot": {"moment": "钥匙入手", "scale": "close"}, "pov": "琳"}
        miss = {
            "style": "coverage",
            "warnings": [],
            "shots": [{"coverage_type": "master", "scale": "wide", "one_action": "走路", "duration_sec": 4}],
        }
        hit = {
            "style": "pov",
            "warnings": ["x", "y"],
            "shots": [{"coverage_type": "pov", "scale": "close", "one_action": "钥匙入手", "duration_sec": 4, "shot_job": "那一颗"}],
        }
        self.assertEqual(deterministic_pick([miss, hit], card), 1)


class BeatAnimatic(unittest.TestCase):
    def test_plan_follows_performance_beats(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "04-frames").mkdir(parents=True)
            Image.new("RGB", (80, 45)).save(prod / "04-frames" / "SH001.jpg")
            Image.new("RGB", (80, 45)).save(prod / "04-frames" / "SH001-last.jpg")
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [{
                        "shot_id": "SH001",
                        "duration_sec": 8,
                        "scale": "medium",
                        "coverage_type": "single",
                        "one_action": "伸手",
                        "action_timing": [
                            {"from_sec": 0, "to_sec": 2, "text": "刺激来了"},
                            {"from_sec": 2, "to_sec": 8, "text": "手还在伸"},
                        ],
                    }],
                },
            )
            plan = plan_animatic(prod, 1)
            self.assertEqual(len(plan), 2)
            self.assertEqual(plan[0]["seconds"], 2.0)
            self.assertEqual(plan[1]["seconds"], 6.0)
            self.assertEqual(plan[0]["part"], "first")
            self.assertEqual(plan[1]["part"], "last")
            self.assertIn("刺激来了", plan[0]["label"])


class HighRiskControl(unittest.TestCase):
    def test_prop_exchange_is_high_risk_first_last(self) -> None:
        shot = {
            "one_action": "她把旧钥匙交给对面的人",
            "in_from": "钥匙还在她手里",
            "out_to": "钥匙在对面手里",
            "hardest": True,
        }
        note = control_note(shot)
        self.assertEqual(note["risk"], "high")
        self.assertIn("hand_prop_exchange", note["reasons"])
        self.assertEqual(recommended_control(shot), "first_last")

    def test_normal_talking_head_stays_first_frame(self) -> None:
        shot = {"one_action": "她听完", "coverage_type": "single", "move_type": "static"}
        note = control_note(shot)
        self.assertEqual(note["risk"], "normal")
        self.assertEqual(note["recommend"], "first_frame")


class SearchableNotes(unittest.TestCase):
    def test_search_filters_evidence_not_blanket_rules(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            write_artifact(prod, "shot_list.json", {"target_model": "seedance_2_0", "shots": [{"shot_id": "SH001", "scale": "close"}]})
            os_notes = Path(raw) / "notes"
            import os

            os.environ["DIRECTOR_MODEL_NOTES_DIR"] = str(os_notes)
            try:
                record_outcome(
                    prod,
                    "SH001",
                    "fail",
                    ["close", "hands"],
                    "这一条手糊了",
                    "seedance_2_0",
                    model="doubao-seedance-2-0-mini-260615",
                    task_kind="first_last",
                    take_id="take-aaa",
                    evidence="0.8s 手指穿模",
                )
                record_outcome(prod, "SH001", "pass", ["close"], "下一条过了", "seedance_2_0", model="doubao-seedance-2-0-mini-260615")
                fails = search_outcomes(prod, verdict="fail", tag="hands")
                self.assertEqual(len(fails), 1)
                self.assertEqual(fails[0]["take_id"], "take-aaa")
                self.assertEqual(fails[0]["evidence"], "0.8s 手指穿模")
                self.assertEqual(len(search_outcomes(prod, verdict="pass")), 1)
            finally:
                os.environ.pop("DIRECTOR_MODEL_NOTES_DIR", None)


class SceneRehearsalPolicy(unittest.TestCase):
    def test_scene_rehearsal_turns_on_animatic_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / ".pipeline").mkdir()
            (prod / ".pipeline" / "show_policy.json").write_text(
                '{"scene_rehearsal_required": true}',
                encoding="utf-8",
            )
            policy = load_show_policy(prod)
            self.assertTrue(policy.scene_rehearsal_required)
            self.assertTrue(policy.animatic_required)


if __name__ == "__main__":
    unittest.main()
