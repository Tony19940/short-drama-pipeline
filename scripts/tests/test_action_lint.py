#!/usr/bin/env python3
"""Action text a video model acts out: intentions, landings that add a second action, held actions, prop states.

Cases come from 012 EP01's 480p draft: SH022 drank the water it was only lifting, SH005 stood up out of frame.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from director.action_lint import (  # noqa: E402
    acting_findings,
    action_findings,
    added_action_seconds,
    added_actions,
    completion_cues,
    intent_hits,
    strip_cues,
)
from director.prompts import action_timing_zh, compile_seedance_motion_detail  # noqa: E402
from director.shot_table import needed_seconds, validate_state_chain  # noqa: E402

SH022 = {
    "shot_id": "SH022", "scene_id": "EP01_SC03", "move_type": "static", "scale": "medium", "duration_sec": 3,
    "one_action": "果萨端起递来的竹筒要喝", "in_from": "竹筒已经递到果萨左手里", "out_to": "竹筒口凑到他嘴边",
}
SH005 = {
    "shot_id": "SH005", "move_type": "static", "scale": "otc", "duration_sec": 5,
    "one_action": "维波蹲在坑沿，把手机镜头怼向达拉举着的箭头", "in_from": "维波已经蹲下，手机正往下伸",
    "out_to": "手机停在箭头上方，维波笑着站起",
    "dialogue_ref": [{"character": "vibol", "line": "传说而已。老师都说你的论文是笑话。", "km_sec": 4.4}],
    "dialogue_delivery": "on_camera",
}


def held_sh022() -> dict:
    shot = copy.deepcopy(SH022)
    shot.update(
        one_action="果萨把递来的竹筒抬到离嘴唇一指远",
        out_to="竹筒停在离嘴唇一指远，他眼睛越过竹筒看着画外",
        held_action={"stop_at": "竹筒停在离嘴唇一指远", "unfinished": "喝水", "keep": "竹筒里的水一直是满的"},
    )
    return shot


class IntentTests(unittest.TestCase):
    def test_intention_is_an_error(self) -> None:
        errors, _ = action_findings(SH022)
        self.assertTrue(any("「要喝」" in e and "held_action" in e for e in errors), errors)

    def test_compounds_quotes_and_reported_speech_are_not_intentions(self) -> None:
        for text in ("需要重要主要只要", "他想起奶奶", "琳开口说他要当老板", "「半份准备好」落完", "竹筒停在离嘴唇一指远"):
            self.assertEqual(intent_hits(text), [], text)
        self.assertEqual(intent_hits("她转头要走"), ["要走"])
        self.assertEqual(intent_hits("两人准备把板立回槽"), ["准备把板"])


class LandingTests(unittest.TestCase):
    def test_static_tight_frame_cannot_take_a_standing_landing(self) -> None:
        errors, _ = action_findings(SH005)
        self.assertTrue(any("「站起」" in e and "first_last" in e for e in errors), errors)

    def test_follow_end_frame_or_wide_only_warn(self) -> None:
        for change in ({"move_type": "tilt"}, {"keyframe_plan": "first_last"}, {"scale": "wide"}):
            shot = {**SH005, **change}
            errors, warnings = action_findings(shot)
            self.assertFalse(any("站起" in e for e in errors), (change, errors))
            self.assertTrue(any("站起" in w for w in warnings), (change, warnings))

    def test_exit_negation_cut_and_small_moves(self) -> None:
        exit_shot = {**SH005, "out_to": "他起身走出画左"}
        self.assertEqual(action_findings(exit_shot), ([], []))
        self.assertEqual(added_actions("琳坐着", "仍坐着，没有起身，无人走近"), ([], []))
        self.assertEqual(added_actions("速卡站在石槽旁", "切蹲下"), ([], []))
        self.assertEqual(added_actions("桑南站起来", "人已站直"), ([], []))
        straighten = {**SH005, "one_action": "维波举着手机往坑底凑", "out_to": "他直起身"}
        errors, warnings = action_findings(straighten)
        self.assertEqual(errors, [])
        self.assertTrue(any("直起身" in w for w in warnings))
        self.assertEqual(added_actions("", "听到“一个接一个地倒下了”时竹筒一沉"), ([], []))

    def test_landing_action_needs_time(self) -> None:
        self.assertEqual(added_action_seconds(SH005), 0.8)
        without = {**SH005, "out_to": "手机停在箭头上方"}
        self.assertAlmostEqual(needed_seconds(SH005) - needed_seconds(without), 0.8, places=1)


class HeldActionTests(unittest.TestCase):
    def test_held_shot_passes_and_must_not_say_the_verb(self) -> None:
        self.assertEqual(action_findings(held_sh022()), ([], []))
        bad = held_sh022()
        bad["out_to"] = "竹筒凑到嘴边喝了一口"
        errors, _ = action_findings(bad)
        self.assertTrue(any("still says 「喝」" in e for e in errors), errors)
        empty = {**SH022, "one_action": "果萨抬起竹筒", "out_to": "竹筒停住", "held_action": {"unfinished": "喝水"}}
        errors, _ = action_findings(empty)
        self.assertTrue(any("needs stop_at" in e for e in errors), errors)

    def test_cues_and_strip(self) -> None:
        self.assertIn("喉结", completion_cues("喝水"))
        self.assertEqual(strip_cues("手上接过竹筒；喉结一动；竹筒往嘴边抬。", completion_cues("喝水")), "手上接过竹筒；竹筒往嘴边抬。")
        self.assertEqual(completion_cues("点头"), ["点头"])

    def test_acting_cannot_finish_the_held_action_or_add_a_pose(self) -> None:
        acting = {"kosal": {"business": "接过竹筒", "muscle": "喉结一动", "change": "竹筒往嘴边抬"}}
        errors, _ = acting_findings(held_sh022(), acting)
        self.assertTrue(any("acting.kosal.muscle" in e and "喉结" in e for e in errors), errors)
        fixed = {**SH005, "out_to": "手机停在箭头上方"}
        errors, _ = acting_findings(fixed, {"vibol": {"change": "说完站起，膝盖一直"}})
        self.assertTrue(any("acting.vibol.change" in e and "站起" in e for e in errors), errors)

    def test_compiler_holds_the_stop_and_drops_finishing_beats(self) -> None:
        shot = held_sh022()
        text, beats = action_timing_zh(shot["one_action"], shot["in_from"], shot["out_to"], 4, shot=shot)
        self.assertIn("落幅——竹筒停在离嘴唇一指远，定在这里直到镜头结束，竹筒里的水一直是满的", text)
        self.assertNotIn("喝", text)
        acting = ["果萨：想喝口水，然后把这事了了；藏着营里在死人；手上接过竹筒；喉结一动；竹筒往嘴边抬。"]
        prompt = compile_seedance_motion_detail({"duration_sec": 4}, shot, None, acting_lines=acting, render_sec=4,
                                                audio_block="画中所有人不说话，嘴闭着。")["prompt"]
        self.assertIn("【表演】果萨：手上接过竹筒；竹筒往嘴边抬。", prompt)
        for word in ("想喝", "藏着", "喉结"):
            self.assertNotIn(word, prompt)

    def test_padding_past_paper_length_holds_the_landing(self) -> None:
        shot = {"shot_id": "SH003", "duration_sec": 2, "one_action": "达拉把箭头从土里抠出来", "out_to": "箭头摊在掌心"}
        text, _ = action_timing_zh(shot["one_action"], "", shot["out_to"], 4, shot=shot)
        self.assertIn("箭头摊在掌心，定在这个姿势直到镜头结束", text)
        exit_shot = {**shot, "out_to": "他走出画左"}
        text, _ = action_timing_zh(exit_shot["one_action"], "", exit_shot["out_to"], 4, shot=exit_shot)
        self.assertNotIn("定在这个姿势", text)
        full = {**shot, "duration_sec": 4}
        text, _ = action_timing_zh(full["one_action"], "", full["out_to"], 4, shot=full)
        self.assertIn("箭头摊在掌心，停住，气还没平", text)


class PropStateTests(unittest.TestCase):
    def table(self, *states) -> dict:
        shots = []
        for index, (value, changes) in enumerate(states, start=1):
            shots.append({
                "shot_id": f"SH{index:03d}", "scene_id": "S1", "one_action": "看", "state_changes": changes,
                "state": {"characters": {"kosal": {"costume": "base", "carrying": ["bamboo-tube"]}},
                          "prop_states": {"bamboo-tube": value} if value else {}, "note": "果萨拿着竹筒"},
            })
        return {"shots": shots, "continuity_bible": {}}

    def test_undeclared_change_is_an_error(self) -> None:
        errors, _ = validate_state_chain(self.table(("竹筒里的水是满的", []), ("竹筒是空的", [])))
        self.assertTrue(any("prop.bamboo-tube changes" in e for e in errors), errors)
        errors, _ = validate_state_chain(self.table(("竹筒里的水是满的", []), ("竹筒是空的", ["prop.bamboo-tube"])))
        self.assertEqual(errors, [])
        errors, _ = validate_state_chain(self.table(("竹筒里的水是满的", []), ("", []), ("竹筒里的水是满的", [])))
        self.assertEqual(errors, [])

    def test_prop_state_reaches_the_continuity_line(self) -> None:
        shot = held_sh022()
        shot["state"] = {"characters": {}, "prop_states": {"bamboo-tube": "竹筒里的水是满的"}, "note": "果萨左手拿着竹筒"}
        prompt = compile_seedance_motion_detail({"duration_sec": 4}, shot, None, render_sec=4, audio_block="无对白。")["prompt"]
        self.assertIn("【连戏】果萨左手拿着竹筒；竹筒里的水是满的。", prompt)


if __name__ == "__main__":
    unittest.main()
