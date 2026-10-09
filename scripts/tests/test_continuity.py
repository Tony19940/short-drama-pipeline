#!/usr/bin/env python3
"""Shot-to-shot continuity and voicing, from the human review of 012 EP01's 480p draft (2026-10-09)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from director.action_lint import acting_findings  # noqa: E402
from director.continuity import pose_sentence, sequence_findings, shot_findings  # noqa: E402

NAMES = {"dara": "达拉", "kosal": "果萨", "scout": "斥候", "soldier": "高棉士兵（群演）"}


def body(pose: str, spot: str, **extra) -> dict:
    return {"costume": "base", "pose": pose, "spot": spot, **extra}


def shot(sid: str, scene: str = "S1", chars: dict | None = None, **extra) -> dict:
    return {"shot_id": sid, "scene_id": scene, "location_id": "pit", "one_action": "看", "in_from": "", "out_to": "",
            "state": {"characters": chars or {}, "note": "x"}, **extra}


class PoseSpotTests(unittest.TestCase):
    def test_crouch_to_stand_jump_is_an_error(self) -> None:
        shots = [shot("SH003", chars={"dara": body("蹲", "坑底")}), shot("SH004", chars={"dara": body("站", "坑底")})]
        errors, _ = sequence_findings(shots, NAMES)
        self.assertTrue(any("SH004 达拉 opens 站 but SH003 left them 蹲" in e for e in errors), errors)

    def test_shown_move_cutaway_or_ellipsis_pass(self) -> None:
        shown = [shot("SH003", chars={"dara": body("蹲", "坑底", pose_end="站")}, out_to="他撑着坑壁站起来"),
                 shot("SH004", chars={"dara": body("站", "坑底")})]
        self.assertEqual(sequence_findings(shown, NAMES)[0], [])
        cutaway = [shot("SH003", chars={"dara": body("蹲", "坑底")}),
                   shot("SH004", chars={"dara": {"costume": "base", "in_frame": False}, "vibol": body("蹲", "坑沿")}),
                   shot("SH005", chars={"dara": body("站", "坑底")})]
        self.assertFalse(any("达拉 opens" in e for e in sequence_findings(cutaway, NAMES)[0]))
        ellipsis = [shot("SH003", chars={"dara": body("蹲", "坑底")}),
                    shot("SH004", chars={"dara": body("站", "坑沿")}, ellipsis=True)]
        self.assertEqual(sequence_findings(ellipsis, NAMES)[0], [])

    def test_spot_jump_and_missing_pose(self) -> None:
        shots = [shot("SH008", chars={"dara": body("站", "坑沿")}), shot("SH009", chars={"dara": body("站", "坑底")})]
        errors, _ = sequence_findings(shots, NAMES)
        self.assertTrue(any("at 坑底 but SH008 left them at 坑沿" in e for e in errors), errors)
        missing = [shot("SH001", chars={"dara": body("站", "坑底")}), shot("SH002", chars={"dara": {"costume": "base"}})]
        errors, _ = sequence_findings(missing, NAMES)
        self.assertTrue(any("SH002 达拉 in frame without pose/spot" in e for e in errors), errors)

    def test_crowd_is_not_tracked(self) -> None:
        shots = [shot("SH022", chars={"soldier": body("站", "溪边")}), shot("SH023", chars={"soldier": body("蹲", "溪边")}),
                 shot("SH024", chars={"soldier": {"costume": "base"}})]
        self.assertEqual(sequence_findings(shots, NAMES)[0], [])

    def test_pose_values_and_sentence(self) -> None:
        bad = shot("SH001", chars={"dara": body("蹲坐", "坑底")})
        self.assertTrue(any("must be one of" in e for e in shot_findings(bad)[0]))
        good = shot("SH001", chars={"dara": body("蹲", "坑底"), "vibol": {"costume": "b", "in_frame": False, "pose": "站"}})
        self.assertEqual(pose_sentence(good, NAMES), "达拉蹲在坑底")


class SetupTests(unittest.TestCase):
    def test_arrival_needs_a_setup(self) -> None:
        shots = [shot("SH029"), shot("SH030", one_action="斥候冲下坡，扑跪在果萨面前")]
        errors, _ = sequence_findings(shots, NAMES)
        self.assertTrue(any("SH030 「冲下」 happens with no setup" in e for e in errors), errors)

    def test_sound_setup_passes_background_only_warns(self) -> None:
        heard = [shot("SH029", key_sfx=["远处战象长吼", "牛角号"], scale="medium"),
                 shot("SH030", one_action="斥候冲下坡", setup={"shot": "SH029", "how": "远处战象长吼"})]
        errors, warnings = sequence_findings(heard, NAMES)
        self.assertEqual(errors, [])
        self.assertFalse(any("blurred" in w for w in warnings), warnings)
        blurred = [shot("SH008", scale="close", out_to="背景北壁的裂缝往上爬"),
                   shot("SH009", one_action="北壁整面塌下", setup={"shot": "SH008", "how": "裂缝往上爬"})]
        _errors, warnings = sequence_findings(blurred, NAMES)
        self.assertTrue(any("blurred" in w for w in warnings), warnings)
        late = [shot("SH009", one_action="北壁整面塌下", setup={"shot": "SH010", "how": "裂缝"}), shot("SH010")]
        self.assertTrue(any("comes after the event" in e for e in sequence_findings(late, NAMES)[0]))


class EditAndLightTests(unittest.TestCase):
    def test_edit_instruction_in_action_text_is_an_error(self) -> None:
        sh010 = shot("SH010", out_to="手被泥吞没，只剩翻滚的泥面；剪辑在此切黑 1.2 秒")
        errors, _ = shot_findings(sh010)
        self.assertTrue(any("edit instruction" in e for e in errors), errors)

    def test_light_on_a_prop_warns_lightning_does_not(self) -> None:
        _e, warnings = shot_findings(shot("SH017", out_to="刀尖挑着 T 恤，ARCHAEOLOGY 字样露在火光里"))
        self.assertTrue(any("hangs light on a thing" in w for w in warnings), warnings)
        _e, warnings = shot_findings(shot("SH009", in_from="闪电一闪，北壁裂开"))
        self.assertEqual(warnings, [])

    def test_transition_rules(self) -> None:
        shots = [shot("SH010", scene="S1", location_id="pit"), shot("SH011", scene="S2", location_id="graves")]
        _e, warnings = sequence_findings(shots, NAMES)
        self.assertTrue(any("write transition_out" in w for w in warnings), warnings)
        shots[0]["transition_out"] = {"type": "black", "sec": 1.2, "sound": "雷声闷下去变成心跳"}
        self.assertEqual(sequence_findings(shots, NAMES)[1], [])
        self.assertTrue(shot_findings({**shots[0], "transition_out": {"type": "wipe"}})[0])
        self.assertTrue(shot_findings({**shots[0], "transition_out": {"type": "black", "sec": 9}})[0])


class OneVoiceTests(unittest.TestCase):
    def test_person_in_frame_stays_quiet_under_an_off_screen_line(self) -> None:
        sh012 = {"shot_id": "SH012", "dialogue_delivery": "off_camera", "one_action": "达拉撑起上半身", "out_to": ""}
        errors, _ = acting_findings(sh012, {"dara": {"muscle": "张嘴喘，喊出声"}})
        self.assertTrue(any("vocalise over an off-screen line" in e for e in errors), errors)
        quiet = {**sh012, "dialogue_delivery": "on_camera"}
        self.assertFalse(any("vocalise" in e for e in acting_findings(quiet, {"dara": {"muscle": "张嘴喘"}})[0]))


if __name__ == "__main__":
    unittest.main()
