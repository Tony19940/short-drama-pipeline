#!/usr/bin/env python3
"""Hell Grind grafts: Seedance native speech (voice cards / audio block / km guard), acting = behavior,
first frame = action onset with ACTION TIMING from 0.0s, GEO block, positive-only motion prompts,
ban dictionary, 500-char trim, video-ready field carry-over, renderer handoff text."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import carry_video_ready_fields  # noqa: E402
from director.acting import (  # noqa: E402
    EYE_LIFE,
    acting_sentence,
    acting_warnings,
    compile_acting_zh,
    emotion_adjectives_in,
    normalize_acting,
    physical_expression,
)
from director.acting import merge_acting  # noqa: E402
from director.frame_desc import compile_frame_desc_from_shot, frame_description_warnings, normalize_item  # noqa: E402
from director.pipeline import compile_packages_from_specs, validate_packages, write_artifact  # noqa: E402
from director.prompts import (  # noqa: E402
    MAX_ZH_PROMPT_CHARS,
    NEGATIVE_RE,
    action_timing_zh,
    apply_ban_dictionary,
    assemble_motion_prompt,
    camera_sentence_zh,
    compile_keyframe_prompt_zh,
    compile_seedance_motion_detail,
    compile_seedance_motion_from_spec,
    compile_seedance_prompt,
    dedupe_sentences,
    geo_layout_for,
    load_ban_dictionary,
    positive_text,
)
from director.shot_table import sanitize_shot_table, validate_shot_table  # noqa: E402
from director.speech import (  # noqa: E402
    SpeechLanguageError,
    cards_by_name,
    check_dialogue_language,
    compile_audio_block,
    descriptor_for,
    load_character_cards,
    parse_character_cards,
    sound_bed_for,
    speech_mode_for,
)
from director.still_t0 import (  # noqa: E402
    ONSET_OK,
    forbidden_result_clause,
    is_onset_state,
    start_still_errors,
)
from render_seedance_packages import plan_shot, write_markdown  # noqa: E402

CARDS_MD = """# 人物简介

## **rin** · 琳 / Rin

- **身份**：20。临时清洁工。
- **声音卡**：二十岁女声，偏高偏细，句子短；一急就更快更碎，绝不喊。
- **外形卡**（机读，100% 以参考图为准）：
  - cleaning：瘦小缩肩，发网；清洁短袖加旧围裙，胸前 T-0417 工牌
  - guest：瘦小，披发；细条纹见客衬衫

## **chanthy** · 春安 / Chanthy

- **声音卡**：三十出头女声，中低音，字咬得死，句尾往下砸。
- **外形卡**：中等身材，短发利落；车间主管厂服，左手挂线头

## 过场人物

- **阿良 / Rith**：只以字条出场。

### **worker** · 女工 / Worker（过场）

- **声音卡**：三十来岁女声，隔着门大声喊，一句喊完就断。
- **外形卡**：普通女工身材；灰蓝厂服无围裙
"""

SETS = {
    "sets": [
        {"id": "storeroom", "name": "杂物间", "axis": "柜在画左", "geo_zh": "灰铁皮柜在画左约1.5米，门中偏左约3米；机位在柜前正面侧，永不越到布架侧；头顶冷白灯管", "sound_bed_zh": "闷热杂物间底噪"},
        {"id": "line-7", "name": "七线", "axis": "琳在画左，春安在画右"},
    ]
}

ASSETS = {
    "assets": [
        {"asset_id": "LOC_STOREROOM_V1", "type": "location", "name": "storeroom", "binds_to": "storeroom", "file": "02-assets/scenes/storeroom/master.jpg", "lock_card": []},
        {"asset_id": "LOC_LINE-7_V1", "type": "location", "name": "line-7", "binds_to": "line-7", "file": "02-assets/scenes/line-7/master.jpg", "lock_card": []},
        {"asset_id": "CHAR_RIN_V1", "type": "character", "name": "rin", "binds_to": "rin", "file": "02-assets/characters/rin/master.jpg", "lock_card": []},
        {"asset_id": "CHAR_CHANTHY_V1", "type": "character", "name": "chanthy", "binds_to": "chanthy", "file": "02-assets/characters/chanthy/master.jpg", "lock_card": []},
    ]
}

WRITER = {
    "series_bible": {"characters": [{"id": "rin", "name": "琳"}, {"id": "chanthy", "name": "春安"}, {"id": "worker", "name": "女工"}]},
    "scenes": [
        {"scene_id": "EP01_SC02", "location_id": "storeroom", "dialogue": [{"character": "琳", "line": "这柜门还虚掩着？"}]},
        {"scene_id": "EP01_SC03", "location_id": "line-7", "dialogue": [{"character": "春安", "line": "车底下塞的什么？"}]},
    ],
}


def _shot(sid: str, **over) -> dict:
    base = {
        "shot_id": sid,
        "scene_id": "EP01_SC02",
        "location_id": "storeroom",
        "beat": "开柜",
        "shot_job": "开柜看见工牌",
        "coverage_type": "single",
        "scale": "medium",
        "angle": "eye",
        "lens": "50mm",
        "move_type": "static",
        "camera_side": "front-left",
        "body_facing": "四分之三",
        "left": "琳",
        "right": "柜",
        "eyeline": "看柜",
        "one_action": "琳一气拉开虚掩铁皮柜",
        "in_from": "手已搭上柜内仍暗",
        "out_to": "柜门已开灰工牌在柜内",
        "duration_sec": 3.5,
        "dialogue_ref": [{"character": "琳", "track": "琳-独白", "line": "这柜门还虚掩着？", "manner": "自言自语地"}],
        "dialogue_delivery": "on_camera",
        "key_sfx": ["柜门吱呀"],
        "characters": ["琳"],
        "light": {"day_night": "day", "key_dir": "top", "quality": "hard", "color": "冷白"},
        "state": {"characters": {"rin": {"costume": "cleaning", "in_frame": True}}, "props": [], "note": "琳穿清洁围裙；禁止汗字；名单不得入画。胸前 T-0417。"},
        "acting": {"琳": {"want": "看看里面", "hide": "手在抖", "business": "手搭柜门", "muscle": "一把拉开，眼跟着探进去", "change": "柜门从虚掩到全开"}},
    }
    base.update(over)
    return base


def _table(shots: list[dict], **over) -> dict:
    data = {
        "schema": "shot-table-v2",
        "episode_no": 1,
        "target_model": "seedance_2_0",
        "aspect": "16:9",
        "whose_pov": "rin",
        "left_right_lock": {"EP01_SC02": "柜左布架右", "EP01_SC03": "琳左春安右"},
        "continuity_bible": {"eyeline": "", "wardrobe": "", "day_night": "day", "props": [], "evidence": []},
        "visible_change_without_dialogue": "pass",
        "shots": shots,
    }
    data.update(over)
    return sanitize_shot_table(data, writer=WRITER)


def _prod(tmp: str, *, sets: dict = SETS, cards_md: str = CARDS_MD) -> Path:
    prod = Path(tmp) / "010-demo"
    (prod / "01-bible").mkdir(parents=True)
    (prod / "03-storyboard").mkdir()
    (prod / "01-bible" / "CHARACTERS.md").write_text(cards_md, encoding="utf-8")
    (prod / "03-storyboard" / "sets.json").write_text(json.dumps(sets, ensure_ascii=False), encoding="utf-8")
    write_artifact(prod, "assets.json", ASSETS)
    return prod


class SpeechLanguage(unittest.TestCase):
    def test_km_with_first_frame_raises_and_explains(self) -> None:
        with self.assertRaises(SpeechLanguageError) as ctx:
            check_dialogue_language("km", speech_mode="seedance_native", shot_id="SH030")
        message = str(ctx.exception)
        self.assertIn("SH030", message)
        self.assertIn("reference_audio", message)
        self.assertIn("first_frame", message)
        self.assertIn("post_dub", message)
        self.assertEqual(check_dialogue_language("zh"), "zh")
        self.assertEqual(check_dialogue_language("", speech_mode="seedance_native"), "zh")
        # post dub does not speak, so any language tag may ride along for the dub crew
        self.assertEqual(check_dialogue_language("km", speech_mode="post_dub"), "km")
        with self.assertRaises(SpeechLanguageError):
            check_dialogue_language("zh", speech_mode="karaoke")

    def test_speech_mode_defaults_to_native_when_model_lip_syncs(self) -> None:
        self.assertEqual(speech_mode_for({}, {"native_dialogue_audio": True}), "seedance_native")
        self.assertEqual(speech_mode_for({}, {"native_dialogue_audio": False}), "post_dub")
        self.assertEqual(speech_mode_for({"speech_mode": "post_dub"}, {"native_dialogue_audio": True}), "post_dub")


class VoiceCards(unittest.TestCase):
    def test_parse_characters_md(self) -> None:
        cards = parse_character_cards(CARDS_MD)
        self.assertEqual(set(cards), {"rin", "chanthy", "worker"})
        self.assertEqual(cards["rin"]["name"], "琳")
        self.assertTrue(cards["rin"]["voice_card"].startswith("二十岁女声"))
        self.assertEqual(set(cards["rin"]["descriptor_by_costume"]), {"cleaning", "guest"})
        self.assertEqual(cards["worker"]["name"], "女工")
        self.assertTrue(cards["chanthy"]["descriptor"].startswith("中等身材"))
        named = cards_by_name(cards, {"rin": "琳", "chanthy": "春安"})
        self.assertEqual(
            descriptor_for("琳", named, "guest"),
            "琳：瘦小，披发；细条纹见客衬衫；100% 以参考图为准。",
        )
        self.assertTrue(descriptor_for("琳", named, "unknown-state").startswith("琳：瘦小缩肩"))
        self.assertEqual(descriptor_for("保安", named), "")

    def test_machine_copy_is_fallback_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            prod.mkdir()
            write_artifact(prod, "voice_cards.json", {"characters": {"rin": {"name": "琳", "voice_card": "机读卡", "descriptor": "瘦"}}})
            self.assertEqual(load_character_cards(prod)["rin"]["voice_card"], "机读卡")
            (prod / "01-bible").mkdir()
            (prod / "01-bible" / "CHARACTERS.md").write_text(CARDS_MD, encoding="utf-8")
            self.assertTrue(load_character_cards(prod)["rin"]["voice_card"].startswith("二十岁女声"))


class AudioBlock(unittest.TestCase):
    CARDS = cards_by_name(parse_character_cards(CARDS_MD), {"rin": "琳", "chanthy": "春安"})

    def test_one_line_voice_card_verbatim_silent_others_ambience(self) -> None:
        block = compile_audio_block(
            [{"character": "春安", "line": "车底下塞的什么？", "track": "春安-口白", "manner": "扬着声"}],
            cards=self.CARDS,
            in_frame=["琳", "春安", "女工"],
            key_sfx=["布甩在地上"],
            sound_bed="七线缝纫机运转声",
        )
        card = self.CARDS["春安"]["voice_card"].rstrip("。")
        self.assertIn(f"春安（{card}）用普通话扬着声说：“车底下塞的什么？”。", block)
        self.assertIn("只说这一句。", block)
        self.assertIn("琳、女工不说话，嘴闭着。", block)
        self.assertTrue(block.endswith("环境声只保留七线缝纫机运转声、布甩在地上，无音乐，无字幕。"))
        self.assertNotIn("对白不进画面", block)

    def test_monologue_default_manner_and_offscreen_speaker(self) -> None:
        block = compile_audio_block(
            [{"character": "琳", "line": "她脚下怎么没有影子？", "track": "琳-独白"}],
            cards=self.CARDS,
            in_frame=["波帕"],
            sound_bed="闷热杂物间底噪",
        )
        self.assertIn("琳画外音（", block)
        self.assertIn("用普通话低声自语地说：“她脚下怎么没有影子？”", block)
        self.assertIn("波帕不说话，嘴闭着。", block)

    def test_two_lines_sequential_each_with_card(self) -> None:
        block = compile_audio_block(
            [
                {"character": "春安", "line": "签。", "track": "春安-口白"},
                {"character": "琳", "line": "不是我拿的。", "track": "琳-口白"},
            ],
            cards=self.CARDS,
            in_frame=["琳", "春安"],
        )
        self.assertTrue(block.startswith("先，春安（"))
        self.assertIn("接着，琳（", block)
        self.assertIn("两人各只说自己这一句。", block)
        self.assertLess(block.index("签。"), block.index("不是我拿的。"))

    def test_mute_shot(self) -> None:
        self.assertEqual(
            compile_audio_block([], in_frame=["琳"], key_sfx=["扫帚刮地"], sound_bed="闷热杂物间底噪"),
            "画中所有人不说话，嘴闭着。只有环境声：闷热杂物间底噪、扫帚刮地。无音乐，无字幕。",
        )
        self.assertTrue(compile_audio_block([], in_frame=[], sound_bed="厂区底噪").startswith("画中无人开口。"))
        self.assertEqual(sound_bed_for("storeroom", SETS), "闷热杂物间底噪")
        self.assertIn("缝纫机", sound_bed_for("line-7", SETS))


class Acting(unittest.TestCase):
    def test_adjective_detector_and_hint(self) -> None:
        self.assertEqual(emotion_adjectives_in("春安横脸讥"), ["横", "讥"])
        self.assertEqual(emotion_adjectives_in("琳咬牙鼻息重"), [])
        shots = [
            {"shot_id": "SH007", "expression": "春安横脸讥", "acting": {"春安": {"want": "压住她", "muscle": "冷笑一下"}}},
            {"shot_id": "SH008", "expression": "春安甩手扔钥匙", "acting": {"春安": {"want": "愤怒", "muscle": "手腕一甩"}}},
        ]
        warnings = acting_warnings(shots)
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("acting_adjective" in w for w in warnings))
        self.assertTrue(any("SH007" in w and "expression" in w for w in warnings))
        self.assertTrue(any("acting.春安.muscle" in w and "冷笑" in w for w in warnings))
        self.assertTrue(all("眼先到头后转" in w for w in warnings))
        # want / hide are the inner line: never flagged
        self.assertFalse(any("SH008" in w for w in warnings))

    def test_physical_expression_drops_feelings(self) -> None:
        self.assertEqual(physical_expression("琳怕得眼瞪大"), "琳眼瞪大")
        self.assertEqual(physical_expression("波帕冷得过分逼近"), "波帕逼近")
        self.assertEqual(physical_expression("春安横脸讥"), "")
        self.assertEqual(physical_expression("无脸只物件"), "无脸只物件")

    def test_sentence_eye_life_and_reaction_rule(self) -> None:
        acting = normalize_acting({"琳": {"want": "不签", "hide": "腿在抖", "business": "空手垂在身侧", "muscle": "站直，咬牙", "change": "手垂下"}})
        self.assertEqual(acting_sentence("琳", acting["琳"]), "琳：想不签；藏着腿在抖；空手垂在身侧；站直，咬牙；手垂下。")
        self.assertEqual(acting_sentence("琳", {"business": "钥匙在指间转"}), "琳：手上钥匙在指间转。")
        shot = {"scale": "medium", "body_facing": "四分之三", "acting": {"春安": {"muscle": "手腕一甩"}}}
        lines = compile_acting_zh(shot, in_frame=["琳", "春安"], speakers=["春安"])
        self.assertIn(f"琳：{EYE_LIFE}。", lines)
        self.assertIn("春安：手腕一甩。", lines)
        self.assertIn("对方话没说完，琳的脸已经在答。", lines)
        # wide shot with no face: no eye-life default; no line: no reaction rule
        self.assertEqual(compile_acting_zh({"scale": "wide", "body_facing": "背对镜头"}, in_frame=["琳"]), [])

    def test_frame_desc_no_exaggerated_expression(self) -> None:
        item = compile_frame_desc_from_shot(_shot("SH021", expression="琳愣住拉开", still_start="柜门仍虚掩尚未拉开"))
        blob = json.dumps(item, ensure_ascii=False)
        self.assertNotIn("夸张表情", blob)
        self.assertNotIn("愣", blob)
        self.assertEqual(item["subject"]["micro_expression"], "琳拉开")
        self.assertIn("已打开", item["forbidden"])
        self.assertFalse(any("禁止" in f for f in item["forbidden"]))

    def test_table_validation_warns_not_errors(self) -> None:
        table = _table([_shot("SH021", expression="琳愣住拉开")])
        errors, warnings = validate_shot_table(table, writer=WRITER, sets=SETS, profile={"native_dialogue_audio": True})
        self.assertFalse(any("acting" in e for e in errors))
        self.assertTrue(any("SH021 acting_adjective 「愣住」 in expression" in w for w in warnings), warnings)
        self.assertEqual(table["shots"][0]["acting"]["琳"]["muscle"], "一把拉开，眼跟着探进去")


class FirstFrameOnset(unittest.TestCase):
    def test_onset_states_pass_results_fail(self) -> None:
        shot = {"shot_id": "SH008", "one_action": "春安把旧钥匙扔到琳脚边", "in_from": "钥匙仍在春安手里"}
        onset = {"one_paragraph": "春安手已扬起，钥匙还在手里，已起手", "still_start": {"one_paragraph": "手已扬起"}}
        self.assertEqual(start_still_errors(shot, onset), [])
        done = {"one_paragraph": "钥匙已落地停在脚边", "still_start": {"one_paragraph": "钥匙已落地"}}
        errors = start_still_errors(shot, done)
        self.assertTrue(any("mid/result" in e for e in errors), errors)
        self.assertTrue(is_onset_state("手已伸出"))
        self.assertIn("已起手", ONSET_OK)

    def test_result_clause_is_positive(self) -> None:
        clause = forbidden_result_clause("琳弯腰捡起脚边旧钥匙")
        self.assertTrue(clause.startswith("首帧是动作起点：可以已经起手"))
        self.assertIn("已在手里", clause)
        self.assertIsNone(NEGATIVE_RE.search(clause))
        self.assertIsNone(NEGATIVE_RE.search(forbidden_result_clause("琳抬眼")))

    def test_still_prompt_carries_geo_and_descriptor_once(self) -> None:
        geo = geo_layout_for("storeroom", SETS)
        self.assertTrue(geo.startswith("【空间锁·杂物间】"))
        prompt = compile_keyframe_prompt_zh(
            {"in_from": "手已搭上柜内仍暗", "action_now": "琳一气拉开虚掩铁皮柜", "shot_size": "medium"},
            _shot("SH021"),
            geo_layout=geo,
            descriptors=["琳：瘦小缩肩；100% 以参考图为准。"],
        )
        self.assertTrue(prompt.startswith(geo))
        self.assertIn("人物锁：琳：瘦小缩肩；100% 以参考图为准。", prompt)
        self.assertEqual(prompt.count("首帧是动作起点"), 1)
        self.assertNotIn("。。", prompt)
        self.assertNotIn("画动作尚未发生", prompt)
        self.assertNotIn("禁止把 one_action", prompt)


class MotionPrompt(unittest.TestCase):
    def test_action_timing_from_zero(self) -> None:
        text, beats = action_timing_zh("春安把旧钥匙扔到琳脚边", "钥匙仍在春安手里", "钥匙停在琳脚边地上", 4)
        self.assertTrue(text.startswith("0.0s 起就在动（首帧已起手：钥匙仍在春安手里）。"))
        self.assertIn("0.0–1.5s：春安把旧钥匙扔到琳脚边。", text)
        self.assertIn("1.5–4s：落幅——钥匙停在琳脚边地上，停住，气还没平。", text)
        self.assertEqual([b["from_sec"] for b in beats], [0.0, 1.5])
        self.assertEqual(beats[1]["to_sec"], 4)
        short, short_beats = action_timing_zh("纸边发颤", "", "", 3)
        self.assertEqual(len(short_beats), 1)
        self.assertIn("气还没平", short)

    def test_positive_only_and_dedupe(self) -> None:
        self.assertEqual(positive_text("名单、保安不得入画。胸前 T-0417。禁止汉字；琳说：“不要怕”"), "胸前 T-0417。板上文字只用拉丁字母；琳说：“不要怕”")
        self.assertEqual(dedupe_sentences("A。B。A。。C。"), "A。B。C。")
        self.assertIn("机位固定在正面偏右", camera_sentence_zh("static", "front-right"))
        self.assertIsNone(NEGATIVE_RE.search(camera_sentence_zh("push", "front")))
        detail = compile_seedance_motion_detail(
            {
                "in_from": "钥匙仍在春安手里",
                "out_to": "钥匙停在琳脚边地上",
                "action_now": "春安把旧钥匙扔到琳脚边",
                "duration_sec": 4.2,
                "camera_side": "front-right",
                "move_type": "static",
                "key_sfx": ["钥匙落地"],
                "state": {"characters": {"rin": {}}, "note": "名单、保安不得入画。琳在画左，清洁车在身边；禁止汉字。"},
            },
            _shot("SH008", dialogue_ref=[{"character": "春安", "track": "春安-口白", "line": "后面那间一年都没开过了，赶紧去。"}], acting={"春安": {"muscle": "手腕一甩"}}),
            geo_layout="【空间锁·厂门】门房在画左。",
            descriptors=["春安：短发利落；100% 以参考图为准。"],
            acting_lines=["春安：手腕一甩。", "对方话没说完，琳的脸已经在答。"],
            render_sec=4,
        )
        prompt = detail["prompt"]
        outside_quotes = re.sub(r"“[^”]*”", "", prompt)
        self.assertIsNone(NEGATIVE_RE.search(outside_quotes), prompt)
        sentences = [s for s in re.split(r"(?<=[。！？])", prompt) if s.strip()]
        self.assertEqual(len(sentences), len(set(sentences)), prompt)
        self.assertTrue(prompt.startswith("【空间锁·厂门】门房在画左。"))
        self.assertLess(prompt.index("【人物锁】"), prompt.index("【动作时间轴】"))
        self.assertLess(prompt.index("【动作时间轴】"), prompt.index("【表演】"))
        self.assertLess(prompt.index("【表演】"), prompt.index("【机位】"))
        self.assertLess(prompt.index("【机位】"), prompt.index("【声音】"))
        self.assertIn("0.0s 起就在动", prompt)
        self.assertIn("说：“后面那间一年都没开过了，赶紧去。”", prompt)
        self.assertIn("【连戏】琳在画左，清洁车在身边；板上文字只用拉丁字母。", prompt)
        self.assertNotIn("对白不进画面", prompt)
        self.assertNotIn("时长约", prompt)
        self.assertEqual(detail["chars"], len(prompt))
        self.assertEqual(detail["dropped"], [])
        self.assertEqual(len(detail["beats"]), 2)
        # the speech lives only in the audio block: action text never quotes the line
        head = prompt.split("【声音】")[0]
        self.assertNotIn("赶紧去", head)

    def test_post_dub_keeps_mouths_closed(self) -> None:
        prompt = compile_seedance_motion_from_spec(
            {"action_now": "琳抬眼", "duration_sec": 4},
            _shot("SH065", dialogue_ref=[{"character": "琳", "line": "不是我拿的。"}]),
            speech_mode="post_dub",
        )
        self.assertNotIn("不是我拿的", prompt)
        self.assertIn("画中无人开口。", prompt)

    def test_trim_order_and_never_dropped_parts(self) -> None:
        card = "二十岁女声，偏高偏细，说话轻、句子短，尾音常收不住会咽回去；一急就更快更碎，带一点气声，绝不喊"

        def segments(geo_repeat: int) -> list[dict]:
            return [
                {"tag": "geo", "text": "【空间锁】" + "门房在画左，" * geo_repeat + "。"},
                {"tag": "lock", "text": "【人物锁】琳：" + "瘦小缩肩，发网，围裙，胶鞋，" * 12 + "100% 以参考图为准。", "short": "【人物锁】琳：100% 以参考图为准。"},
                {"tag": "timing", "text": "【动作时间轴】0.0s 起就在动（首帧已起手：手已搭上）。0.0–1.5s：拉开。1.5–4s：落幅——柜开，停住，气还没平。"},
                {"tag": "camera", "text": "【机位】机位固定在正面。"},
                {"tag": "continuity", "text": "【连戏】" + "琳穿清洁围裙，胸前 T-0417，" * 8 + "。"},
                {"tag": "style", "text": "数字电影 CG 质感。"},
                {"tag": "audio", "text": f"【声音】琳（{card}）用普通话说：“这柜门还虚掩着？”。只说这一句。无音乐，无字幕。"},
            ]

        # decoration → repeated continuity → descriptor detail, then it fits
        result = assemble_motion_prompt(segments(30), limit=MAX_ZH_PROMPT_CHARS)
        self.assertEqual(result["dropped"], ["style", "continuity", "lock_detail"])
        prompt = result["prompt"]
        self.assertNotIn("数字电影 CG 质感", prompt)
        self.assertNotIn("【连戏】", prompt)
        self.assertIn("【人物锁】琳：100% 以参考图为准。", prompt)
        self.assertNotIn("瘦小缩肩", prompt)
        self.assertFalse(result["over_limit"])
        self.assertEqual(result["chars"], len(prompt))
        # only the first two tiers are needed here: descriptor detail survives
        partial = assemble_motion_prompt(segments(8), limit=MAX_ZH_PROMPT_CHARS)
        self.assertEqual(partial["dropped"], ["style", "continuity"])
        self.assertIn("瘦小缩肩", partial["prompt"])
        # a GEO block too long to fit: everything protected stays, over_limit is reported
        heavy = assemble_motion_prompt(segments(70), limit=MAX_ZH_PROMPT_CHARS)
        self.assertEqual(heavy["dropped"], ["style", "continuity", "lock_detail"])
        self.assertTrue(heavy["over_limit"])
        for kept in ("【空间锁】", card, "“这柜门还虚掩着？”", "首帧已起手：手已搭上", "0.0–1.5s", "【机位】"):
            self.assertIn(kept, heavy["prompt"])
        # under the limit: nothing is touched
        small = assemble_motion_prompt([{"tag": "style", "text": "数字电影 CG 质感。"}, {"tag": "audio", "text": "【声音】无音乐。"}])
        self.assertEqual(small["dropped"], [])
        self.assertFalse(small["over_limit"])

    def test_ban_dictionary_default_and_override(self) -> None:
        self.assertEqual(apply_ban_dictionary("走进黑暗的杂物间"), "走进低调光的杂物间")
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp)
            self.assertNotIn("血", load_ban_dictionary(prod))
            (prod / "03-storyboard").mkdir()
            (prod / "03-storyboard" / "ban_dictionary.json").write_text(json.dumps({"血": "深色污渍", "黑暗": "夜色"}, ensure_ascii=False), encoding="utf-8")
            table = load_ban_dictionary(prod)
            self.assertEqual(table["血"], "深色污渍")
            self.assertEqual(table["黑暗"], "夜色")
            self.assertEqual(apply_ban_dictionary("黑暗里一滴血", table), "夜色里一滴深色污渍")

    def test_legacy_seedance_prompt_speaks_the_line(self) -> None:
        prompt = compile_seedance_prompt(
            {"id": "SH001", "action": "速卡蹲在石槽前伸手摸凹痕", "setup": "master", "camera": "固定机位"},
            {"action_now": "速卡蹲在石槽前伸手摸凹痕", "move_detail": "固定机位", "shot_size": "中近景", "dialogue_line": "水往哪走，河床都替你记着。", "speaker": "速卡"},
        )
        self.assertIn("速卡用普通话说：“水往哪走，河床都替你记着。”", prompt)
        self.assertNotIn("对白不进画面", prompt)
        self.assertNotIn("不要", prompt.replace("不要字幕", ""))


class PackageCompile(unittest.TestCase):
    def test_packages_carry_speech_geo_descriptor_acting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = _prod(tmp)
            shots = [
                _shot("SH020", coverage_type="insert", scale="insert", body_facing="无人", one_action="她的手搭上虚掩柜门", in_from="柜门仍虚掩手尚未搭上", out_to="手搭在虚掩柜门上", dialogue_ref=[], key_sfx=["柜门吱呀"], acting=None),
                _shot("SH021"),
                _shot("SH051", scene_id="EP01_SC03", location_id="line-7", characters=["琳", "春安"], camera_side="front", one_action="春安把藏青布从车底拖出", in_from="手伸向底层布还没出来", out_to="布已离车底", dialogue_ref=[{"character": "春安", "track": "春安-口白", "line": "车底下塞的什么？"}], state={"characters": {"rin": {"costume": "cleaning"}, "chanthy": {"costume": "base"}}, "props": [], "note": "琳在画左"}, acting={"春安": {"muscle": "手臂一拽"}}),
                _shot("SH052", scene_id="EP01_SC03", location_id="line-7", characters=["春安"], camera_side="front", one_action="藏青布甩在地上", in_from="布已离车底", out_to="布落地铺开", dialogue_ref=[], state={"characters": {"chanthy": {"costume": "base"}}, "props": [], "note": "吊牌朝上"}, acting=None),
            ]
            table = _table(shots)
            data = compile_packages_from_specs(prod, "seedance_2_0", table=table, writer=WRITER)
            self.assertEqual(validate_packages(data, ASSETS, None), [])
            self.assertEqual(data["speech_mode"], "seedance_native")
            self.assertEqual(data["dialogue_language"], "zh")
            by_id = {pkg["shot_id"]: pkg for pkg in data["packages"]}
            self.assertEqual(len(by_id), 4)
            for pkg in by_id.values():
                self.assertEqual(pkg["speech_mode"], "seedance_native")
                self.assertEqual(pkg["dialogue_language"], "zh")
                self.assertTrue(pkg["audio_block"])
                self.assertTrue(pkg["generate_audio"])
                self.assertTrue(pkg["motion_prompt"].startswith(pkg["geo_layout"]))
                self.assertTrue(pkg["still_image_prompt"].startswith(pkg["geo_layout"]))
                self.assertIsNone(NEGATIVE_RE.search(re.sub(r"“[^”]*”", "", pkg["motion_prompt"])), pkg["shot_id"])
                self.assertEqual(pkg["motion_prompt_chars"], len(pkg["motion_prompt"]))
            # GEO identical inside a scene, from geo_zh; line-7 falls back to axis
            self.assertEqual(by_id["SH020"]["geo_layout"], by_id["SH021"]["geo_layout"])
            self.assertTrue(by_id["SH021"]["geo_layout"].startswith("【空间锁·杂物间】灰铁皮柜在画左约1.5米"))
            self.assertEqual(by_id["SH051"]["geo_layout"], by_id["SH052"]["geo_layout"])
            self.assertEqual(by_id["SH052"]["geo_layout"], "【空间锁·七线】琳在画左，春安在画右。")
            # speech: line in quotes with the verbatim card, mute shot closes mouths
            spoken = by_id["SH051"]
            self.assertEqual(spoken["dialogue_lines"], ["车底下塞的什么？"])
            self.assertEqual(spoken["voice_card"]["春安"], "三十出头女声，中低音，字咬得死，句尾往下砸。")
            self.assertIn("春安（三十出头女声，中低音，字咬得死，句尾往下砸）用普通话说：“车底下塞的什么？”", spoken["audio_block"])
            self.assertIn("琳不说话，嘴闭着。", spoken["audio_block"])
            self.assertIn("【声音】" + spoken["audio_block"], spoken["motion_prompt"])
            self.assertTrue(by_id["SH052"]["audio_block"].startswith("画中所有人不说话，嘴闭着。"))
            self.assertEqual(by_id["SH052"]["voice_card"], {})
            # descriptor follows the costume state; acting compiled; timing beats recorded
            self.assertTrue(any(d.startswith("琳：瘦小缩肩，发网") for d in by_id["SH021"]["descriptor"]))
            self.assertIn("【表演】琳：想看看里面；藏着手在抖；手搭柜门；一把拉开，眼跟着探进去；柜门从虚掩到全开。", by_id["SH021"]["motion_prompt"])
            self.assertIn("对方话没说完，琳的脸已经在答。", spoken["motion_prompt"])
            self.assertEqual(len(by_id["SH021"]["action_timing"]), 2)
            self.assertIn("0.0s 起就在动（首帧已起手：手已搭上柜内仍暗）", by_id["SH021"]["motion_prompt"])
            self.assertNotIn("夸张表情", by_id["SH021"]["still_image_prompt"])
            self.assertNotIn("对白不进画面", spoken["motion_prompt"])

    def test_km_table_is_rejected_with_first_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = _prod(tmp)
            table = _table([_shot("SH021")], dialogue_language="km")
            with self.assertRaises(SpeechLanguageError) as ctx:
                compile_packages_from_specs(prod, "seedance_2_0", table=table, writer=WRITER)
            self.assertIn("reference_audio", str(ctx.exception))

    def test_carry_video_ready_fields(self) -> None:
        previous = {
            "video_ready": True,
            "official_dest_dir": "05-shots/ep01-v2",
            "notes": "old",
            "packages": [
                {"shot_id": "SH001", "first_frame": "04-frames/ep01-v2/SH001.jpg", "last_frame": "04-frames/ep01-v2/SH001-last.jpg", "official_dest": "05-shots/ep01-v2/SH001.mp4", "motion_prompt": "old"},
                {"shot_id": "SH002", "first_frame": "04-frames/ep01-v2/SH002.jpg", "last_frame": ""},
            ],
        }
        fresh = {"packages": [{"shot_id": "SH001", "motion_prompt": "new"}, {"shot_id": "SH002", "motion_prompt": "new"}, {"shot_id": "SH003", "motion_prompt": "new"}]}
        carry_video_ready_fields(previous, fresh)
        by_id = {pkg["shot_id"]: pkg for pkg in fresh["packages"]}
        self.assertEqual(by_id["SH001"]["first_frame"], "04-frames/ep01-v2/SH001.jpg")
        self.assertEqual(by_id["SH001"]["last_frame"], "04-frames/ep01-v2/SH001-last.jpg")
        self.assertEqual(by_id["SH001"]["official_dest"], "05-shots/ep01-v2/SH001.mp4")
        self.assertEqual(by_id["SH001"]["motion_prompt"], "new")
        self.assertEqual(by_id["SH002"]["last_frame"], "")
        self.assertNotIn("first_frame", by_id["SH003"])
        self.assertTrue(fresh["video_ready"])
        self.assertEqual(fresh["official_dest_dir"], "05-shots/ep01-v2")


class RendererHandoff(unittest.TestCase):
    def test_plan_marks_native_speech_and_h3_line_loss(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            first = prod / "04-frames" / "ep01-v2" / "SH007.jpg"
            first.parent.mkdir(parents=True)
            Image.new("RGB", (64, 36)).save(first, format="JPEG")
            pkg = {
                "shot_id": "SH007",
                "gen_mode": "i2v_first",
                "keyframe_plan": "first",
                "confirmed": True,
                "motion_prompt": "【声音】春安用普通话说：“去把后面那间扫了。”",
                "render_duration_sec": 4,
                "asset_refs": [],
                "speech_mode": "seedance_native",
                "dialogue_language": "zh",
                "dialogue_lines": ["去把后面那间扫了。"],
            }
            frames = {"SH007": {"shot_id": "SH007", "first_frame_file": "04-frames/ep01-v2/SH007.jpg", "qc": {"status": "pass"}}}
            planned = plan_shot(prod, pkg, frames, {}, episode="ep01-v2")
            self.assertTrue(planned["ok"], planned["errors"])
            self.assertTrue(planned["native_speech"])
            self.assertTrue(planned["loses_lines_on_h3"])
            self.assertEqual(planned["prompt_chars"], len(pkg["motion_prompt"]))
            mute = plan_shot(prod, dict(pkg, dialogue_lines=[], dialogue_line=""), frames, {}, episode="ep01-v2")
            self.assertFalse(mute["loses_lines_on_h3"])
            khmer = plan_shot(prod, dict(pkg, dialogue_language="km"), frames, {}, episode="ep01-v2")
            self.assertFalse(khmer["ok"])
            self.assertTrue(any("reference_audio" in err for err in khmer["errors"]))
            plan = {
                "prod": "productions/demo",
                "episode": "ep01-v2",
                "episode_label": "ep01-v2",
                "dest_dir": "05-shots/ep01-v2",
                "count": 2,
                "ok_count": 2,
                "first_last_count": 0,
                "hardest": [],
                "native_speech_count": 1,
                "h3_line_loss": ["SH007"],
                "max_prompt_chars": planned["prompt_chars"],
                "shots": [planned, mute],
            }
            (prod / "03-storyboard").mkdir()
            dest = write_markdown(prod, plan)
            text = dest.read_text(encoding="utf-8")
            self.assertIn("Seedance 原声中文唇同步", text)
            self.assertIn("H3 fallback 不会有原声对白", text)
            self.assertIn("SH007", text.split("H3 fallback 不会有原声对白")[1].split("\n")[0])
            self.assertIn("| ★ 去把后面那间扫了。 |", text)
            self.assertIn("07-dubbing/sfx/ep01-sfx.m4a", text)
            self.assertIn("首帧 = 动作起点", text)
            self.assertNotIn("motion 从 one_action 之后才动", text)


class Reconcile(unittest.TestCase):
    """Docs ↔ code alignment: 7a acting lays over the table row, adjective scan covers the description
    text, dialogue_delivery drives the per-shot speech mode."""

    def test_7a_acting_overrides_table_field_by_field(self) -> None:
        table = {"琳": {"want": "看看里面", "muscle": "一把拉开", "business": "手搭柜门"}}
        over = {"琳": {"muscle": "手停在柜门上半秒再拉", "business": ""}}
        merged = merge_acting(table, over)
        self.assertEqual(merged["琳"]["muscle"], "手停在柜门上半秒再拉")
        self.assertEqual(merged["琳"]["business"], "手搭柜门")  # empty 7a field keeps the table
        self.assertEqual(merged["琳"]["want"], "看看里面")
        lines = compile_acting_zh(
            {"acting": table, "scale": "medium", "body_facing": "四分之三"}, in_frame=["琳"], override=over
        )
        self.assertTrue(any("手停在柜门上半秒再拉" in line for line in lines))
        self.assertFalse(any("一把拉开" in line for line in lines))
        self.assertEqual(normalize_item({"shot_id": "SH021", "acting": over})["acting"], {"琳": {
            "want": "", "hide": "", "business": "", "muscle": "手停在柜门上半秒再拉", "change": ""}})

    def test_frame_description_adjectives_warn_not_error(self) -> None:
        items = [
            {"shot_id": "SH030", "one_paragraph": "波帕冷笑着逼近，嘴角往下。", "subject": {"micro_expression": "眼皮压下来"}},
            {"shot_id": "SH031", "one_paragraph": "波帕跨一步逼近，嘴角往下。", "still_start": {"pose": "身前倾"}},
            {"shot_id": "SH032", "acting": {"春安": {"muscle": "横着脸把钥匙举到胸口"}}},
        ]
        warnings = frame_description_warnings({"items": items})
        self.assertEqual(len(warnings), 2)
        self.assertIn("SH030 acting_adjective 「冷笑」 in one_paragraph", warnings[0])
        self.assertIn("SH032 acting_adjective 「横」 in acting.春安.muscle", warnings[1])

    def test_sanitize_defaults_delivery_from_table_speech_mode(self) -> None:
        native = _table([_shot("SH021", dialogue_delivery="")], speech_mode="seedance_native")
        self.assertEqual(native["shots"][0]["dialogue_delivery"], "on_camera")
        # undeclared table on a lip-sync model defaults native too
        implied = _table([_shot("SH021", dialogue_delivery="")])
        self.assertEqual(implied["shots"][0]["dialogue_delivery"], "on_camera")
        dubbed = _table([_shot("SH021", dialogue_delivery="")], speech_mode="post_dub")
        self.assertEqual(dubbed["shots"][0]["dialogue_delivery"], "post")
        h3 = _table([_shot("SH021", dialogue_delivery="")], target_model="minimax_h3")
        self.assertEqual(h3["shots"][0]["dialogue_delivery"], "post")
        # an undeclared all-`post` table is a post-dub table: no opt-out warning, no native lines
        from director.speech import speech_mode_for
        from director.video_profiles import get_profile
        legacy = _table([_shot("SH021", dialogue_delivery="post"), _shot("SH020", dialogue_ref=[], dialogue_delivery="")])
        self.assertEqual(speech_mode_for(legacy, get_profile("seedance_2_0")), "post_dub")
        self.assertEqual(speech_mode_for(native, get_profile("seedance_2_0")), "seedance_native")
        mute = _table([_shot("SH020", dialogue_ref=[], dialogue_delivery="")], speech_mode="seedance_native")
        self.assertEqual(mute["shots"][0]["dialogue_delivery"], "none")

    def test_post_shot_opts_out_of_native_speech(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = _prod(tmp)
            table = _table([_shot("SH021"), _shot("SH022", dialogue_delivery="post", in_from="手已搭上柜门", out_to="柜门全开")])
            data = compile_packages_from_specs(prod, "seedance_2_0", table=table, writer=WRITER)
            by_id = {pkg["shot_id"]: pkg for pkg in data["packages"]}
            self.assertEqual(data["speech_mode"], "seedance_native")
            self.assertEqual(by_id["SH021"]["speech_mode"], "seedance_native")
            self.assertEqual(by_id["SH021"]["dialogue_delivery"], "on_camera")
            self.assertIn("“这柜门还虚掩着？”", by_id["SH021"]["audio_block"])
            self.assertEqual(by_id["SH022"]["speech_mode"], "post_dub")
            self.assertEqual(by_id["SH022"]["dialogue_delivery"], "post")
            self.assertTrue(by_id["SH022"]["audio_block"].startswith("画中所有人不说话，嘴闭着。"))
            self.assertNotIn("这柜门还虚掩着", by_id["SH022"]["motion_prompt"])
            self.assertTrue(any("dialogue_delivery=post under speech_mode=seedance_native" in w and "SH022" in w for w in data.get("warnings", [])))


if __name__ == "__main__":
    unittest.main()
