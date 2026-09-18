#!/usr/bin/env python3
"""Director's-statement layer: scene cards, visual grammar, film-grade checks, candidates + critic,
frame descriptions, animatic plan, camera-plot geometry, model notes, and the mocked design run."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_shot_table import LOOK, SETS, WRITER, good_shots, shot, table  # noqa: E402

from director.design_critic import (  # noqa: E402
    RUBRIC_KEYS,
    critic_errors,
    deterministic_pick,
    normalize_verdict,
    render_candidates_md,
    styles_for,
)
from director.direction import (  # noqa: E402
    candidate_metrics,
    film_grade_checks,
    grammar_violations,
    light_checks,
    neighbor_checks,
    render_scene_cards_md,
    rhythm_checks,
    validate_scene_cards,
    validate_visual_grammar,
)
from director.frame_desc import (  # noqa: E402
    SCHEMA as FRAME_DESC_SCHEMA,
    description_sentence,
    index_by_shot,
    validate_frame_descriptions,
)
from director.shot_table import validate_shot_table  # noqa: E402
from director.video_profiles import get_profile, profile_brief  # noqa: E402

SCENE_IDS = ["EP01_SC01", "EP01_SC02"]


def card(scene_id: str = "EP01_SC01", **over) -> dict:
    base = {
        "scene_id": scene_id,
        "dramatic_question": "她认不认得这条河？",
        "turn": {"at": "水往哪走，河床都替你记着。", "what_flips": "information"},
        "emotion_curve": {"start": 2, "peak": 6, "end": 4, "peak_at": "手指伸进凹痕"},
        "the_shot": {"moment": "手指伸进凹痕", "scale": "medium", "why": "第一次触到旧河"},
        "reveal_order": ["先河道全貌", "再石槽凹痕", "再她的手"],
        "pov": "速卡",
        "distance_strategy": "由远到近，越认得越近",
        "light_motivation": "暴雨天光，顶侧",
        "color_shift": "",
        "silence_test": "蹲下、伸手、低头，不用台词也知道她认出了什么",
        "case_cards": ["reveal"],
    }
    base.update(over)
    return base


def cards() -> list[dict]:
    return [
        card(),
        card(
            "EP01_SC02",
            dramatic_question="她是不是细作？",
            turn={"at": "什么人？", "what_flips": "power"},
            emotion_curve={"start": 4, "peak": 8, "end": 7, "peak_at": "云朗按刀俯视"},
            the_shot={"moment": "云朗按刀俯视速卡贴地抬头", "scale": "otc", "why": "权力关系在这一眼"},
            reveal_order=["先空手与断槽", "再云朗的刀", "再她抬头"],
            light_motivation="黄昏低侧光",
            silence_test="空手、断槽、被按倒，静音仍成立",
            case_cards=["standoff"],
        ),
    ]


def grammar(**over) -> dict:
    base = {
        "motifs": [
            {"id": "yunlong_eye", "subject": "云朗", "rule": "第一集平视，他还没在上面", "when": "always", "angle": "eye"},
        ],
        "scale_rhythm": "每场远→中→紧，高潮后回中景",
        "light_motivation": "天光与火把",
        "color_arc": "湿冷到暖橙",
        "ending_hook": {"scale": ["otc", "close"], "note": "最后一眼停在关系上"},
    }
    base.update(over)
    return base


def film_table(shots: list[dict], **over) -> dict:
    extra = {"scene_cards": cards(), "visual_grammar": grammar()}
    extra.update(over)
    return table(shots, **extra)


class SceneCards(unittest.TestCase):
    def test_good_cards_pass(self) -> None:
        self.assertEqual(validate_scene_cards(cards(), SCENE_IDS), [])
        self.assertEqual(validate_visual_grammar(grammar()), [])

    def test_missing_turn_at_peak_below_start_bad_scale(self) -> None:
        bad = cards()
        bad[0]["turn"] = {"at": "", "what_flips": "power"}
        bad[0]["emotion_curve"] = {"start": 7, "peak": 3, "end": 2, "peak_at": "x"}
        bad[1]["the_shot"]["scale"] = "extreme-close"
        errors = validate_scene_cards(bad, SCENE_IDS)
        self.assertTrue(any("turn.at must quote" in e for e in errors), errors)
        self.assertTrue(any("emotion peak below start" in e for e in errors), errors)
        self.assertTrue(any("the_shot.scale must be one of" in e for e in errors), errors)
        errors = validate_scene_cards(cards()[:1], SCENE_IDS)
        self.assertTrue(any("scene card missing for EP01_SC02" in e for e in errors), errors)
        self.assertEqual(validate_scene_cards([], SCENE_IDS), ["scene_cards empty"])

    def test_grammar_needs_checkable_constraint(self) -> None:
        errors = validate_visual_grammar({"motifs": [{"id": "m", "subject": "云朗", "rule": "x", "when": "sometimes"}]})
        self.assertTrue(any("when must be one of" in e for e in errors), errors)
        self.assertTrue(any("no checkable constraint" in e for e in errors), errors)

    def test_render_cards_md(self) -> None:
        md = render_scene_cards_md(cards(), grammar(), title="第 01 集")
        self.assertIn("## EP01_SC02", md)
        self.assertIn("那一颗**：云朗按刀俯视速卡贴地抬头（otc）", md)
        self.assertIn("| yunlong_eye | 云朗 | always | eye |", md)


class Grammar(unittest.TestCase):
    def test_first_shot_in_scene_scale_not(self) -> None:
        g = grammar(motifs=[{"id": "sokha_local", "subject": "速卡", "rule": "先局部再全身", "when": "first_shot_in_scene", "scale_not": ["wide", "full"]}])
        errors, warnings = grammar_violations(table(good_shots()), g, WRITER)
        self.assertTrue(any(e.startswith("SH001 breaks motif sokha_local") for e in errors), errors)
        self.assertTrue(any(e.startswith("SH003 breaks motif sokha_local") for e in errors), errors)
        self.assertFalse(any(e.startswith("SH002") for e in errors + warnings), errors + warnings)

    def test_always_angle_and_until_scene_scope(self) -> None:
        g = grammar(motifs=[{"id": "yunlong_low", "subject": "云朗", "rule": "他在上面", "when": "always", "angle": "low"}])
        _, warnings = grammar_violations(table(good_shots()), g, WRITER)
        self.assertTrue(any("SH004 breaks motif yunlong_low" in e and "low angle" in e for e in warnings), warnings)
        scoped = grammar(motifs=[{"id": "sokha_local", "subject": "速卡", "rule": "x", "when": "first_shot_in_scene", "scale_not": ["wide", "full"], "until_scene": "EP01_SC01"}])
        errors, _ = grammar_violations(table(good_shots()), scoped, WRITER)
        self.assertTrue(any(e.startswith("SH001") for e in errors), errors)
        self.assertFalse(any(e.startswith("SH003") for e in errors), errors)
        later = grammar(motifs=[{"id": "sokha_local", "subject": "速卡", "rule": "x", "when": "first_shot_in_scene", "scale_not": ["wide", "full"], "from_scene": "EP01_SC02"}])
        errors, _ = grammar_violations(table(good_shots()), later, WRITER)
        self.assertFalse(any(e.startswith("SH001") for e in errors), errors)
        self.assertTrue(any(e.startswith("SH003") for e in errors), errors)

    def test_ending_hook_warning(self) -> None:
        _, warnings = grammar_violations(table(good_shots()), grammar(ending_hook={"scale": ["close"], "note": ""}), WRITER)
        self.assertTrue(any("ending hook SH004 is otc; grammar asks close" in w for w in warnings), warnings)
        _, warnings = grammar_violations(table(good_shots()), grammar(), WRITER)
        self.assertFalse(any("ending hook" in w for w in warnings), warnings)


class Rhythm(unittest.TestCase):
    def _three_medium(self) -> list[dict]:
        shots = good_shots()
        shots[0].update(scale="medium", coverage_type="master")
        shots[1].update(scale="medium", coverage_type="single")
        shots.insert(2, shot(shot_id="SH002b", coverage_type="reaction", scale="medium", lens="50mm", beat="识水", shot_job="看水", one_action="速卡抬头看水", duration_sec=4, in_from="x", out_to="y"))
        return shots

    def test_three_same_scale_warns(self) -> None:
        _, warnings = rhythm_checks({"shots": self._three_medium()})
        self.assertTrue(any("three shots in a row at medium" in w for w in warnings), warnings)
        _, warnings = rhythm_checks({"shots": good_shots()})
        self.assertFalse(any("three shots" in w for w in warnings), warnings)

    def test_the_shot_landed_and_tightest(self) -> None:
        errors, _ = rhythm_checks({"shots": good_shots()}, cards())
        self.assertEqual(errors, [])
        missing = cards()
        missing[0]["the_shot"]["scale"] = "close"
        errors, _ = rhythm_checks({"shots": good_shots()}, missing)
        self.assertTrue(any("scene EP01_SC01: scene card says the shot is close" in e and "no shot at that scale" in e for e in errors), errors)
        loose = cards()
        loose[1]["the_shot"]["scale"] = "full"
        _, warnings = rhythm_checks({"shots": good_shots()}, loose)
        self.assertTrue(any("scene EP01_SC02: the shot (full) is not the tightest" in w for w in warnings), warnings)

    def test_emotion_peak_logic(self) -> None:
        shots = good_shots()
        shots[2]["emotion_level"] = 9  # full shot carries the peak while an otc exists
        shots[3]["emotion_level"] = 5
        _, warnings = rhythm_checks({"shots": shots})
        self.assertTrue(any("emotional peak SH003 (level 9) sits at full, tighter shots exist" in w for w in warnings), warnings)
        shots = good_shots()
        shots[0]["emotion_level"] = 2
        shots[1]["emotion_level"] = 6
        shots.insert(2, shot(shot_id="SH002b", coverage_type="close", scale="close", lens="85mm", beat="识水", shot_job="眼", one_action="速卡眼里有水", duration_sec=4, in_from="x", out_to="y", emotion_level=3))
        _, warnings = rhythm_checks({"shots": shots})
        self.assertTrue(any("after the peak SH002 nothing returns to medium or wider" in w for w in warnings), warnings)
        shots = good_shots()
        shots[0]["emotion_level"] = 12
        errors, _ = rhythm_checks({"shots": shots})
        self.assertTrue(any("emotion_level must be 0–10" in e for e in errors), errors)

    def test_the_shot_two_subjects(self) -> None:
        shots = good_shots()
        scene_cards = cards()
        scene_cards[0]["the_shot"] = {"moment": "琳与波帕同框", "scale": "medium", "why": "金手指立住"}
        shots[1]["state"] = {
            "characters": {
                "rin": {"in_frame": True, "binding": "none"},
                "bopha": {"in_frame": False, "binding": "none"},
            },
            "note": "只有琳",
        }
        errors, _ = rhythm_checks({"shots": shots}, scene_cards)
        self.assertTrue(any("同框" in e and "SH002" in e for e in errors), errors)
        shots[1]["state"]["characters"]["bopha"]["in_frame"] = True
        errors, _ = rhythm_checks({"shots": shots}, scene_cards)
        self.assertFalse(any("同框" in e for e in errors), errors)


class Light(unittest.TestCase):
    def _scene2(self, first: str, second: str, coverage: str = "otc") -> dict:
        shots = good_shots()
        shots[2]["light"]["key_dir"] = first
        shots[3]["light"]["key_dir"] = second
        shots[3]["coverage_type"] = coverage
        return table(shots)

    def test_left_to_right_jump_is_error_unless_reverse(self) -> None:
        errors, warnings = light_checks(self._scene2("left", "right", coverage="single"))
        self.assertTrue(any("SH004 key light jumps from left (SH003) to right" in e for e in errors), errors)
        errors, warnings = light_checks(self._scene2("left", "right", coverage="otc"))
        self.assertEqual(errors, [])
        self.assertFalse(any("SH004" in w and "key light" in w for w in warnings), warnings)
        errors, warnings = light_checks(self._scene2("画左", "reverse-side", coverage="reverse"))
        self.assertEqual(errors, [])

    def test_mirror_on_non_reverse_warns(self) -> None:
        errors, warnings = light_checks(self._scene2("front-left", "front-right", coverage="single"))
        self.assertEqual(errors, [])
        self.assertTrue(any("SH004 key light mirrors SH003 (front-left→front-right) but this is not a reverse" in w for w in warnings), warnings)

    def test_day_night_contradiction(self) -> None:
        shots = good_shots()
        shots[3]["light"]["day_night"] = "night"
        errors, _ = light_checks(table(shots))
        self.assertTrue(any("SH004 light.day_night night contradicts continuity_bible dusk" in e for e in errors), errors)
        errors, _ = light_checks(table(good_shots()))
        self.assertEqual(errors, [])


class Neighbours(unittest.TestCase):
    def test_more_than_two_changes_warns(self) -> None:
        _, warnings = neighbor_checks({"shots": good_shots()})
        self.assertEqual(warnings, [])
        shots = good_shots()
        shots[3].update(angle="low", move_type="push", move_reason="逼近")
        _, warnings = neighbor_checks({"shots": shots})
        self.assertTrue(any(w.startswith("SH004 changes 4 things at once") for w in warnings), warnings)
        shots = good_shots()
        shots[3].update(angle="low", move_type="push", move_reason="逼近", coverage_type="insert")
        _, warnings = neighbor_checks({"shots": shots})
        self.assertEqual(warnings, [])


class FilmGradeGate(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = get_profile("seedance_2_0")

    def check(self, data: dict):
        return validate_shot_table(data, writer=WRITER, sets=SETS, profile=self.profile, look_text=LOOK)

    def _three_medium_table(self, **over) -> dict:
        shots = good_shots()
        shots[0].update(scale="medium", coverage_type="master")
        shots[1].update(scale="medium", coverage_type="single")
        shots.insert(2, shot(shot_id="SH002b", coverage_type="reaction", scale="medium", lens="50mm", beat="识水", shot_job="看水", one_action="速卡抬头看水", duration_sec=4, in_from="x", out_to="y"))
        return table(shots, **over)

    def test_not_run_without_cards_unless_asked(self) -> None:
        _, warnings = self.check(self._three_medium_table())
        self.assertFalse(any("three shots in a row" in w for w in warnings), warnings)
        _, warnings = self.check(self._three_medium_table(film_grade=True))
        self.assertTrue(any("three shots in a row" in w for w in warnings), warnings)

    def test_runs_with_cards_and_passes_good_table(self) -> None:
        errors, warnings = self.check(film_table(good_shots()))
        self.assertEqual(errors, [], errors)
        errors, warnings = film_grade_checks(film_table(good_shots()), WRITER)
        self.assertEqual(errors, [])
        bad = film_table(good_shots(), scene_cards=[cards()[0]])
        _, warnings = self.check(bad)
        self.assertTrue(any("scene_cards: scene card missing for EP01_SC02" in w for w in warnings), warnings)
        broken = film_table(good_shots())
        broken["scene_cards"][0]["the_shot"]["scale"] = "close"
        errors, _ = self.check(broken)
        self.assertTrue(any("no shot at that scale" in e for e in errors), errors)

    def test_candidate_metrics(self) -> None:
        metrics = candidate_metrics(good_shots()[2:], cards()[1], ["w"])
        self.assertEqual(metrics["shots"], 2)
        self.assertEqual(metrics["total_sec"], 16)
        self.assertEqual(metrics["scale_curve"], "F O")
        self.assertEqual(metrics["tightest"], "O")
        self.assertTrue(metrics["the_shot_landed"])
        self.assertTrue(metrics["the_shot_tightest"])
        self.assertEqual(metrics["warnings"], 1)


class Critic(unittest.TestCase):
    def _candidates(self) -> list[dict]:
        a = {"style": "coverage", "label": "覆盖派", "shots": good_shots()[2:], "warnings": ["x", "y"]}
        b = {"style": "pov", "label": "主观派", "shots": good_shots()[2:], "warnings": []}
        return [a, b]

    def test_critic_errors_ranges(self) -> None:
        self.assertEqual(critic_errors("nope", 2), ["critic must return an object"])
        verdict = {"scores": [{"candidate": 0, "dims": {k: 11 for k in RUBRIC_KEYS}, "notes": "n"}, {"candidate": 1, "dims": {k: 5 for k in RUBRIC_KEYS}, "notes": "n"}], "pick": 1, "why": "w"}
        errors = critic_errors(verdict, 2)
        self.assertTrue(any("dims.reveal_order must be 0–10" in e for e in errors), errors)
        verdict["scores"][0]["dims"] = {k: 5 for k in RUBRIC_KEYS if k != "silence"}
        errors = critic_errors(verdict, 2)
        self.assertTrue(any("missing dims.silence" in e for e in errors), errors)
        verdict["scores"][0]["dims"] = {k: 5 for k in RUBRIC_KEYS}
        verdict["pick"] = 4
        self.assertTrue(any("pick out of range" in e for e in critic_errors(verdict, 2)))
        verdict["pick"] = 1
        self.assertEqual(critic_errors(verdict, 2), [])
        self.assertTrue(critic_errors({"scores": [verdict["scores"][0]], "pick": 0, "why": "w"}, 2))
        normalized = normalize_verdict(verdict, 2)
        self.assertEqual(normalized["source"], "critic")
        self.assertEqual(normalized["scores"][1]["total"], 35.0)

    def test_deterministic_pick_prefers_fewer_warnings(self) -> None:
        self.assertEqual(deterministic_pick(self._candidates(), cards()[1]), 1)
        self.assertEqual(deterministic_pick([], None), 0)
        self.assertEqual(len(styles_for(4)), 4)
        self.assertEqual(styles_for(1)[0]["id"], "coverage")

    def test_render_candidates_md_marks_pick(self) -> None:
        rows = [{"scene_id": "EP01_SC02", "scene_card": cards()[1], "candidates": self._candidates(), "verdict": {"pick": 1, "why": "少警告", "source": "critic", "scores": []}, "pick": 1}]
        md = render_candidates_md(rows, title="t")
        self.assertIn("★ 2 主观派", md)
        self.assertIn("### 第 2 版 · 主观派 ★", md)
        self.assertIn("| 警告数 | 2 | 0 |", md)
        self.assertIn("评审选第 2 版", md)


def frame_item(shot_id: str, **over) -> dict:
    base = {
        "shot_id": shot_id,
        "layers": {"foreground": "湿石槽边缘", "midground": "速卡蹲着", "background": "雨里的河道虚成灰"},
        "light": {"key": "顶侧天光从画右上", "fill": "水面反光", "practical": "", "quality": "软，冷"},
        "subject": {"facing": "四分之三朝画右", "hands": "右手指伸进凹痕", "holding": "空手", "micro_expression": "垂眼"},
        "composition": {"weight": "左下三分", "negative_space": "右上留给河", "headroom": "紧"},
        "height_meaning": "略俯，她低于河",
        "forbidden": ["汉字", "第二个光源"],
        "one_paragraph": "前景是湿的石槽边缘，中景速卡蹲着，右手指伸进凹痕，背景河道在雨里虚成灰。顶侧天光从画右上来，水面反光补脸。重心左下，右上留给河。",
    }
    base.update(over)
    return base


class FrameDescriptions(unittest.TestCase):
    def test_validate_words_missing_and_length(self) -> None:
        ids = ["SH001", "SH002"]
        data = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH001"), frame_item("SH002")]}
        self.assertEqual(validate_frame_descriptions(data, ids), [])
        bad = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH001", one_paragraph="电影感拉满的一张"), frame_item("SH003")]}
        errors = validate_frame_descriptions(bad, ids)
        self.assertTrue(any("SH001 uses empty adjective 「电影感」" in e for e in errors), errors)
        self.assertTrue(any("SH003 is not a shot in the table" in e for e in errors), errors)
        self.assertTrue(any("SH002 has no frame description" in e for e in errors), errors)
        real = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH001", subject={"facing": "真人正面", "hands": "x", "holding": "", "micro_expression": ""}), frame_item("SH002")]}
        self.assertTrue(any("真人" in e for e in validate_frame_descriptions(real, ids)))
        long = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH001", one_paragraph="雨" * 230), frame_item("SH002")]}
        self.assertTrue(any("SH001 one_paragraph is 230 chars" in e for e in validate_frame_descriptions(long, ids)))
        self.assertIn("schema must be frame-desc-v1", validate_frame_descriptions({"schema": "x", "items": [frame_item("SH001")]}, ["SH001"]))

    def test_otc_facing_cannot_be_back(self) -> None:
        shots = [
            {"shot_id": "SH010", "scene_id": "EP01_SC02", "coverage_type": "close", "one_action": "低头看牌", "in_from": "清", "out_to": "面朝镜头"},
            {"shot_id": "SH011", "scene_id": "EP01_SC02", "coverage_type": "otc", "one_action": "过肩", "in_from": "看牌", "out_to": "未转身"},
        ]
        data = {
            "schema": FRAME_DESC_SCHEMA,
            "items": [
                frame_item("SH010", subject={"facing": "朝镜头", "hands": "持牌", "holding": "工牌", "micro_expression": "垂眼"}),
                frame_item("SH011", subject={"facing": "琳背对镜头未转正脸", "hands": "持牌", "holding": "工牌", "micro_expression": "不见脸"}),
            ],
        }
        errors = validate_frame_descriptions(data, ["SH010", "SH011"], shots=shots)
        self.assertTrue(any("otc frame_desc facing" in e for e in errors), errors)
        self.assertTrue(any("facing flips" in e for e in errors), errors)

    def test_sentence_and_keyframe_prompt(self) -> None:
        from director.prompts import compile_keyframe_prompt_zh

        sentence = description_sentence(frame_item("SH001"))
        self.assertIn("前景湿石槽边缘", sentence)
        self.assertIn("主光顶侧天光从画右上", sentence)
        self.assertIn("手右手指伸进凹痕", sentence)
        self.assertIn("画面里不得出现：汉字、第二个光源", sentence)
        prompt = compile_keyframe_prompt_zh({}, good_shots()[1], frame_desc=frame_item("SH002"))
        self.assertIn("画面描述：", prompt)
        self.assertNotIn("画面描述：", compile_keyframe_prompt_zh({}, good_shots()[1]))
        self.assertEqual(list(index_by_shot({"items": [frame_item("SH001")]})), ["SH001"])

    def test_pick_up_first_still_rejects_result_accepts_pre_state(self) -> None:
        shot = {
            "shot_id": "SH006",
            "one_action": "琳弯腰捡起脚边旧钥匙，钥匙离地入手",
            "in_from": "钥匙仍在脚边地上",
            "out_to": "她拿着旧钥匙走向尽头",
            "coverage_type": "follow",
            "scale": "wide",
            "move_type": "track",
        }
        bad = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH006", one_paragraph="钥匙已在右手")]}
        errors = validate_frame_descriptions(bad, ["SH006"], shots=[shot])
        self.assertTrue(any("first still is mid/result" in e and "SH006" in e for e in errors), errors)
        good = {
            "schema": FRAME_DESC_SCHEMA,
            "items": [frame_item("SH006", one_paragraph="钥匙在脚边地上，人尚未弯腰", last_paragraph="她拿着钥匙走向尽头")],
        }
        self.assertEqual(validate_frame_descriptions(good, ["SH006"], shots=[shot]), [])

    def test_throw_first_still_already_on_ground_is_error(self) -> None:
        shot = {
            "shot_id": "SH004",
            "one_action": "春安把旧钥匙扔到琳脚边",
            "in_from": "旧钥匙还在她手里，尚未出手",
            "coverage_type": "single",
            "scale": "medium",
            "move_type": "static",
        }
        bad = {"schema": FRAME_DESC_SCHEMA, "items": [frame_item("SH004", one_paragraph="钥匙在地上")]}
        errors = validate_frame_descriptions(bad, ["SH004"], shots=[shot])
        self.assertTrue(any("first still is mid/result" in e for e in errors), errors)

    def test_first_last_missing_still_end_is_error(self) -> None:
        shot = {
            "shot_id": "SH006",
            "one_action": "琳弯腰捡起脚边旧钥匙",
            "in_from": "钥匙仍在脚边地上",
            "out_to": "她拿着旧钥匙走向尽头",
            "keyframe_plan": "first_last",
            "coverage_type": "follow",
            "scale": "wide",
            "move_type": "track",
        }
        data = {
            "schema": FRAME_DESC_SCHEMA,
            "items": [frame_item("SH006", one_paragraph="钥匙在脚边地上，人尚未弯腰")],
        }
        errors = validate_frame_descriptions(data, ["SH006"], shots=[shot])
        self.assertTrue(any("first_last missing still_end / last_paragraph" in e for e in errors), errors)

    def test_first_frame_prompt_does_not_draw_the_result(self) -> None:
        from director.prompts import compile_keyframe_prompt_zh

        shot = {
            "shot_id": "SH006",
            "one_action": "琳弯腰捡起脚边旧钥匙，钥匙离地入手",
            "in_from": "钥匙仍在脚边地上",
            "scale": "wide",
            "move_type": "track",
        }
        desc = frame_item(
            "SH006",
            one_paragraph="钥匙在脚边地上，人尚未弯腰",
            still_start={"pose": "尚未弯腰", "holding": "空手", "prop_state": "钥匙在脚边地上", "one_paragraph": "钥匙在脚边地上，人尚未弯腰"},
            subject={"facing": "四分之三", "hands": "双手仍在车把上", "holding": "空手", "micro_expression": "垂眼"},
            layers={"foreground": "脚边地上的旧钥匙", "midground": "琳尚未弯腰", "background": "夹道尽头"},
        )
        prompt = compile_keyframe_prompt_zh(
            {"in_from": shot["in_from"], "action_now": shot["one_action"], "shot_size": "wide"},
            shot,
            frame_desc=desc,
            slot="first",
        )
        self.assertIn("画动作尚未发生的那一格", prompt)
        self.assertTrue(any(token in prompt for token in ("禁止", "尚未", "不要画已", "不要画成已完成")), prompt)
        self.assertIn("本镜之后才会发生", prompt)
        head = prompt.split("本镜之后才会发生")[0]
        self.assertNotIn("已在手里", head)
        self.assertNotIn("离地入手", head)
        self.assertNotIn("画面：琳弯腰捡起", prompt)


class Knowledge(unittest.TestCase):
    def test_cases_for_matches_tags(self) -> None:
        from director.knowledge import case_cards, cases_for

        ids = {c["id"] for c in case_cards()}
        for needed in ("ghost-reveal", "frame-up-crowd", "pass-through", "serve-tea", "photo-gaze", "pen-down", "blackout", "ledger-hide", "farewell-touch", "standoff"):
            self.assertIn(needed, ids)
        hits = [c["id"] for c in cases_for("琳抹掉工牌上的灰。灯管从波帕胸口透过来。她地上没有影子。")]
        self.assertEqual(hits[0], "ghost-reveal")
        hits = [c["id"] for c in cases_for("七线门口围人。春安从清洁车底层拖出藏青色布，吊牌还在。离职书摊开，笔帽拧开。")]
        self.assertIn("frame-up-crowd", hits)
        self.assertEqual(cases_for(""), [])
        self.assertTrue(all(c["tags"] for c in case_cards()), [c["id"] for c in case_cards() if not c["tags"]])


# --- mocked design run ------------------------------------------------------------------


def _writer() -> dict:
    writer = copy.deepcopy(WRITER)
    writer["series_bible"] = {
        "logline": "水认得旧路",
        "characters": [{"id": "sokha", "name": "速卡"}, {"id": "yunlong", "name": "云朗"}],
        "relationships": [],
        "locations": [{"location_id": "modern-channel", "name": "现代旧河道遗址"}, {"location_id": "ancient-shoal", "name": "古河边浅滩"}],
        "core_conflict": "x",
        "adaptation_rules": "x",
    }
    writer["episode_outline"] = [{"episode_no": 1, "title": "水认得旧路"}]
    for index, scene in enumerate(writer["scenes"], start=1):
        scene.update({
            "episode_no": 1,
            "heading": f"EXT. 场 {index} - 日",
            "time_of_day": "day",
            "int_ext": "ext",
            "present_cast": ["sokha"] if index == 1 else ["sokha", "yunlong"],
            "scene_job": "认河" if index == 1 else "被按倒盘问",
            "whose_scene": "速卡",
            "start_state": "干",
            "end_state": "湿",
            "action": "速卡蹲下把手指伸进凹痕" if index == 1 else "云朗按刀俯视速卡",
        })
    return writer


def _strip_ids(shots: list[dict]) -> list[dict]:
    out = []
    for item in shots:
        row = dict(item)
        row.pop("shot_id", None)
        out.append(row)
    return out


def make_prod(tmp: str) -> Path:
    from director.pipeline import write_artifact

    prod = Path(tmp) / "p"
    (prod / "01-bible").mkdir(parents=True)
    (prod / "02-assets").mkdir()
    (prod / "03-storyboard").mkdir()
    (prod / "02-assets" / "LOOK.md").write_text(LOOK, encoding="utf-8")
    (prod / "03-storyboard" / "sets.json").write_text(json.dumps(SETS, ensure_ascii=False), encoding="utf-8")
    (prod / "01-bible" / "ep01.md").write_text("# 第 01 集\n\n速卡：水往哪走，河床都替你记着。\n云朗：什么人？\n速卡：我是高棉人，大湖边来的！我不是细作——\n", encoding="utf-8")
    write_artifact(prod, "writer.json", _writer())
    return prod


def fake_design_chat(calls: list[dict]):
    """Deterministic stand-in for the Grok call: routes on ctx['call']."""
    header = {
        "whose_pov": "速卡",
        "left_right_lock": {"EP01_SC01": "槽左人左河右", "EP01_SC02": "高棉左暹罗右"},
        "continuity_bible": {
            "eyeline": "看水",
            "wardrobe": "现代勘测服，SH003 起湿透",
            "day_night": {"EP01_SC01": "storm-day", "EP01_SC02": "dusk"},
            "props": [{"name": "测量杆", "first_scene": "EP01_SC01", "last_scene": "EP01_SC01"}],
            "evidence": [{"what": "空手+断槽", "scene_id": "EP01_SC02"}],
        },
        "scene_plan": [{"scene_id": sid, "target_shots": 2, "target_sec": 12, "beats": ["a", "b"]} for sid in SCENE_IDS],
    }

    def chat(system: str, ctx: dict, temperature: float = 0.3) -> dict:
        calls.append({"call": ctx.get("call"), "scene": (ctx.get("scene") or {}).get("scene_id"), "style": (ctx.get("candidate_style") or {}).get("id"), "temperature": temperature})
        call = ctx.get("call")
        if call == "analysis":
            return {"scene_cards": cards(), "visual_grammar": grammar()}
        if call == "header":
            return header
        if call == "scene":
            sid = ctx["scene"]["scene_id"]
            style = ctx["candidate_style"]["id"]
            shots = good_shots()[:2] if sid == "EP01_SC01" else good_shots()[2:]
            lens = {"coverage": None, "pov": "40mm", "long_take": "35mm"}.get(style)
            if lens:
                shots[-1]["lens"] = lens
            return {"shots": _strip_ids(shots)}
        if call == "critic":
            count = len(ctx["candidates"])
            return {
                "scores": [{"candidate": i, "dims": {k: (7 if i == 1 else 5) for k in RUBRIC_KEYS}, "notes": f"第 {i + 1} 版", "fixes": []} for i in range(count)],
                "pick": 1 if count > 1 else 0,
                "why": "主观派守住了揭示顺序",
                "merge": "",
            }
        if call == "frame_desc":
            return {"items": [frame_item(s["shot_id"]) for s in ctx["shots"]]}
        raise AssertionError(f"unexpected call {call}")

    return chat


class DesignRun(unittest.TestCase):
    def test_design_table_end_to_end_with_candidates_and_pick(self) -> None:
        from director.pipeline import read_artifact
        from director.station_agents import design_candidates, pick_candidate, run_design_table

        calls: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            prod = make_prod(tmp)
            with mock.patch("director.station_agents.text_configured", return_value=True), mock.patch(
                "director.station_agents._design_chat", side_effect=fake_design_chat(calls)
            ):
                result = run_design_table(prod, target_model="seedance_2_0", resume=False, candidates=3)
            self.assertTrue(result["ok"])
            self.assertEqual([c["call"] for c in calls].count("analysis"), 1)
            self.assertEqual([c["call"] for c in calls].count("header"), 1)
            self.assertEqual([c["call"] for c in calls].count("scene"), 6)
            self.assertEqual([c["call"] for c in calls].count("critic"), 2)
            self.assertEqual({c["style"] for c in calls if c["call"] == "scene"}, {"coverage", "pov", "long_take"})
            self.assertGreater(max(c["temperature"] for c in calls if c["call"] == "scene"), 0.3)

            written = read_artifact(prod, "shot_list.json")
            self.assertEqual(written["schema"], "shot-table-v2")
            self.assertEqual(len(written["scene_cards"]), 2)
            self.assertEqual(written["visual_grammar"]["motifs"][0]["id"], "yunlong_eye")
            self.assertEqual(written["candidate_picks"], {"EP01_SC01": 1, "EP01_SC02": 1})
            self.assertEqual([s["shot_id"] for s in written["shots"]], ["SH001", "SH002", "SH003", "SH004"])
            self.assertEqual(written["shots"][3]["lens"], "40mm")  # pov version picked
            self.assertEqual(written["scene_reports"][0]["critic"], "critic")

            candidates = design_candidates(prod)
            self.assertEqual(candidates["schema"], "design-candidates-v1")
            self.assertEqual([len(row["candidates"]) for row in candidates["scenes"]], [3, 3])
            self.assertEqual(candidates["scenes"][1]["verdict"]["pick"], 1)
            self.assertEqual(candidates["scenes"][1]["verdict"]["scores"][1]["total"], 49.0)

            self.assertTrue(read_artifact(prod, "scene_cards.json").get("scene_cards"))
            self.assertEqual(len(read_artifact(prod, "shot_specs.json")["shot_specs"]), 4)
            for rel in ("03-storyboard/scene-cards.draft.md", "03-storyboard/shot-list.draft.md", "03-storyboard/shot-candidates.draft.md"):
                self.assertTrue((prod / rel).exists(), rel)
            self.assertIn("★ 2 主观派", (prod / "03-storyboard" / "shot-candidates.draft.md").read_text(encoding="utf-8"))
            self.assertIn("EP01_SC01 选第 2 版", (prod / "03-storyboard" / "shot-list.draft.md").read_text(encoding="utf-8"))
            self.assertFalse((prod / ".pipeline" / "design.cache.json").exists())

            swapped = pick_candidate(prod, "EP01_SC02", 0)
            self.assertFalse(swapped["used_tokens"])
            table_now = read_artifact(prod, "shot_list.json")
            self.assertEqual(table_now["candidate_picks"], {"EP01_SC01": 1, "EP01_SC02": 0})
            self.assertEqual(table_now["shots"][3]["lens"], "50mm")
            self.assertEqual([s["shot_id"] for s in table_now["shots"]], ["SH001", "SH002", "SH003", "SH004"])
            self.assertEqual(design_candidates(prod)["scenes"][1]["verdict"]["source"], "human")
            with self.assertRaises(ValueError):
                pick_candidate(prod, "EP01_SC02", 7)
            with self.assertRaises(ValueError):
                pick_candidate(prod, "EP01_SC09", 0)

    def test_frame_descriptions_flow_into_packages(self) -> None:
        from director.pipeline import compile_packages_from_specs, read_artifact
        from director.station_agents import run_frame_descriptions, run_station_agent

        calls: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            prod = make_prod(tmp)
            with mock.patch("director.station_agents.text_configured", return_value=True), mock.patch(
                "director.station_agents._design_chat", side_effect=fake_design_chat(calls)
            ):
                run_station_agent(prod, "design", target_model="seedance_2_0", resume=False, candidates=1)
                result = run_frame_descriptions(prod)
            self.assertEqual(result["file"], "frame_descriptions.json")
            self.assertEqual([c["call"] for c in calls].count("frame_desc"), 2)
            data = read_artifact(prod, "frame_descriptions.json")
            self.assertEqual(data["schema"], FRAME_DESC_SCHEMA)
            self.assertEqual([i["shot_id"] for i in data["items"]], ["SH001", "SH002", "SH003", "SH004"])
            self.assertTrue((prod / "03-storyboard" / "frame-descriptions.draft.md").exists())
            self.assertIn("**画面描述**", (prod / "03-storyboard" / "shot-list.draft.md").read_text(encoding="utf-8"))
            packages = compile_packages_from_specs(prod, target_model="seedance_2_0")
            self.assertEqual(len(packages["packages"]), 4)
            for pkg in packages["packages"]:
                self.assertTrue(pkg["frame_description"].startswith("前景是湿的石槽边缘"))
                self.assertIn("画面描述：", pkg["image_prompt"])
            # pipeline snapshot lists the new artifacts
            from director.pipeline import snapshot_pipeline

            snap = snapshot_pipeline(prod)
            self.assertTrue(snap["artifacts"]["scene_cards"]["exists"])
            self.assertEqual(snap["artifacts"]["frame_descriptions"]["count"], 4)
            self.assertGreaterEqual([c["call"] for c in calls].count("critic"), 1)

    def test_critic_single_candidate_still_calls_model(self) -> None:
        from director.station_agents import _run_critic

        calls: list[dict] = []

        def chat(system: str, ctx: dict, temperature: float = 0.2) -> dict:
            calls.append(ctx)
            return {
                "scores": [{"candidate": 0, "dims": {k: 6 for k in RUBRIC_KEYS}, "notes": "连戏", "fixes": []}],
                "pick": 0,
                "why": "单版也过连戏",
                "merge": "",
            }

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            prod.mkdir()
            with mock.patch("director.station_agents._design_chat", side_effect=chat), mock.patch(
                "director.station_agents._system", return_value="sys"
            ):
                verdict = _run_critic(
                    prod,
                    sid="EP01_SC01",
                    scene={"scene_id": "EP01_SC01"},
                    card=card(),
                    grammar=grammar(),
                    candidates=[{"style": "coverage", "label": "覆盖派", "shots": good_shots()[:2], "warnings": []}],
                    profile=get_profile("seedance_2_0"),
                )
        self.assertEqual(len(calls), 1)
        self.assertEqual(verdict["source"], "critic")
        self.assertEqual(verdict["pick"], 0)

    def test_frame_desc_ctx_includes_facing_and_prev(self) -> None:
        from director.station_agents import frame_desc_shots_ctx

        rows = frame_desc_shots_ctx(
            [
                {"shot_id": "SH010", "body_facing": "朝镜头", "camera_side": "front", "scale": "close"},
                {"shot_id": "SH011", "body_facing": "四分之三", "camera_side": "front-left", "scale": "medium"},
            ]
        )
        self.assertEqual(rows[0]["body_facing"], "朝镜头")
        self.assertEqual(rows[0]["prev_shot_id"], "")
        self.assertEqual(rows[1]["prev_shot_id"], "SH010")
        self.assertEqual(rows[1]["prev_facing"], "朝镜头")
        self.assertEqual(rows[1]["camera_side"], "front-left")

    def test_analysis_station_alone_writes_cards(self) -> None:
        from director.pipeline import read_artifact
        from director.station_agents import run_station_agent

        calls: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            prod = make_prod(tmp)
            with mock.patch("director.station_agents.text_configured", return_value=True), mock.patch(
                "director.station_agents._design_chat", side_effect=fake_design_chat(calls)
            ):
                result = run_station_agent(prod, "analysis")
            self.assertEqual(result["file"], "scene_cards.json")
            self.assertEqual(len(read_artifact(prod, "scene_cards.json")["scene_cards"]), 2)
            self.assertTrue((prod / "03-storyboard" / "scene-cards.draft.md").exists())


class Animatic(unittest.TestCase):
    def test_plan_without_ffmpeg(self) -> None:
        from PIL import Image

        from director.animatic import animatic_output_path, plan_animatic
        from director.pipeline import write_artifact

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            (prod / "04-frames").mkdir(parents=True)
            write_artifact(prod, "shot_list.json", table(good_shots()))
            for name in ("SH001.jpg", "SH001-last.jpg", "SH002.jpg"):
                Image.new("RGB", (160, 90), (90, 60, 30)).save(prod / "04-frames" / name)
            plan = plan_animatic(prod, 1)
            self.assertEqual([p["shot_id"] for p in plan], ["SH001", "SH001", "SH002", "SH003", "SH004"])
            self.assertEqual([p["part"] for p in plan[:2]], ["first", "last"])
            self.assertEqual([p["seconds"] for p in plan], [2.5, 2.5, 6.0, 7.0, 9.0])
            self.assertEqual(round(sum(p["seconds"] for p in plan), 3), 27.0)
            self.assertEqual(plan[1]["image"], "04-frames/SH001-last.jpg")
            self.assertFalse(plan[2]["missing"])
            self.assertTrue(plan[3]["missing"])
            self.assertIsNone(plan[3]["image"])
            self.assertIn("缺首帧", plan[3]["label"])
            self.assertIn("SH002 · 6s · medium/single", plan[2]["label"])
            self.assertEqual(animatic_output_path(prod, 2), prod / "03-storyboard" / "animatic" / "ep02.animatic.mp4")
            for bad in ("05-shots/SH001.mp4", "06-export/ep01.mp4", "03-storyboard/animatic/../../06-export/x.mp4", "03-storyboard/x.mp4"):
                with self.assertRaises(PermissionError):
                    animatic_output_path(prod, 1, bad)

    def test_plan_falls_back_to_legacy_shots(self) -> None:
        from director.animatic import episode_frames_dir, plan_animatic

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            (prod / "03-storyboard").mkdir(parents=True)
            (prod / "03-storyboard" / "shots.json").write_text(json.dumps({"shots": [{"id": "SH001", "seconds": 3, "setup": "master", "action": "开门"}]}), encoding="utf-8")
            plan = plan_animatic(prod, 1)
            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0]["seconds"], 3.0)
            self.assertTrue(plan[0]["missing"])
            self.assertEqual(episode_frames_dir(2), "04-frames/ep02")

    def test_export_guards_refuse_animatic(self) -> None:
        from director.gates import ken_burns_blocked

        self.assertTrue(ken_burns_blocked(Path("ep01.animatic.mp4")))
        self.assertFalse(ken_burns_blocked(Path("SH001.mp4")))
        script = (SCRIPTS / "assemble.sh").read_text(encoding="utf-8")
        self.assertIn("animatic", script)


CAMERA_SET = {
    "id": "ancient-shoal",
    "name": "古河边浅滩",
    "marks": [
        {"id": "camera", "x": 0.5, "y": 0.95, "note": "旧机位标"},
        {"id": "sokha", "x": 0.35, "y": 0.5, "note": "速卡"},
        {"id": "yunlong", "x": 0.65, "y": 0.5, "note": "云朗"},
    ],
    "cameras": [
        {"id": "A", "x": 0.5, "y": 0.9, "facing_deg": 0, "lens": "35mm", "label": "master"},
        {"id": "B", "x": 0.9, "y": 0.75, "facing_deg": 300, "lens": "50mm"},
        {"id": "C", "x": 0.5, "y": 0.1, "facing_deg": 180, "lens": "50mm", "label": "跳轴"},
    ],
}


class CameraPlot(unittest.TestCase):
    def test_screen_side_eyeline_and_axis(self) -> None:
        from director.camera_plot import axis_check, eyeline_direction, screen_side, set_cameras

        sokha, yunlong = CAMERA_SET["marks"][1], CAMERA_SET["marks"][2]
        a, b, c = set_cameras(CAMERA_SET)
        self.assertEqual(screen_side(a, sokha, yunlong), "left")
        self.assertEqual(screen_side(b, sokha, yunlong), "left")
        self.assertEqual(screen_side(c, sokha, yunlong), "right")
        self.assertEqual(screen_side({"id": "D", "x": 0.5, "y": 0.9}, sokha, yunlong), "left")  # no facing: looks at the pair
        self.assertEqual(eyeline_direction(a, sokha, yunlong), "画右")
        self.assertEqual(eyeline_direction(c, sokha, yunlong), "画左")
        self.assertEqual(eyeline_direction({"id": "D", "x": 0.35, "y": 0.9, "facing_deg": 0}, sokha, {"x": 0.35, "y": 0.95}), "朝镜头")
        self.assertEqual(eyeline_direction({"id": "D", "x": 0.35, "y": 0.9, "facing_deg": 0}, sokha, {"x": 0.35, "y": 0.1}), "背镜头")
        self.assertEqual(axis_check([a, b], sokha, yunlong), [])
        problems = axis_check([a, b, c], sokha, yunlong)
        self.assertEqual(len(problems), 1)
        self.assertIn("cameras C cross the axis sokha–yunlong", problems[0])
        on_axis = axis_check([{"id": "E", "x": 0.5, "y": 0.5}], sokha, yunlong)
        self.assertTrue(any("sits on the axis" in p for p in on_axis), on_axis)

    def test_suggest_sides_and_report(self) -> None:
        from director.camera_plot import set_report, side_disagreements, suggest_sides

        ok = suggest_sides(CAMERA_SET, {"shot_id": "SH004", "camera_id": "A", "left": "速卡", "right": "云朗", "eyeline": "互看"})
        self.assertEqual((ok["left"], ok["right"], ok["eyeline"]), ("sokha", "yunlong", "画右"))
        self.assertTrue(ok["matches_design"])
        flipped = suggest_sides(CAMERA_SET, {"shot_id": "SH004", "camera_id": "C", "left": "速卡", "right": "云朗"})
        self.assertFalse(flipped["matches_design"])
        self.assertEqual((flipped["left"], flipped["right"]), ("yunlong", "sokha"))
        self.assertTrue(side_disagreements(CAMERA_SET, {"shot_id": "SH004", "camera_id": "C", "left": "速卡", "right": "云朗"}))
        self.assertEqual(side_disagreements(CAMERA_SET, {"shot_id": "SH004", "camera_id": "A", "left": "速卡", "right": "云朗"}), [])
        self.assertTrue(suggest_sides(CAMERA_SET, {"camera_id": "Z"})["unknown_camera"])
        self.assertEqual(suggest_sides(CAMERA_SET, {"left": "速卡"}), {})
        loose = suggest_sides(CAMERA_SET, {"shot_id": "SH001", "camera_id": "A", "left": "", "right": ""})
        self.assertEqual((loose["left"], loose["right"]), ("sokha", "yunlong"))
        report = set_report(CAMERA_SET)
        self.assertEqual(report["axis"], ["sokha", "yunlong"])
        self.assertEqual(len(report["axis_problems"]), 1)
        self.assertEqual(report["views"][2]["left_to_right"], ["yunlong", "sokha"])

    def test_shot_table_hook(self) -> None:
        sets = copy.deepcopy(SETS)
        sets["sets"][1] = copy.deepcopy(CAMERA_SET)
        profile = get_profile("seedance_2_0")
        shots = good_shots()
        shots[3]["camera_id"] = "A"
        errors, warnings = validate_shot_table(table(shots), writer=WRITER, sets=sets, profile=profile, look_text=LOOK)
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("camera" in w for w in warnings), warnings)
        shots[3]["camera_id"] = "C"
        errors, warnings = validate_shot_table(table(shots), writer=WRITER, sets=sets, profile=profile, look_text=LOOK)
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("SH004 designed left=速卡 right=云朗, but camera C sees yunlong on the left" in w for w in warnings), warnings)
        shots[3]["camera_id"] = "Z"
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=sets, profile=profile, look_text=LOOK)
        self.assertTrue(any("SH004 camera_id Z is not a camera in sets.json" in e for e in errors), errors)
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=SETS, profile=profile, look_text=LOOK)
        self.assertTrue(any("camera_id Z" in e for e in errors), errors)

    def test_used_cameras_crossing_is_error(self) -> None:
        sets = copy.deepcopy(SETS)
        sets["sets"][1] = copy.deepcopy(CAMERA_SET)
        profile = get_profile("seedance_2_0")
        shots = good_shots()
        shots[2]["camera_id"] = "A"
        shots[3]["camera_id"] = "C"
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=sets, profile=profile, look_text=LOOK)
        self.assertTrue(any("cross the axis" in e for e in errors), errors)
        shots[3]["camera_id"] = "A"
        errors, _ = validate_shot_table(table(shots), writer=WRITER, sets=sets, profile=profile, look_text=LOOK)
        self.assertFalse(any("cross the axis" in e for e in errors), errors)

    def test_render_plot_writes_png(self) -> None:
        from PIL import Image

        from director.camera_plot import render_all, render_plot

        with tempfile.TemporaryDirectory() as tmp:
            out = render_plot(CAMERA_SET, Path(tmp) / "plot.png")
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (1200, 800))
            prod = Path(tmp) / "p"
            prod.mkdir()
            result = render_all(prod, {"sets": [CAMERA_SET, {"id": "empty"}]})
            self.assertEqual(result["written"], ["02-assets/scenes/ancient-shoal/camera-plot.png"])
            self.assertTrue((prod / "02-assets" / "scenes" / "ancient-shoal" / "camera-plot.png").exists())


class ModelNotes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("DIRECTOR_MODEL_NOTES_DIR")
        os.environ["DIRECTOR_MODEL_NOTES_DIR"] = str(Path(self.tmp.name) / "notes")

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("DIRECTOR_MODEL_NOTES_DIR", None)
        else:
            os.environ["DIRECTOR_MODEL_NOTES_DIR"] = self.old
        self.tmp.cleanup()

    def test_record_and_experience(self) -> None:
        from director.model_notes import experience_for, read_feedback, record_outcome, snapshot_feedback
        from director.pipeline import write_artifact

        prod = Path(self.tmp.name) / "010-demo"
        prod.mkdir()
        write_artifact(prod, "shot_list.json", table(good_shots(), target_model="seedance_2_0"))
        self.assertEqual(profile_brief(get_profile("seedance_2_0"))["experience"], [])
        first = record_outcome(prod, "SH004", "fail", ["close", "hands"], "漂")
        self.assertEqual(first["item"]["profile_id"], "seedance_2_0")
        record_outcome(prod, "SH001", "pass", "", "稳")  # tags read from the table: wide + static + master
        record_outcome(prod, "SH002", "pass", "medium、static", "", "seedance")
        feedback = read_feedback(prod)
        self.assertEqual(len(feedback["items"]), 3)
        self.assertEqual(feedback["items"][1]["tags"], ["wide", "static", "master"])
        md = Path(os.environ["DIRECTOR_MODEL_NOTES_DIR"]) / "seedance_2_0.md"
        self.assertTrue(md.exists())
        text = md.read_text(encoding="utf-8")
        self.assertIn("## close + hands", text)
        self.assertIn("- close + hands → 漂（010-demo SH004，fail）", text)
        experience = profile_brief(get_profile("seedance_2_0"))["experience"]
        self.assertEqual(len(experience), 3)
        self.assertEqual(experience[0], "close + hands → 漂（010-demo SH004，fail）")
        self.assertEqual(experience_for("minimax_h3"), [])
        snap = snapshot_feedback(prod)
        self.assertEqual(snap["profile_id"], "seedance_2_0")
        self.assertEqual(len(snap["items"]), 3)
        with self.assertRaises(ValueError):
            record_outcome(prod, "SH001", "meh", ["x"])
        with self.assertRaises(ValueError):
            record_outcome(prod, "SH999", "pass", [])
        for _ in range(45):
            record_outcome(prod, "SH003", "fail", ["full", "push"], "糊")
        bullets = [line for line in md.read_text(encoding="utf-8").splitlines() if line.startswith("- ") and "→" in line]
        self.assertEqual(len(bullets), 40)

    def test_seeds_lead_experience_and_survive_qc_rewrite(self) -> None:
        from director.model_notes import experience_for, parse_seeds, read_seeds, record_outcome, seed_notes
        from director.pipeline import write_artifact

        rows = [
            {"现象": "全片几乎不动", "原因": "motion_prompt 里只有外观没有 one_action", "处理": "改成起幅→动作→落幅，重跑不加 attempt"},
            ("HTTP 400", "风控拦词", "改写提示词再提，原样硬重试不算 attempt"),
        ]
        result = seed_notes("seedance", rows)
        self.assertEqual(result["profile_id"], "seedance_2_0")
        md = Path(os.environ["DIRECTOR_MODEL_NOTES_DIR"]) / "seedance_2_0.md"
        text = md.read_text(encoding="utf-8")
        self.assertIn("## 种子", text)
        self.assertIn("| 现象 | 原因 | 处理 |", text)
        self.assertIn("| HTTP 400 | 风控拦词 | 改写提示词再提，原样硬重试不算 attempt |", text)
        self.assertEqual(len(parse_seeds(text)), 2)
        self.assertEqual(
            profile_brief(get_profile("seedance_2_0"))["experience"],
            ["全片几乎不动 → motion_prompt 里只有外观没有 one_action → 改成起幅→动作→落幅，重跑不加 attempt", "HTTP 400 → 风控拦词 → 改写提示词再提，原样硬重试不算 attempt"],
        )
        # a QC write-back regenerates the page but keeps the hand-written table, seeds still first
        prod = Path(self.tmp.name) / "010-demo"
        prod.mkdir()
        write_artifact(prod, "shot_list.json", table(good_shots(), target_model="seedance_2_0"))
        record_outcome(prod, "SH004", "fail", ["close", "hands"], "漂")
        experience = experience_for("seedance_2_0")
        self.assertEqual(len(experience), 3)
        self.assertTrue(experience[0].startswith("全片几乎不动 → "))
        self.assertEqual(experience[2], "close + hands → 漂（010-demo SH004，fail）")
        self.assertEqual(len(read_seeds("seedance_2_0")), 2)
        # same 现象 replaces, not duplicates; empty cells are rejected
        seed_notes("seedance_2_0", [("HTTP 400", "风控拦词", "换词再提")])
        seeds = read_seeds("seedance_2_0")
        self.assertEqual([row["symptom"] for row in seeds], ["全片几乎不动", "HTTP 400"])
        self.assertEqual(seeds[1]["fix"], "换词再提")
        self.assertEqual(len(experience_for("seedance_2_0", limit=2)), 2)
        with self.assertRaises(ValueError):
            seed_notes("seedance_2_0", [("只有现象", "", "")])
        self.assertEqual(experience_for("minimax_h3"), [])

    def test_design_context_carries_experience(self) -> None:
        from director.model_notes import record_outcome
        from director.station_agents import _design_base_context

        prod = ROOT / "productions" / "009-siem-reap"
        if not (prod / ".pipeline" / "writer.json").exists():
            self.skipTest("009 writer.json missing")
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "scratch"
            scratch.mkdir()
            from director.pipeline import write_artifact

            write_artifact(scratch, "shot_list.json", table(good_shots(), target_model="seedance_2_0"))
            record_outcome(scratch, "SH004", "fail", ["otc", "hands"], "手指多一根", "seedance_2_0")
        ctx = _design_base_context(prod, "seedance_2_0")
        self.assertIn("otc + hands → 手指多一根（scratch SH004，fail）", ctx["target_profile"]["experience"])


if __name__ == "__main__":
    unittest.main()
