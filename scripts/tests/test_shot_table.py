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
    fit_writer_dialogue,
    has_compound_action,
    lock_axis_text,
    lock_display,
    lock_is_present,
    lock_parts,
    look_forbidden_tokens,
    needed_seconds,
    pace_enforcement,
    pace_metrics,
    pack_dialogue_for_budget,
    picture_is_locked,
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

    def test_sanitize_keeps_camera_id(self) -> None:
        shots = good_shots()
        shots[0]["camera_id"] = "C10"
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][0]["camera_id"], "C10")

    def test_lock_parts_string_vs_dict_and_axis_side_text(self) -> None:
        self.assertEqual(lock_parts("柜左门右"), {"plate": "柜左门右", "axis": "柜左门右"})
        self.assertEqual(lock_parts({"plate": "柜左门右", "axis": "琳左波帕右"}), {"plate": "柜左门右", "axis": "琳左波帕右"})
        self.assertEqual(lock_parts({"background": "柜左", "line": "轴同侧"}), {"plate": "柜左", "axis": "轴同侧"})
        self.assertTrue(lock_is_present({"plate": "柜左"}))
        self.assertTrue(lock_is_present({"axis": "琳左"}))
        self.assertFalse(lock_is_present({}))
        self.assertFalse(lock_is_present(""))
        self.assertEqual(lock_axis_text({"plate": "柜左门右", "axis": "琳左波帕右"}), "琳左波帕右")
        self.assertIn("底板", lock_display({"plate": "柜左", "axis": "琳左"}))
        data = table(
            good_shots(),
            left_right_lock={"EP01_SC01": {"plate": "槽左河右", "axis": "人左河右"}, "EP01_SC02": "高棉左暹罗右"},
        )
        specs = compile_specs_from_shot_table(data)
        self.assertEqual(specs["shot_specs"][0]["axis_side"], "人左河右")
        self.assertEqual(specs["shot_specs"][3]["axis_side"], "高棉左暹罗右")
        errors, _ = self.check(data)
        self.assertEqual(errors, [], errors)
        md = render_shot_table_md(data, title="锁")
        self.assertIn("底板", md)
        self.assertIn("轴", md)

    def test_sanitize_ceils_subsecond_duration_deficit(self) -> None:
        shots = good_shots()
        # four clauses → 6.5s action; no lines. 6s is a <1s rounding miss → bump to 7.
        shots[0]["one_action"] = "速卡站在石槽旁，低头看水，伸手探槽，停住"
        shots[0]["duration_sec"] = 6
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][0]["duration_sec"], 7)
        errors, _ = self.check(cleaned)
        self.assertFalse(any("needs about" in e and "SH001" in e for e in errors), errors)
        # 1.5s short is real coverage missing, not rounding — do not invent a second shot's worth.
        shots = good_shots()
        shots[0]["one_action"] = "速卡站在石槽旁，低头看水，伸手探槽，停住"
        shots[0]["duration_sec"] = 5
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][0]["duration_sec"], 5)
        errors, _ = self.check(cleaned)
        self.assertTrue(any("SH001 needs about" in e for e in errors), errors)

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

    def test_sentence_fragments_cover_a_long_writer_line(self) -> None:
        long_line = (
            "黑的是给他看的。红的是真的。U盘里有最后一次对账，还有货梯口监控。"
            "监控只到我走进井边。后面被切了。切点在第十四秒。"
            "够证明有人等在那儿，不够直接判。所以才要桑南看。"
        )
        writer = {
            "scenes": [
                {"scene_id": "EP11_SC01", "location_id": "storeroom", "dialogue": [{"character": "bopha", "line": long_line}]}
            ]
        }
        fitted = fit_writer_dialogue({"scenes": [{"scene_id": "EP11_SC01", "dialogue": [{"line": long_line}]}]})
        packs = [item["line"] for item in fitted["scenes"][0]["dialogue"]]
        self.assertGreater(len(packs), 1, packs)
        self.assertLessEqual(max(dialogue_seconds([p]) for p in packs), 13.0)
        self.assertGreater(len(pack_dialogue_for_budget(long_line, 12.0)), 1)
        shots = []
        for index, pack in enumerate(packs):
            shots.append(
                {
                    "shot_id": f"SH{index + 1:03d}",
                    "scene_id": "EP11_SC01",
                    "location_id": "storeroom",
                    "beat": "规则",
                    "shot_job": "开口" if index == 0 else "拆句",
                    "coverage_type": "otc" if index % 2 == 0 else "reaction",
                    "scale": "otc" if index % 2 == 0 else "close",
                    "angle": "eye",
                    "height": "chest",
                    "lens": "50mm",
                    "move_type": "static",
                    "left": "琳" if index % 2 == 0 else "柜",
                    "right": "波帕" if index % 2 == 0 else "琳",
                    "eyeline": "看账",
                    "one_action": "波帕开口" if index == 0 else "听着停一拍",
                    "duration_sec": 15,
                    "dialogue_ref": [{"character": "bopha", "line": pack}],
                    "dialogue_delivery": "post",
                    "in_from": "起",
                    "out_to": "停",
                    "evidence": [],
                }
            )
        payload = sanitize_shot_table(
            {
                "schema": SCHEMA,
                "whose_pov": "rin",
                "left_right_lock": {"EP11_SC01": "柜左门右"},
                "continuity_bible": {"eyeline": "", "wardrobe": "", "day_night": {}, "props": [], "evidence": []},
                "visible_change_without_dialogue": "pass",
                "shots": shots,
            },
            writer=writer,
        )
        errors, _ = validate_shot_table(
            payload,
            writer=writer,
            sets={"sets": [{"id": "storeroom", "name": "storeroom"}]},
            profile=get_profile("seedance_2_0"),
        )
        self.assertFalse(any("not a writer line" in e or "line not assigned" in e or "needs about" in e for e in errors), errors)

    def test_tight_scale_cannot_show_distance(self) -> None:
        shots = good_shots()
        shots[3]["shot_job"] = "近景盯柱脚水线，远处火把一行行熄"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("cannot show distant content" in e for e in errors), errors)

    def test_axis_flip_inside_scene_fails(self) -> None:
        shots = good_shots()
        shots[3]["left"], shots[3]["right"] = "云朗", "速卡"
        errors, warnings = self.check(table(shots))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("axis lock broken" in w for w in warnings), warnings)

    def test_prop_after_last_scene_fails(self) -> None:
        shots = good_shots()
        shots[2]["one_action"] = "速卡爬到跪姿举起测量杆看断槽"
        errors, _ = self.check(table(shots))
        self.assertTrue(any("still shows 测量杆" in e for e in errors), errors)

    def test_sanitize_unwraps_evidence_what_dicts(self) -> None:
        shots = good_shots()
        shots[2]["evidence"] = [{"what": "空手+断槽"}]
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][2]["evidence"], ["空手+断槽"])
        errors, _ = self.check(cleaned)
        self.assertFalse(any("evidence not claimed" in e for e in errors), errors)

    def test_evidence_must_be_claimed_and_readable(self) -> None:
        shots = good_shots()
        shots[2]["evidence"] = []
        errors, _ = self.check(table(shots))
        self.assertTrue(any("evidence not claimed" in e for e in errors), errors)
        errors, _ = self.check(table(shots), partial=True)
        self.assertFalse(any("evidence not claimed" in e for e in errors), errors)
        shots = good_shots()
        shots[2]["scale"] = "wide"
        errors, warnings = self.check(table(shots))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("sits in wide shot" in w for w in warnings), warnings)

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
        dirty = table(good_shots())
        dirty["shots"][0]["duration_sec"] = 16
        errors, _ = self.check(dirty)
        self.assertTrue(any("exceeds model max 15s" in e for e in errors), errors)
        shots = good_shots()
        shots[0]["duration_sec"] = 3
        errors, warnings = self.check(table(shots))
        self.assertEqual(errors, [])
        self.assertTrue(any("below model min" in w for w in warnings), warnings)
        shots = good_shots()
        shots[3]["internal_cuts"] = [{"at_sec": 4, "scale": "close", "one_action": "速卡抬眼"}]
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][3]["internal_cuts"], [])
        dirty = copy.deepcopy(cleaned)
        dirty["shots"][3]["internal_cuts"] = [{"at_sec": 4, "scale": "close", "one_action": "速卡抬眼"}]
        errors, _ = self.check(dirty)
        self.assertTrue(any("internal_cuts not supported" in e for e in errors), errors)
        errors, _ = validate_shot_table(dirty, writer=WRITER, sets=SETS, profile=get_profile("minimax_h3"), look_text=LOOK)
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
        self.assertEqual(needed_seconds(shot(coverage_type="reaction", one_action="琳抬眼", duration_sec=1.5)), 1.2)
        self.assertEqual(needed_seconds(shot(coverage_type="insert", one_action="名单最上是她的名字", duration_sec=2)), 1.5)
        one_line = shot(
            coverage_type="single",
            one_action="春安把旧钥匙扔到琳脚边",
            dialogue_ref=[{"character": "春安", "line": "油会自己干。"}],
            dialogue_delivery="post",
        )
        self.assertLess(needed_seconds(one_line), 3.2)
        self.assertGreaterEqual(needed_seconds(one_line), 2.5)
        self.assertEqual(look_forbidden_tokens(LOOK), ["现代泰国国旗", "现代城市", "字幕烧进画面", "环绕运镜"])

    def test_tight_24_opening_hook_allows_one_second_insert(self) -> None:
        shots = good_shots()
        shots[0].update(
            coverage_type="insert",
            scale="insert",
            one_action="名单纸边自己轻轻发颤",
            duration_sec=1.0,
            opening_hook=True,
            dialogue_ref=[],
            dialogue_delivery="none",
        )
        locked = table(shots, locked_picture=True, status="ready")
        locked["shots"][0]["duration_sec"] = 1.0
        locked["shots"][0]["opening_hook"] = True
        locked_errors, _ = self.check(locked)
        self.assertTrue(any("needs about" in e and "SH001" in e for e in locked_errors), locked_errors)
        candidate = table(shots, locked_picture=False, status="candidate", pace_profile="tight_2_4", resplit_of="shot_list.json")
        candidate["shots"][0]["opening_hook"] = True
        candidate["shots"][0]["duration_sec"] = 1.0
        errors, warnings = self.check(candidate)
        self.assertFalse(any("needs about" in e and "SH001" in e for e in errors), errors)
        self.assertTrue(any("opening hook" in w and "SH001" in w for w in warnings), warnings)

    def test_paper_float_duration_is_kept(self) -> None:
        shots = good_shots()
        shots[0]["coverage_type"] = "reaction"
        shots[0]["one_action"] = "琳抬眼"
        shots[0]["duration_sec"] = 1.5
        cleaned = table(shots)
        self.assertEqual(cleaned["shots"][0]["duration_sec"], 1.5)
        errors, warnings = self.check(cleaned)
        self.assertFalse(any("needs about" in e and "SH001" in e for e in errors), errors)
        self.assertTrue(any("below model min" in w and "SH001" in w for w in warnings), warnings)

    def test_compound_action_must_split_except_must_hold(self) -> None:
        self.assertTrue(has_compound_action({"one_action": "琳捡起钥匙再推车走向尽头"}))
        self.assertFalse(has_compound_action({"one_action": "女工肩穿进白衬衫再穿出"}))
        self.assertFalse(has_compound_action({"one_action": "琳把清洁车卡住旧门槛再推进去"}))
        shots = good_shots()
        shots[0]["one_action"] = "春安扔钥匙并且转身走"
        data = table(shots)
        data["status"] = "draft"
        errors, _ = self.check(data)
        self.assertTrue(any("two verbs" in e for e in errors), errors)
        data["locked_picture"] = True
        errors, warnings = self.check(data)
        self.assertFalse(any("two verbs" in e for e in errors), errors)
        self.assertTrue(any("two verbs" in w for w in warnings), warnings)

    def test_long_take_without_reason_and_spm(self) -> None:
        shots = good_shots()
        shots[0]["duration_sec"] = 12
        shots[0]["shot_job"] = "建立旧河道与石槽"
        data = table(shots)
        data["status"] = "draft"
        errors, _ = self.check(data)
        self.assertTrue(any("信息在连续时间里" in e and "SH001" in e for e in errors), errors)
        shots[0]["shot_job"] = "信息在连续时间里：脚印要扫够才读得清"
        data = table(shots)
        data["status"] = "draft"
        errors, _ = self.check(data)
        self.assertFalse(any("信息在连续时间里" in e and "SH001" in e for e in errors), errors)

        dense = []
        for i in range(10):
            dense.append(
                shot(
                    shot_id=f"SH{i+1:03d}",
                    scene_id="EP01_SC01",
                    coverage_type="single" if i % 2 else "master",
                    scale="medium" if i % 2 else "wide",
                    left="速卡" if i % 2 else "河",
                    right="河" if i % 2 else "速卡",
                    one_action=f"速卡看水第{i}拍",
                    duration_sec=8,
                    in_from="x",
                    out_to="y",
                    beat="建置",
                    shot_job="铺",
                    dialogue_ref=[],
                    dialogue_delivery="none",
                )
            )
        dense[1]["dialogue_ref"] = [{"character": "速卡", "line": "水往哪走，河床都替你记着。"}]
        dense[1]["dialogue_delivery"] = "post"
        writer = {"scenes": [WRITER["scenes"][0]]}
        slow = sanitize_shot_table(
            {
                "schema": SCHEMA,
                "whose_pov": "速卡",
                "left_right_lock": {"EP01_SC01": "槽左人左河右"},
                "continuity_bible": {
                    "eyeline": "看水",
                    "wardrobe": "勘测服",
                    "day_night": {"EP01_SC01": "storm-day"},
                    "props": [],
                    "evidence": [],
                },
                "visible_change_without_dialogue": "pass",
                "status": "draft",
                "shots": dense,
            },
            writer=writer,
        )
        errors, warnings = validate_shot_table(slow, writer=writer, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("SPM" in e for e in errors), errors)
        self.assertTrue(any("consecutive long takes" in w for w in warnings), warnings)
        slow["locked_picture"] = True
        errors, warnings = validate_shot_table(slow, writer=writer, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertFalse(any("SPM" in e for e in errors), errors)
        self.assertTrue(any("SPM" in w for w in warnings), warnings)

    def test_picture_lock_and_ready_tables_stay_warning(self) -> None:
        data = table(good_shots())
        data["status"] = "ready"
        self.assertEqual(pace_enforcement(data), "warning")
        data["status"] = "candidate"
        self.assertEqual(pace_enforcement(data), "error")
        data["status"] = "draft"
        data["locked_picture"] = True
        self.assertTrue(picture_is_locked(data))
        self.assertEqual(pace_enforcement(data), "warning")
        metrics = pace_metrics(good_shots())
        self.assertEqual(metrics["shots"], 4)
        self.assertEqual(metrics["total_sec"], 27)

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
        data["shots"][3]["state_changes"] = []
        errors, _ = validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("sokha.binding changes none→wrists_behind" in e for e in errors), errors)
        shots = self._stateful_shots()
        shots[2]["state_changes"] = ["sokha.costume"]
        data = table(shots, continuity_bible=self._stateful_bible())
        data["shots"][2]["state_changes"] = ["sokha.costume"]
        errors, _ = validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("sokha.carrying changes" in e for e in errors), errors)

    def test_sanitize_fills_omitted_state_change_tags(self) -> None:
        shots = self._stateful_shots()
        shots[2]["state_changes"] = {"sokha.costume": True}
        shots[3]["state_changes"] = []
        cleaned = table(shots, continuity_bible=self._stateful_bible())
        self.assertIn("sokha.costume", cleaned["shots"][2]["state_changes"])
        self.assertIn("sokha.carrying", cleaned["shots"][2]["state_changes"])
        self.assertEqual(cleaned["shots"][2]["state"]["characters"]["sokha"]["carrying"], [])
        self.assertIn("sokha.binding", cleaned["shots"][3]["state_changes"])
        self.assertIn("sokha.bound_with", cleaned["shots"][3]["state_changes"])
        self.assertNotIn("sokha.costume", cleaned["shots"][3]["state_changes"])
        errors, _ = validate_shot_table(cleaned, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertEqual(errors, [], errors)
        shots = self._stateful_shots()
        shots[1]["state"]["characters"]["sokha"]["costume"] = ""
        shots[1]["state_changes"] = ["sokha.binding"]
        cleaned = table(shots, continuity_bible=self._stateful_bible())
        self.assertEqual(cleaned["shots"][1]["state"]["characters"]["sokha"]["costume"], "")
        self.assertNotIn("sokha.costume", cleaned["shots"][1]["state_changes"])
        self.assertIn("sokha.binding", cleaned["shots"][1]["state_changes"])

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

    def test_otc_target_behind_and_unmotivated_facing_flip(self) -> None:
        from director.shot_table import compile_specs_from_shot_table, orientation_errors

        front = shot(
            shot_id="SH010",
            coverage_type="close",
            scale="close",
            lens="85mm",
            left="琳",
            right="柜门缝",
            eyeline="盯工牌",
            body_facing="朝镜头",
            one_action="琳低头看工牌，尚未转身",
            in_from="字面已清",
            out_to="她仍面朝镜头低头看牌",
        )
        otc_behind = shot(
            shot_id="SH011",
            coverage_type="otc",
            scale="otc",
            lens="50mm",
            left="琳的左肩与发网后脑",
            right="柜缝里的波帕胸口",
            eyeline="仍盯工牌，没有去看身后",
            body_facing="背对镜头",
            one_action="机位过肩，波帕在她身后偏画右柜缝里透胸",
            in_from="她还盯工牌",
            out_to="仍见透胸，她仍未转身",
            state={"note": "波帕在她身后偏画右"},
        )
        dirty = dict(otc_behind)
        dirty.update({
            "coverage_type": "single",
            "scale": "medium",
            "left": "琳的左肩与颊侧",
            "right": "柜缝暖金",
            "body_facing": "四分之三",
            "camera_side": "front-left",
            "one_action": "机位停在她身前偏左，柜缝里灯管从胸口透出；她仍低头看牌",
            "state": {"note": "机位在琳身前偏左，不是过肩。波帕只在景深里给胸口透光。"},
        })
        errors, _ = validate_shot_table(table([front, otc_behind]), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertTrue(any("cannot show a target behind" in e for e in errors), errors)
        self.assertTrue(any("facing flips" in e or "背对镜头/后脑" in e for e in errors), errors)
        ok, _ = validate_shot_table(table([front, dirty]), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertFalse(any("cannot show a target behind" in e or "facing flips" in e for e in ok), ok)
        turned = dict(otc_behind)
        turned.update({
            "coverage_type": "single",
            "scale": "medium",
            "left": "琳",
            "one_action": "琳转身回头看柜缝",
            "in_from": "她转身",
            "body_facing": "背对镜头",
            "state": {"note": ""},
        })
        motivated, _ = validate_shot_table(table([front, turned]), writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)
        self.assertFalse(any("facing flips" in e for e in motivated), motivated)
        spec = compile_specs_from_shot_table(table([front]))["shot_specs"][0]
        self.assertEqual(spec["body_facing"], "朝镜头")
        self.assertEqual(spec.get("camera_side"), "")
        self.assertEqual(orientation_errors([{"shot_id": "SH001", "body_facing": "toward_camera"}]), [
            "SH001 body_facing must be one of ['朝镜头', '四分之三', '侧脸', '背对镜头', '无人']"
        ])

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
        first = compile_keyframe_prompt_zh({}, wide)
        self.assertIn("连戏必须照做：反剪麻绳仍在。", first)
        self.assertIn("画动作尚未发生的那一格", first)
        self.assertNotIn("画面：暹罗前队踏上浅滩人仰马翻", first)
        self.assertIn("连戏不变：反剪麻绳仍在。", compile_seedance_motion_from_spec({}, wide))
        cut_motion = compile_seedance_motion_from_spec(
            {"in_from": "她还盯工牌", "out_to": "立刻切她的怕", "action_now": "从肩后看见透光", "duration_sec": 4},
            {"internal_cuts": [{"at_sec": 3, "scale": "full", "one_action": "波帕已全身盖脚"}]},
        )
        self.assertIn("从起幅开始：她还盯工牌。", cut_motion)
        self.assertNotIn("立刻切", cut_motion)
        self.assertNotIn("片内切", cut_motion)
        self.assertNotIn("片内切到", cut_motion)
        self.assertNotIn("切到", cut_motion)
        self.assertNotIn("落幅停在：立刻切", cut_motion)
        opted = compile_seedance_motion_from_spec(
            {"action_now": "波帕站着", "duration_sec": 8, "internal_cuts": [{"at_sec": 3, "scale": "full", "one_action": "全身盖脚"}]},
            {},
            {"max_internal_cuts": 2, "multi_setup_in_clip": True},
        )
        self.assertIn("3秒时片内切到全身：全身盖脚。", opted)
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
        self.assertFalse(brief["one_shot_may_cut_inside"])
        self.assertEqual(brief["max_internal_cuts"], 0)
        self.assertIn("on_camera", brief["dialogue_delivery_options"])
        self.assertEqual(profile_brief(get_profile("minimax_h3"))["dialogue_delivery_options"], ["post"])
        self.assertTrue(get_profile("seedance_2_5")["verified"])
        self.assertEqual(get_profile("doubao-seedance-2-5-260628")["id"], "seedance_2_5")
        self.assertEqual(profile_brief(get_profile("seedance_2_5"))["shot_seconds"], {"min": 4, "max": 30})

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
        self.assertEqual(by_id["SH021"]["gen_mode"], "video_extend")
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
