#!/usr/bin/env python3
"""Shot table v2: filmability rules, model profiles, deterministic spec projection, human table."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.shot_table import (  # noqa: E402
    SCHEMA,
    compile_specs_from_shot_table,
    dialogue_seconds,
    look_forbidden_tokens,
    needed_seconds,
    render_shot_table_md,
    sanitize_shot_table,
    validate_shot_table,
)
from director.video_profiles import get_profile, profile_brief, resolve_target_model  # noqa: E402

WRITER = {
    "scenes": [
        {
            "scene_id": "EP01_SC01",
            "location_id": "modern-channel",
            "dialogue": [{"character": "速卡", "line": "水往哪走，河床都替你记着。"}],
        },
        {
            "scene_id": "EP01_SC02",
            "location_id": "ancient-shoal",
            "dialogue": [
                {"character": "云朗", "line": "什么人？"},
                {"character": "速卡", "line": "我是高棉人，大湖边来的！我不是细作——"},
            ],
        },
    ]
}
SETS = {
    "sets": [
        {"id": "modern-channel", "name": "现代旧河道遗址"},
        {"id": "ancient-shoal", "name": "古河边浅滩"},
        {"id": "granary", "name": "边寨粮栈"},
    ]
}
LOOK = "# LOOK\n- 画幅：16:9\n- 禁止：现代泰国国旗、现代城市、字幕烧进画面、环绕运镜\n"


def shot(**over) -> dict:
    base = {
        "shot_id": "SH001",
        "scene_id": "EP01_SC01",
        "location_id": "modern-channel",
        "beat": "建置",
        "shot_job": "建立旧河道与石槽",
        "coverage_type": "master",
        "scale": "wide",
        "angle": "eye",
        "height": "standing",
        "lens": "28mm",
        "move_type": "static",
        "move_reason": "",
        "left": "速卡",
        "right": "河",
        "eyeline": "看河",
        "one_action": "速卡站在石槽旁看河道",
        "duration_sec": 5,
        "dialogue_ref": [],
        "dialogue_delivery": "none",
        "key_sfx": ["闷雷"],
        "light": {"day_night": "storm-day", "key_dir": "top-side", "quality": "soft", "color": "wet-slate"},
        "in_from": "开场",
        "out_to": "切蹲下",
        "evidence": [],
    }
    base.update(over)
    return base


def table(shots: list[dict], **over) -> dict:
    data = {
        "schema": SCHEMA,
        "whose_pov": "速卡",
        "left_right_lock": {"EP01_SC01": "槽左人左河右", "EP01_SC02": "高棉左暹罗右"},
        "continuity_bible": {
            "eyeline": "看水",
            "wardrobe": "现代勘测服，SH003 起湿透",
            "day_night": {"EP01_SC01": "storm-day", "EP01_SC02": "dusk"},
            "props": [{"name": "测量杆", "first_scene": "EP01_SC01", "last_scene": "EP01_SC01"}],
            "evidence": [{"what": "空手+断槽", "scene_id": "EP01_SC02"}],
        },
        "visible_change_without_dialogue": "pass",
        "shots": shots,
    }
    data.update(over)
    return sanitize_shot_table(data, writer=WRITER)


def good_shots() -> list[dict]:
    return [
        shot(),
        shot(shot_id="SH002", coverage_type="single", scale="medium", lens="50mm", beat="识水", shot_job="手指伸进凹痕自语",
             one_action="速卡蹲下把手指伸进凹痕低头看水", duration_sec=6,
             dialogue_ref=[{"character": "速卡", "line": "水往哪走，河床都替你记着。"}], dialogue_delivery="post",
             in_from="承接站姿", out_to="雷更近"),
        shot(shot_id="SH003", scene_id="EP01_SC02", location_id="ancient-shoal", coverage_type="master", scale="full", lens="35mm",
             beat="冲上古岸", shot_job="空手与断槽同框", one_action="速卡爬到跪姿摊开空手看断槽", duration_sec=7,
             left="速卡", right="对岸", eyeline="看手", evidence=["空手+断槽"], in_from="古岸", out_to="抬头看火",
             light={"day_night": "dusk", "key_dir": "low-side", "quality": "mixed", "color": "warm-ember"}),
        shot(shot_id="SH004", scene_id="EP01_SC02", location_id="ancient-shoal", coverage_type="otc", scale="otc", lens="50mm",
             beat="被按倒盘问", shot_job="云朗俯视盘问", one_action="云朗按刀俯视速卡贴地抬头答话", duration_sec=9,
             left="速卡", right="云朗", eyeline="互看",
             dialogue_ref=[{"character": "云朗", "line": "什么人？"}, {"character": "速卡", "line": "我是高棉人，大湖边来的！我不是细作——"}],
             dialogue_delivery="post", in_from="按倒", out_to="切绑绳",
             light={"day_night": "dusk", "key_dir": "side", "quality": "hard", "color": "warm-ember"}),
    ]


class ShotTableRules(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = get_profile("seedance_2_0")

    def check(self, data: dict, **kw):
        return validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK, **kw)

    def test_good_table_passes(self) -> None:
        errors, warnings = self.check(table(good_shots()))
        self.assertEqual(errors, [], errors)
        self.assertEqual([w for w in warnings if "no per-shot state" not in w], [])

    def test_dialogue_needs_seconds_and_max_two_lines(self) -> None:
        shots = good_shots()
        shots[3]["duration_sec"] = 6
        errors, _ = self.check(table(shots))
        self.assertTrue(any("needs about" in e for e in errors), errors)
        shots = good_shots()
        shots[3]["dialogue_ref"].append({"character": "云朗", "line": "什么人？"})
        errors, _ = self.check(table(shots))
        self.assertTrue(any("max 2 per shot" in e for e in errors), errors)

    def test_every_writer_line_must_be_assigned_once(self) -> None:
        shots = good_shots()
        shots[3]["dialogue_ref"] = [{"character": "云朗", "line": "什么人？"}]
        errors, _ = self.check(table(shots))
        self.assertTrue(any("line not assigned" in e for e in errors), errors)
        shots = good_shots()
        shots[3]["dialogue_ref"] = [{"character": "云朗", "line": "什么人"}]
        errors, _ = self.check(table(shots))
        self.assertTrue(any("not a writer line" in e for e in errors), errors)

    def test_tight_scale_cannot_show_distance(self) -> None:
        shots = good_shots()
        shots[3]["shot_job"] = "近景盯柱脚水线，远处火把一行行熄"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("cannot show distant content" in e for e in errors), errors)

    def test_axis_flip_inside_scene_fails(self) -> None:
        shots = good_shots()
        shots[3]["left"], shots[3]["right"] = "云朗", "速卡"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("axis lock broken" in e for e in errors), errors)

    def test_prop_after_last_scene_fails(self) -> None:
        shots = good_shots()
        shots[2]["one_action"] = "速卡爬到跪姿举起测量杆看断槽"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("still shows 测量杆" in e for e in errors), errors)

    def test_evidence_must_be_claimed_and_readable(self) -> None:
        shots = good_shots()
        shots[2]["evidence"] = []
        errors, _ = self.check(table(shots))
        self.assertTrue(any("evidence not claimed" in e for e in errors), errors)
        errors, _ = self.check(table(shots), partial=True)
        self.assertFalse(any("evidence not claimed" in e for e in errors), errors)
        shots = good_shots()
        shots[2]["scale"] = "wide"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("sits in wide shot" in e for e in errors), errors)

    def test_forbidden_moves_from_profile_and_look(self) -> None:
        shots = good_shots()
        shots[0]["move_type"] = "orbit"
        shots[0]["move_reason"] = "绕一圈"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("not allowed" in e for e in errors), errors)
        shots = good_shots()
        shots[0]["one_action"] = "航拍旧河道，速卡站在石槽旁"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("drone" in e for e in errors), errors)
        shots = good_shots()
        shots[0]["move_type"] = "handheld"
        shots[0]["move_reason"] = "跟两步"
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=SETS, profile=get_profile("minimax_h3"), look_text=LOOK)
        self.assertTrue(any("handheld not allowed" in e for e in errors), errors)

    def test_model_limits_duration_internal_cuts_and_dialogue_delivery(self) -> None:
        shots = good_shots()
        shots[0]["duration_sec"] = 16
        errors, _ = self.check(table(shots))
        self.assertTrue(any("exceeds model max 15s" in e for e in errors), errors)
        shots = good_shots()
        shots[0]["duration_sec"] = 3
        errors, warnings = self.check(table(shots))
        self.assertEqual(errors, [])
        self.assertTrue(any("below model min" in w for w in warnings), warnings)
        shots = good_shots()
        shots[3]["internal_cuts"] = [{"at_sec": 4, "scale": "close", "one_action": "速卡抬眼"}]
        errors, _ = self.check(table(shots))
        self.assertEqual(errors, [], errors)
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=SETS, profile=get_profile("minimax_h3"), look_text=LOOK)
        self.assertTrue(any("internal_cuts not supported" in e for e in errors), errors)
        shots = good_shots()
        shots[3]["dialogue_delivery"] = "on_camera"
        errors, _ = self.check(table(shots))
        self.assertEqual(errors, [], errors)
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=SETS, profile=get_profile("minimax_h3"), look_text=LOOK)
        self.assertTrue(any("on_camera dialogue not supported" in e for e in errors), errors)

    def test_one_shot_one_set_and_no_repeat_setup(self) -> None:
        shots = good_shots()
        shots[2]["one_action"] = "速卡爬上古河边浅滩，被拖进边寨粮栈绑柱"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("cannot visit two sets" in e for e in errors), errors)
        shots = good_shots()
        shots[1].update(scale="wide", coverage_type="master", left="速卡", right="河", dialogue_ref=[], dialogue_delivery="none")
        shots[3]["dialogue_ref"] = [{"character": "云朗", "line": "什么人？"}, {"character": "速卡", "line": "我是高棉人，大湖边来的！我不是细作——"}]
        errors, _ = self.check(table(shots))
        self.assertTrue(any("repeats SH001" in e for e in errors), errors)

    def test_design_cannot_carry_prompts_and_total_sec_is_sum(self) -> None:
        shots = good_shots()
        shots[0]["video_prompt"] = "cinematic"
        data = table(shots)
        self.assertNotIn("video_prompt", data["shots"][0])
        self.assertEqual(data["total_sec"], 27)
        data["total_sec"] = 30
        errors, _ = self.check(data)
        self.assertTrue(any("total_sec 30 != sum" in e for e in errors), errors)

    def test_timing_helpers(self) -> None:
        self.assertEqual(dialogue_seconds(["什么人？"]), 1.6)
        self.assertGreater(needed_seconds(good_shots()[3]), 7.0)
        self.assertEqual(look_forbidden_tokens(LOOK), ["现代泰国国旗", "现代城市", "字幕烧进画面", "环绕运镜"])

    def test_legacy_validate_shot_list_dispatches_to_v2(self) -> None:
        from director.pipeline import validate_shot_list

        data = table(good_shots())
        self.assertEqual(validate_shot_list(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK), [])
        legacy = {"shots": [{"shot_id": "SH001", "beat": "hook", "shot_job": "see the torch take", "coverage_type": "master", "move_needed": "static"}], "left_right_lock": "Dara left", "visible_change_without_dialogue": "pass", "design_steps_done": [1, 2, 3, 4, 5, 6, 7]}
        self.assertEqual(validate_shot_list(legacy), [])


class ShotState(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = get_profile("seedance_2_0")

    # ---- per-shot state -------------------------------------------------------------

    def _stateful_shots(self) -> list[dict]:
        shots = good_shots()
        shots[0]["state"] = {"characters": {"sokha": {"costume": "dry", "carrying": ["survey-pole"]}}, "props": ["sluice-intact"], "note": "干衣背杆无绳"}
        shots[1]["state"] = {"characters": {"sokha": {"costume": "dry", "carrying": ["survey-pole"]}}, "props": ["sluice-intact"], "note": "手指探槽"}
        shots[2]["state"] = {"characters": {"sokha": {"costume": "wet"}}, "props": ["sluice-broken"], "note": "湿衣无杆无绳"}
        shots[2]["state_changes"] = ["sokha.costume", "sokha.carrying"]
        shots[3]["state"] = {"characters": {"sokha": {"costume": "wet", "binding": "wrists_behind", "bound_with": "hemp-rope"}, "yunlong": {"costume": "base"}}, "note": "反剪麻绳"}
        shots[3]["state_changes"] = ["sokha.binding", "sokha.bound_with"]
        return shots

    def _stateful_bible(self) -> dict:
        return {
            "eyeline": "看水",
            "wardrobe": "现代勘测服，SH003 起湿透",
            "day_night": {"EP01_SC01": "storm-day", "EP01_SC02": "dusk"},
            "props": [
                {"name": "测量杆", "first_scene": "EP01_SC01", "last_scene": "EP01_SC01", "assets": ["survey-pole"], "aliases": ["测量杆"]},
                {"name": "旧闸石槽", "first_scene": "EP01_SC01", "last_scene": "EP01_SC02", "assets": ["sluice-intact", "sluice-broken"], "aliases": ["石槽", "凹痕", "断槽"]},
                {"name": "麻绳", "first_scene": "EP01_SC02", "last_scene": "EP01_SC02", "assets": ["hemp-rope"], "aliases": ["麻绳"]},
            ],
            "evidence": [{"what": "空手+断槽", "scene_id": "EP01_SC02"}],
        }

    def test_state_chain_passes_when_changes_are_declared(self) -> None:
        data = table(self._stateful_shots(), continuity_bible=self._stateful_bible())
        errors, warnings = validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("no per-shot state" in w for w in warnings), warnings)

    def test_state_change_without_declaration_fails(self) -> None:
        shots = self._stateful_shots()
        shots[3]["state_changes"] = []
        data = table(shots, continuity_bible=self._stateful_bible())
        errors, _ = validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("sokha.binding changes none→wrists_behind" in e for e in errors), errors)
        shots = self._stateful_shots()
        shots[2]["state_changes"] = ["sokha.costume"]
        errors, _ = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("sokha.carrying changes" in e for e in errors), errors)

    def test_state_all_or_nothing_note_and_binding_rules(self) -> None:
        shots = self._stateful_shots()
        del shots[1]["state"]
        errors, _ = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("SH002 missing state" in e for e in errors), errors)
        shots = self._stateful_shots()
        shots[0]["state"]["note"] = ""
        shots[3]["state"]["characters"]["sokha"]["bound_with"] = ""
        shots[3]["state"]["characters"]["yunlong"]["binding"] = "hogtied"
        errors, _ = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("SH001 state needs a note" in e for e in errors), errors)
        self.assertTrue(any("needs bound_with" in e for e in errors), errors)
        self.assertTrue(any("binding must be one of" in e for e in errors), errors)
        plain = table(good_shots())
        _, warnings = validate_shot_table(plain, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("no per-shot state" in w for w in warnings), warnings)

    def test_state_props_outside_bible_span_fail(self) -> None:
        shots = self._stateful_shots()
        shots[2]["state"]["characters"]["sokha"]["carrying"] = ["survey-pole"]
        shots[2]["state_changes"] = ["sokha.costume"]
        errors, _ = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("keeps survey-pole after its last scene EP01_SC01" in e for e in errors), errors)
        shots = self._stateful_shots()
        shots[0]["state"]["characters"]["sokha"]["binding"] = "wrists_front"
        shots[0]["state"]["characters"]["sokha"]["bound_with"] = "hemp-rope"
        errors, _ = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("hemp-rope before its first scene" in e for e in errors), errors)

    def test_state_warns_when_named_cast_is_missing(self) -> None:
        shots = self._stateful_shots()
        del shots[3]["state"]["characters"]["yunlong"]
        writer = dict(WRITER, series_bible={"characters": [{"id": "sokha", "name": "速卡"}, {"id": "yunlong", "name": "云朗"}]})
        _, warnings = validate_shot_table(table(shots, continuity_bible=self._stateful_bible()), writer=writer, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("SH004 mentions 云朗 but state.characters has no yunlong" in w for w in warnings), warnings)

    def test_specs_and_markdown_carry_state(self) -> None:
        data = table(self._stateful_shots(), continuity_bible=self._stateful_bible(), status="locked")
        specs = compile_specs_from_shot_table(data)
        self.assertEqual(specs["shot_specs"][3]["state"]["characters"]["sokha"]["binding"], "wrists_behind")
        self.assertEqual(specs["shot_specs"][2]["state_changes"], ["sokha.costume", "sokha.carrying"])
        md = render_shot_table_md(data, title="t")
        self.assertIn("locked（人已接受 4 镜", md)
        self.assertIn("- **状态**：反剪麻绳（变：sokha.binding、sokha.bound_with）", md)

    def test_package_refs_follow_state_not_keywords(self) -> None:
        from director.pipeline import asset_refs_for_package
        from director.prompts import compile_keyframe_prompt_zh, compile_seedance_motion_from_spec

        assets = {"assets": [
            {"asset_id": "LOC_SHOAL_V1", "type": "location", "binds_to": "ancient-shoal", "file": "02-assets/scenes/ancient-shoal/master.jpg"},
            {"asset_id": "LOC_SHOAL_NIGHT_V1", "type": "location", "binds_to": "ancient-shoal", "file": "02-assets/scenes/ancient-shoal-night/master.jpg"},
            {"asset_id": "CHAR_SOKHA_V1", "type": "character", "binds_to": "sokha", "file": "02-assets/characters/sokha/master.jpg"},
            {"asset_id": "CHAR_SOKHA_FACE_V1", "type": "character", "binds_to": "sokha", "file": "02-assets/characters/sokha/face.jpg"},
            {"asset_id": "CHAR_SOKHA_WET_V1", "type": "costume_state", "binds_to": "sokha", "file": "02-assets/characters/sokha-wet/master.jpg"},
            {"asset_id": "CHAR_PATROL_V1", "type": "character", "binds_to": "patrol", "file": "02-assets/characters/patrol/master.jpg"},
            {"asset_id": "PROP_ROPE_V1", "type": "prop", "binds_to": "hemp-rope", "file": "02-assets/props/hemp-rope/master.jpg"},
            {"asset_id": "PROP_POLE_V1", "type": "prop", "binds_to": "survey-pole", "file": "02-assets/props/survey-pole/master.jpg"},
        ]}
        tbl = {
            "whose_pov": "速卡",
            "continuity_bible": {"props": [{"name": "麻绳", "assets": ["hemp-rope"], "aliases": ["麻绳"]}, {"name": "测量杆", "assets": ["survey-pole"]}], "cast_assets": {"khmer_patrol": "patrol"}},
        }
        writer = {"series_bible": {"characters": [{"id": "sokha", "name": "速卡"}, {"id": "khmer_patrol", "name": "高棉巡丁"}]}}
        # Text never says rope; state does. Wide shot: bound prop comes along.
        wide = shot(scene_id="EP01_SC02", location_id="ancient-shoal", scale="full", one_action="暹罗前队踏上浅滩人仰马翻",
                    state={"characters": {"sokha": {"costume": "wet", "binding": "wrists_behind", "bound_with": "hemp-rope"}, "khmer_patrol": {"costume": "base"}}, "props": [], "note": "反剪麻绳仍在"})
        refs, costume, loc = asset_refs_for_package({}, wide, assets, table=tbl, writer=writer)
        self.assertIn("PROP_ROPE_V1", refs)
        self.assertIn("CHAR_SOKHA_WET_V1", refs)
        self.assertNotIn("CHAR_SOKHA_V1", refs)
        self.assertIn("CHAR_PATROL_V1", refs)
        self.assertNotIn("PROP_POLE_V1", refs)
        self.assertEqual(refs[0], "LOC_SHOAL_V1")
        self.assertEqual(costume, "sokha-wet")
        # Close-up: the rope is out of frame unless the text names it.
        tight = shot(scene_id="EP01_SC02", location_id="ancient-shoal", scale="close", one_action="速卡盯着河面",
                     state={"characters": {"sokha": {"costume": "wet", "binding": "wrists_behind", "bound_with": "hemp-rope"}}, "note": "绳在画外"})
        refs, _, _ = asset_refs_for_package({}, tight, assets, table=tbl, writer=writer)
        self.assertNotIn("PROP_ROPE_V1", refs)
        named = shot(scene_id="EP01_SC02", location_id="ancient-shoal", scale="close", one_action="麻绳勒进速卡手腕",
                     state={"characters": {"sokha": {"costume": "wet", "binding": "wrists_behind", "bound_with": "hemp-rope"}}, "note": "绳特写"})
        refs, _, _ = asset_refs_for_package({}, named, assets, table=tbl, writer=writer)
        self.assertIn("PROP_ROPE_V1", refs)
        # Night plate by state.location; character out of frame gets no refs.
        night = shot(scene_id="EP01_SC02", location_id="ancient-shoal", scale="insert", one_action="柱脚水线",
                     state={"characters": {"sokha": {"costume": "wet", "in_frame": False}}, "location": "ancient-shoal-night", "note": "人在画外"})
        refs, _, loc = asset_refs_for_package({}, night, assets, table=tbl, writer=writer)
        self.assertEqual(refs, ["LOC_SHOAL_NIGHT_V1"])
        self.assertEqual(loc, "ancient-shoal-night")
        # Prompts carry the note.
        self.assertIn("连戏必须照做：反剪麻绳仍在。", compile_keyframe_prompt_zh({}, wide))
        self.assertIn("连戏不变：反剪麻绳仍在。", compile_seedance_motion_from_spec({}, wide))
        # No state: names in text, no production-specific literals.
        bare = shot(scene_id="EP01_SC02", location_id="ancient-shoal", one_action="高棉巡丁按倒速卡，拿出麻绳")
        refs, costume, _ = asset_refs_for_package({}, bare, assets, table=tbl, writer=writer)
        self.assertIn("CHAR_SOKHA_V1", refs)
        self.assertIn("CHAR_PATROL_V1", refs)
        self.assertIn("PROP_ROPE_V1", refs)
        self.assertEqual(costume, "")



class SpecProjectionAndRender(unittest.TestCase):
    def test_specs_project_without_guessing(self) -> None:
        from director.pipeline import validate_shot_specs

        data = table(good_shots())
        specs = compile_specs_from_shot_table(data)
        self.assertEqual(len(specs["shot_specs"]), 4)
        first = specs["shot_specs"][0]
        self.assertEqual(first["focal_length"], "28mm")
        self.assertEqual(first["left"], "速卡")
        self.assertEqual(first["intensity"], 0)
        self.assertEqual(first["day_night"], "storm-day")
        fourth = specs["shot_specs"][3]
        self.assertEqual(fourth["dialogue_line"], "什么人？")
        self.assertEqual(len(fourth["dialogue_lines"]), 2)
        self.assertEqual(fourth["axis_side"], "高棉左暹罗右")
        self.assertEqual(validate_shot_specs(specs, WRITER), [])

    def test_insert_and_pov_specs_need_no_sides(self) -> None:
        from director.pipeline import validate_shot_specs

        shots = good_shots()
        shots.append(shot(shot_id="SH005", scene_id="EP01_SC02", location_id="ancient-shoal", coverage_type="insert", scale="insert",
                          lens="50mm", beat="水线", shot_job="看清柱脚水线", one_action="水线沿木纹上升一指", left="", right="",
                          eyeline="", duration_sec=4, in_from="她看向柱脚", out_to="水线更高",
                          light={"day_night": "dusk", "key_dir": "side", "quality": "soft", "color": "warm-ember"}))
        specs = compile_specs_from_shot_table(table(shots))
        self.assertEqual(validate_shot_specs(specs, WRITER), [])

    def test_design_cache_is_keyed_by_inputs(self) -> None:
        from director.station_agents import _load_design_cache, _save_design_cache, clear_design_cache

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            prod.mkdir()
            _save_design_cache(prod, {"key": "k1", "header": {"whose_pov": "a"}, "scenes": {"S1": [{"shot_id": "SH001"}]}})
            self.assertEqual(_load_design_cache(prod, "k1")["scenes"]["S1"][0]["shot_id"], "SH001")
            self.assertIsNone(_load_design_cache(prod, "k2")["header"])
            clear_design_cache(prod)
            self.assertIsNone(_load_design_cache(prod, "k1")["header"])

    def test_legacy_spec_flatten_no_longer_invents_sides(self) -> None:
        from director.station_agents import _flatten_spec_groups

        spec = {"shot_id": "SH001", "content": "远处火把", "blocking": "", "movement": {"move_type": "static"}}
        _flatten_spec_groups(spec, "16:9")
        self.assertNotIn("left", spec)
        self.assertNotIn("focal_length", spec)
        self.assertEqual(spec["move_type"], "static")

    def test_render_markdown_table(self) -> None:
        data = table(good_shots())
        md = render_shot_table_md(data, title="第 01 集 水认得旧路", profile=get_profile("seedance_2_0"), warnings=["x"])
        self.assertIn("| SH004 | EP01_SC02 | 9 | otc |", md)
        self.assertIn("## 左右锁", md)
        self.assertIn("测量杆（EP01_SC01 → EP01_SC01）", md)
        self.assertIn("空手+断槽 → SH003", md)
        self.assertIn("总时长**：27 秒", md)
        self.assertIn("Seedance 2.0", md)


class Profiles(unittest.TestCase):
    def test_profiles_and_aliases(self) -> None:
        self.assertEqual(get_profile("doubao-seedance-2-0-mini")["id"], "seedance_2_0")
        self.assertEqual(get_profile("h3")["id"], "minimax_h3")
        self.assertEqual(get_profile("nonsense")["id"], "seedance_2_0")
        brief = profile_brief(get_profile("seedance_2_0"))
        self.assertEqual(brief["shot_seconds"], {"min": 4, "max": 15})
        self.assertTrue(brief["one_shot_may_cut_inside"])
        self.assertIn("on_camera", brief["dialogue_delivery_options"])
        self.assertEqual(profile_brief(get_profile("minimax_h3"))["dialogue_delivery_options"], ["post"])
        self.assertFalse(get_profile("seedance_2_5")["verified"])

    def test_resolve_target_model_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            (prod / "01-bible").mkdir(parents=True)
            (prod / "01-bible" / "confirm.md").write_text("- 出片：MiniMax H3 图生视频", encoding="utf-8")
            old = {k: os.environ.pop(k, None) for k in ("DIRECTOR_TARGET_MODEL", "ARK_SEEDANCE_MODEL", "DIRECTOR_VIDEO_BACKEND", "LOCAL_H3_BASE", "ARK_API_KEY")}
            try:
                self.assertEqual(resolve_target_model(prod), "minimax_h3")
                self.assertEqual(resolve_target_model(prod, "seedance"), "seedance_2_0")
                os.environ["DIRECTOR_TARGET_MODEL"] = "seedance_2_5"
                self.assertEqual(resolve_target_model(prod), "seedance_2_5")
            finally:
                for key, value in old.items():
                    os.environ.pop(key, None)
                    if value is not None:
                        os.environ[key] = value


class DesignContext(unittest.TestCase):
    def test_design_context_carries_full_episode_and_profile(self) -> None:
        from director.station_agents import _design_base_context, _system

        prod = ROOT / "productions" / "009-siem-reap"
        ctx = _design_base_context(prod, "seedance_2_0")
        self.assertIn("水往哪走", ctx["episode_text"])
        self.assertEqual(len(ctx["writer"]["scenes"]), 3)
        self.assertEqual(ctx["writer"]["scenes"][0]["end_state"][:1], "人")
        self.assertEqual([s["id"] for s in ctx["sets"]], ["modern-channel", "ancient-shoal", "granary"])
        self.assertEqual(ctx["target_profile"]["target_model"], "seedance_2_0")
        self.assertTrue(any(c["slug"] == "sokha" for c in ctx["characters"]))
        system = _system("design")
        self.assertIn("shot-table-v2", system)
        self.assertIn("摄影机契约", system)
        self.assertIn("什么时候切", system)

    def test_spec_station_compiles_from_v2_without_tokens(self) -> None:
        from director.pipeline import write_artifact
        from director.station_agents import run_station_agent

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            (prod / "02-assets").mkdir(parents=True)
            (prod / "02-assets" / "LOOK.md").write_text(LOOK, encoding="utf-8")
            write_artifact(prod, "writer.json", copy.deepcopy(WRITER))
            write_artifact(prod, "shot_list.json", table(good_shots()))
            result = run_station_agent(prod, "spec")
            self.assertFalse(result["used_tokens"])
            self.assertEqual(result["origin"], "compiled-from-shot-table")
            specs = json.loads((prod / ".pipeline" / "shot_specs.json").read_text(encoding="utf-8"))
            self.assertEqual(len(specs["shot_specs"]), 4)

    def test_package_station_compiles_from_v2_without_tokens(self) -> None:
        from director.pipeline import compile_packages_from_specs, read_artifact, validate_packages
        from director.station_agents import run_station_agent

        prod = ROOT / "productions" / "009-siem-reap"
        if not (prod / ".pipeline" / "shot_specs.json").exists():
            self.skipTest("009 shot specs missing")
        data = compile_packages_from_specs(prod, target_model="seedance_2_0")
        errors = validate_packages(data, read_artifact(prod, "assets.json"), read_artifact(prod, "shot_specs.json"))
        self.assertEqual(errors, [], errors)
        self.assertEqual(len(data["packages"]), 21)
        self.assertEqual(data["episode_target_model"], "seedance_2_0")
        self.assertFalse(data["confirmed"])
        by_id = {item["shot_id"]: item for item in data["packages"]}
        self.assertIn("PROP_SURVEY_POLE_V1", by_id["SH001"]["asset_refs"])
        self.assertIn("PROP_SLUICE_INTACT_V1", by_id["SH001"]["asset_refs"])
        self.assertNotIn("PROP_SURVEY_POLE_V1", by_id["SH005"]["asset_refs"])
        self.assertTrue(any("WET" in ref for ref in by_id["SH005"]["asset_refs"]))
        self.assertTrue(any("NIGHT" in ref for ref in by_id["SH016"]["asset_refs"]))
        self.assertTrue(any("SIAMESE" in ref or "RIDER" in ref for ref in by_id["SH013"]["asset_refs"]))
        self.assertIn("PROP_HEMP_ROPE_V1", by_id["SH013"]["asset_refs"])
        self.assertNotIn("PROP_HEMP_ROPE_V1", by_id["SH011"]["asset_refs"])
        self.assertEqual(by_id["SH013"]["continuity"]["binding"], "wrists_behind")
        self.assertEqual(by_id["SH019"]["asset_refs"], ["LOC_GRANARY_V1"])
        self.assertIn("连戏必须照做", by_id["SH010"]["image_prompt"])
        self.assertIsNone(data.get("warnings"))
        self.assertEqual(by_id["SH001"]["prompt_language"], "zh")
        self.assertEqual(by_id["SH004"]["gen_mode"], "flf2v")
        self.assertEqual(by_id["SH015"]["gen_mode"], "video_extend")
        self.assertEqual(by_id["SH019"]["gen_mode"], "i2v_first")
        self.assertEqual(by_id["SH021"]["gen_mode"], "flf2v")
        self.assertIn("LOC_GRANARY_V1", by_id["SH017"]["asset_refs"])
        self.assertFalse(any("SIAMESE" in ref or "RIDER" in ref for ref in by_id["SH005"]["asset_refs"]))
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / "009"
            shutil.copytree(prod, clone, ignore=shutil.ignore_patterns("05-shots", "06-export", "04-frames"))
            result = run_station_agent(clone, "package")
            self.assertFalse(result["used_tokens"])
            self.assertEqual(result["origin"], "compiled-from-shot-table")


if __name__ == "__main__":
    unittest.main()
