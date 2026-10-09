#!/usr/bin/env python3
"""Dialogue gate (台词关 L): AI-tell lint, Khmer timing, Gemini fill, shot stamping, proposals, gate rail."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.agents import LOCKABLE, UPSTREAM, previous_satisfied, virtual_locked  # noqa: E402
from director.lines import (  # noqa: E402
    apply_revisions,
    build_lines,
    fill_khmer,
    human_signer,
    khmer_prompt,
    khmer_seconds,
    lint_km,
    lint_zh,
    parse_json_reply,
    retime_shots,
    review_errors,
    shot_fit,
    stamp_line_timing,
    timing_stamp_errors,
    validate_lines,
    writer_digest,
    writer_rows,
)
from director.shot_table import dialogue_seconds, needed_seconds, writer_dialogue_records  # noqa: E402
from director.speech import parse_character_cards  # noqa: E402

KM_A = "កាប់វាចោល"  # 5 Khmer letters (U+1780–U+17B3); vowel signs do not count
KM_B = "បង ខ្ញុំឃ្លានហើយ"


def writer_fixture() -> dict:
    return {
        "series_bible": {
            "logline": "穿越回 1549 年的学生",
            "characters": [{"id": "dara", "name": "达拉"}, {"id": "kosal", "name": "果萨"}, {"id": "yeay-kim", "name": "金奶奶"}],
        },
        "scenes": [
            {
                "scene_id": "EP01_SC01",
                "heading": "外 工地 日",
                "captions": [{"kind": "intro", "character": "dara", "text": "达拉 · 考古系"}],
                "key_sounds": ["铲子声"],
                "dialogue": [
                    {"character": "yeay-kim", "speaker": "yeay-kim", "line": "孩子，奶奶请阿查给你念了经。手上那根线别摘，啊？", "line_kind": "dialogue", "parenthetical": "电话里"},
                    {"character": "dara", "speaker": "dara", "line": "奶奶，克良蒙是传说。", "line_kind": "dialogue"},
                ],
            },
            {
                "scene_id": "EP01_SC02",
                "heading": "外 营地 夜",
                "dialogue": [
                    {"character": "kosal", "speaker": "kosal", "line": "你叫什么？", "line_kind": "dialogue"},
                    {"character": "kosal", "speaker": "kosal", "line": "你最好是对的。", "line_kind": "dialogue"},
                ],
            },
        ],
    }


def table_fixture() -> dict:
    return {
        "schema": "shot-table-v2",
        "shots": [
            {"shot_id": "SH001", "scene_id": "EP01_SC01", "duration_sec": 6, "coverage_type": "close", "dialogue_delivery": "post",
             "dialogue_ref": [{"character": "yeay-kim", "line": "孩子，奶奶请阿查给你念了经。"}]},
            {"shot_id": "SH002", "scene_id": "EP01_SC01", "duration_sec": 3, "coverage_type": "insert", "dialogue_delivery": "post",
             "dialogue_ref": [{"character": "yeay-kim", "line": "手上那根线别摘，啊？"}]},
            {"shot_id": "SH003", "scene_id": "EP01_SC01", "duration_sec": 3.5, "coverage_type": "close", "dialogue_delivery": "on_camera",
             "dialogue_ref": [{"character": "dara", "line": "奶奶，克良蒙是传说。"}]},
            {"shot_id": "SH004", "scene_id": "EP01_SC02", "duration_sec": 2.5, "coverage_type": "close", "dialogue_delivery": "none",
             "one_action": "达拉盯着溪水", "dialogue_ref": []},
            {"shot_id": "SH005", "scene_id": "EP01_SC02", "duration_sec": 2.5, "coverage_type": "close", "dialogue_delivery": "on_camera",
             "dialogue_ref": [{"character": "kosal", "line": "你叫什么？"}]},
            {"shot_id": "SH006", "scene_id": "EP01_SC02", "duration_sec": 2.5, "coverage_type": "close", "dialogue_delivery": "on_camera",
             "dialogue_ref": [{"character": "kosal", "line": "你最好是对的。"}]},
        ],
    }


def fake_gemini(long_ids: tuple[str, ...] = ()) -> callable:
    """Answers every requested row with aligned units; `long_ids` get a long Khmer line."""

    def run(prompt: str) -> str:
        rows = [json.loads(line) for line in prompt.splitlines() if line.startswith("{\"id\"")]
        out = []
        for row in rows:
            km = (KM_B * 6) if row["id"] in long_ids else KM_A
            if row.get("kind") == "caption":
                km = "តារា · និស្សិត"
            out.append({"id": row["id"], "units": [{"km": km, "back_zh": "回译" + piece[:2]} for piece in row["units"]], "note_zh": ""})
        return json.dumps({"lines": out}, ensure_ascii=False)

    return run


class LintTests(unittest.TestCase):
    def test_not_x_but_y_flagged_but_either_or_is_speech(self) -> None:
        codes = {f["code"] for f in lint_zh("不是糖水。是烧开的水。")}
        self.assertIn("不是X是Y", codes)
        self.assertNotIn("不是X是Y", {f["code"] for f in lint_zh("不是暹罗探子，就是鬼。")})
        self.assertNotIn("格言等式", {f["code"] for f in lint_zh("不是暹罗探子，就是鬼。")})

    def test_maxim_calque_triple_long_number(self) -> None:
        self.assertIn("格言等式", {f["code"] for f in lint_zh("大人说了，浪费柴火，就是浪费军粮。")})
        self.assertNotIn("格言等式", {f["code"] for f in lint_zh("医院里吊的盐水，就是这个。")})
        self.assertIn("翻译腔", {f["code"] for f in lint_zh("你最好是对的。")})
        self.assertIn("三连排比", {f["code"] for f in lint_zh("给我一口锅、一撮盐、一块糖棕糖。")})
        # a long line with pauses is speech; only a clause with no breath in it is flagged
        self.assertNotIn("一口气", {f["code"] for f in lint_zh("孩子，奶奶请阿查在克良蒙爷爷像前给你念了经，你千万记得。")})
        self.assertIn("一口气", {f["code"] for f in lint_zh("奶奶请阿查在克良蒙爷爷像前给你念了整整一个下午的经文")})
        self.assertIn("数字", {f["code"] for f in lint_zh("一五四九……暹粒之战。")})
        self.assertEqual(lint_zh("给他锅。"), [])
        self.assertEqual(lint_zh("哥，我饿了。"), [])

    def test_telegram_scene_warns(self) -> None:
        from director.lines import rhythm_warnings

        rows = [{"line_id": f"EP01_SC03:d0{i}", "kind": "dialogue", "zh": t} for i, t in
                enumerate(["你叫什么？", "达拉。", "砍了。", "上游全是坟，你们营里的人是不是一个接一个倒下了？"], start=1)]
        self.assertTrue(any("像打电报" in w for w in rhythm_warnings(rows)))
        rows[1]["zh"] = "我叫达拉，大人，菩萨省来的。"
        rows[2]["zh"] = "要是你说错了一个字，我亲手砍了你。"
        self.assertEqual(rhythm_warnings(rows), [])

    def test_khmer_lint(self) -> None:
        self.assertEqual(lint_km("", "dialogue")[0]["level"], "error")
        self.assertEqual(lint_km("ឆ្នាំ 1549", "dialogue")[0]["level"], "error")
        self.assertEqual(lint_km("ឆ្នាំ ១៥៤៩", "dialogue")[0]["level"], "error")
        self.assertEqual(lint_km("១៥៤៩ · សៀមរាប", "caption"), [])
        self.assertEqual(lint_km("អ្នកតា 达拉", "dialogue")[0]["code"], "混汉字")
        self.assertEqual(lint_km("neak ta អ្នកតា", "dialogue")[0]["level"], "warn")

    def test_human_signer(self) -> None:
        self.assertTrue(human_signer("Tony"))
        for name in ("", "Claude", "opus-5.5", "Gemini", "AI", "codex agent"):
            self.assertFalse(human_signer(name), name)


class TimingTests(unittest.TestCase):
    def test_khmer_seconds_calibrated(self) -> None:
        self.assertEqual(khmer_seconds(KM_A, "dialogue"), round(5 / 6.0 + 0.4, 1))
        self.assertLess(khmer_seconds(KM_A * 4, "narration"), khmer_seconds(KM_A * 4, "dialogue"))
        self.assertEqual(khmer_seconds("", "dialogue"), 0.0)
        # dialogue_seconds' Khmer branch uses the same calibrated rate (it used to overestimate by ~60%).
        self.assertEqual(dialogue_seconds([KM_A]), round(5 / 6.0 + 0.4, 1))

    def test_needed_seconds_holds_the_longer_language(self) -> None:
        shot = {"coverage_type": "close", "dialogue_ref": [{"line": "砍了。"}]}
        zh_only = needed_seconds(shot)
        self.assertEqual(needed_seconds({**shot, "dialogue_ref": [{"line": "砍了。", "km_sec": 0.5}]}), zh_only)
        self.assertEqual(needed_seconds({**shot, "dialogue_ref": [{"line": "砍了。", "km_sec": 4.0}]}), 4.4)


class BuildTests(unittest.TestCase):
    def test_rows_match_writer_ids_and_include_captions(self) -> None:
        writer = writer_fixture()
        rows = writer_rows(writer)
        dialogue_ids = [r["line_id"] for rows_ in writer_dialogue_records(writer).values() for r in rows_]
        self.assertEqual([r["line_id"] for r in rows if r["kind"] != "caption"], dialogue_ids)
        self.assertIn("EP01_SC01:c01", [r["line_id"] for r in rows])
        data = build_lines(writer)
        first = data["lines"][0]
        self.assertEqual([u["zh"] for u in first["units"]], ["孩子，奶奶请阿查给你念了经。", "手上那根线别摘，啊？"])
        self.assertEqual(data["writer_digest"], writer_digest(writer))

    def test_fill_khmer_and_cache(self) -> None:
        writer = writer_fixture()
        data = build_lines(writer)
        missing = fill_khmer(data, writer=writer, runner=fake_gemini())
        self.assertEqual(missing, [])
        self.assertTrue(all(r["km_key"] for r in data["lines"]))
        errors, _warnings = validate_lines(build_lines(writer, previous=data), writer)
        self.assertEqual(errors, [])
        # Same writer: Khmer survives a rebuild. Changed line: that row's Khmer is dropped.
        again = build_lines(writer, previous=data)
        self.assertEqual(again["lines"][1]["units"][0]["km"], KM_A)
        changed = copy.deepcopy(writer)
        changed["scenes"][0]["dialogue"][1]["line"] = "奶奶，那是传说。"
        rebuilt = build_lines(changed, previous=data)
        self.assertEqual(rebuilt["lines"][1]["units"][0]["km"], "")
        self.assertEqual(rebuilt["lines"][0]["units"][0]["km"], KM_A)
        errors, _ = validate_lines(data, changed)
        self.assertTrue(any("剧本改过" in e for e in errors))

    def test_fill_khmer_retries_bad_alignment(self) -> None:
        writer = writer_fixture()
        data = build_lines(writer)
        calls = []

        def misaligned(prompt: str) -> str:
            calls.append(prompt)
            rows = [json.loads(line) for line in prompt.splitlines() if line.startswith("{\"id\"")]
            return json.dumps({"lines": [{"id": r["id"], "units": [{"km": KM_A, "back_zh": "x"}]} for r in rows]})

        missing = fill_khmer(data, writer=writer, runner=misaligned)
        self.assertEqual(missing, ["EP01_SC01:d01"])
        self.assertEqual(len(calls), 2)

    def test_prompt_carries_listener_names_and_units(self) -> None:
        writer = writer_fixture()
        writer["scenes"][1]["dialogue"][1]["to"] = "dara"
        cards = {"kosal": {"name": "果萨", "km_name": "កុសល", "speech_style": "短句，对下用 ឯង"}, "dara": {"name": "达拉", "km_name": "ដារ៉ា"}}
        data = build_lines(writer)
        prompt = khmer_prompt(data["lines"], writer=writer, cards=cards, glossary=[{"zh": "暹粒", "km": "សៀមរាប"}])
        self.assertIn("果萨 = កុសល", prompt)
        self.assertIn("暹粒 = សៀមរាប", prompt)
        self.assertIn("说话方式：短句，对下用 ឯង", prompt)
        self.assertIn('"to": "dara"', prompt)
        self.assertIn("不要使用任何工具", prompt)
        self.assertEqual(parse_json_reply('```json\n{"lines": []}\n```'), {"lines": []})

    def test_review_needs_human(self) -> None:
        data = {"status": "reviewed", "reviewed_by": "Claude"}
        self.assertTrue(review_errors(data))
        self.assertEqual(review_errors({"status": "reviewed", "reviewed_by": "Tony"}), [])


class ShotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.writer = writer_fixture()
        self.table = table_fixture()
        self.data = build_lines(self.writer, table=self.table)
        fill_khmer(self.data, writer=self.writer, runner=fake_gemini(long_ids=("EP01_SC02:d02",)))

    def test_split_line_stamps_per_shot(self) -> None:
        touched = stamp_line_timing(self.table, self.data)
        self.assertIn("SH001", touched)
        refs = {s["shot_id"]: s["dialogue_ref"] for s in self.table["shots"]}
        self.assertEqual(refs["SH001"][0]["line_id"], "EP01_SC01:d01")
        self.assertEqual(refs["SH002"][0]["km_sec"], khmer_seconds(KM_A))
        self.assertEqual(timing_stamp_errors(self.table, self.data), [])
        self.table["shots"][2]["dialogue_ref"][0]["km_sec"] = 9.9
        self.assertTrue(any("SH003" in e for e in timing_stamp_errors(self.table, self.data)))
        self.table["shots"][3]["dialogue_ref"] = [{"line": "剧本里没有这句。"}]
        self.assertTrue(any("not in the dialogue gate" in e for e in timing_stamp_errors(self.table, self.data)))

    def test_long_khmer_overflows_and_retime_fixes(self) -> None:
        fit = {f["shot_id"]: f for f in shot_fit(self.table, self.data)}
        self.assertFalse(fit["SH006"]["fits"])
        self.assertTrue(fit["SH005"]["fits"])
        log = retime_shots(self.table, self.data)
        self.assertTrue(any(line.startswith("SH006") for line in log))
        fit = {f["shot_id"]: f for f in shot_fit(self.table, self.data)}
        self.assertTrue(fit["SH006"]["fits"])

    def test_proposals_block_lock_then_apply(self) -> None:
        rows = {r["line_id"]: r for r in self.data["lines"]}
        rows["EP01_SC02:d02"]["zh_new"] = "错了，我砍你。"
        rows["EP01_SC02:d02"]["why"] = "英语直译"
        rows["EP01_SC01:d02"]["kind_new"] = "inner"
        self.data["lines"].insert(3, {
            "line_id": "EP01_SC02:n01", "scene_id": "EP01_SC02", "add": True, "after": "", "shot_id": "SH004",
            "kind": "inner", "speaker": "dara", "zh_new": "坟……水……", "why": "补上他想通的那一下",
        })
        data = build_lines(self.writer, previous=self.data, table=self.table)
        fill_khmer(data, writer=self.writer, runner=fake_gemini())
        errors, _ = validate_lines(data, self.writer, self.table)
        self.assertTrue(any("改稿还没写回剧本" in e for e in errors))
        fit = {f["shot_id"]: f for f in shot_fit(self.table, data)}
        self.assertEqual(fit["SH004"]["delivery_after"], "inner")
        self.assertEqual(fit["SH003"]["delivery_after"], "inner")  # d02 became a monologue: voiced, mouth closed
        log = apply_revisions(self.writer, data, self.table)
        self.assertTrue(log)
        lines = {d["line_id"]: d for s in self.writer["scenes"] for d in s["dialogue"]}
        self.assertEqual(lines["EP01_SC02:d02"]["line"], "错了，我砍你。")
        self.assertEqual(lines["EP01_SC01:d02"]["line_kind"], "inner")
        self.assertEqual(self.writer["scenes"][1]["dialogue"][0]["line_id"], "EP01_SC02:n01")
        shots = {s["shot_id"]: s for s in self.table["shots"]}
        self.assertEqual(shots["SH006"]["dialogue_ref"][0]["line"], "错了，我砍你。")
        self.assertEqual(shots["SH004"]["dialogue_ref"][0]["line_id"], "EP01_SC02:n01")
        self.assertEqual(shots["SH004"]["dialogue_delivery"], "inner")  # voiced as a monologue, not dubbed later
        self.assertEqual(shots["SH003"]["dialogue_delivery"], "inner")
        errors, _ = validate_lines(data, self.writer, self.table)
        self.assertEqual(errors, [])
        self.assertEqual(timing_stamp_errors(self.table, data), [])

    def test_lip_gap_flags_on_camera_only_and_tighten_keeps_shorter(self) -> None:
        from director.lines import refresh, tighten_khmer, tighten_targets

        refresh(self.data, self.table)
        targets = tighten_targets(self.data, self.table)
        self.assertIn("EP01_SC02:d02", targets)  # long Khmer, on camera
        self.assertNotIn("EP01_SC01:d01", targets)  # grandma is on the phone (post)
        _errors, warnings = validate_lines(self.data, self.writer, self.table)
        self.assertTrue(any("对口型" in w for w in warnings))

        def shorter(prompt: str) -> str:
            rows = [json.loads(line) for line in prompt.splitlines() if line.startswith("{\"id\"")]
            self.assertTrue(all("target_sec" in r and "current_km" in r for r in rows))
            return json.dumps({"lines": [{"id": r["id"], "units": [{"km": KM_A, "back_zh": "短"} for _ in r["units"]]} for r in rows]})

        result = tighten_khmer(self.data, targets, writer=self.writer, runner=shorter)
        before, after = result["EP01_SC02:d02"]
        self.assertLess(after, before)
        refresh(self.data, self.table)
        self.assertNotIn("EP01_SC02:d02", tighten_targets(self.data, self.table))

        def longer(prompt: str) -> str:
            rows = [json.loads(line) for line in prompt.splitlines() if line.startswith("{\"id\"")]
            return json.dumps({"lines": [{"id": r["id"], "units": [{"km": KM_B * 9, "back_zh": "长"} for _ in r["units"]]} for r in rows]})

        kept = self.data["lines"][-1]["units"][0]["km"]
        tighten_khmer(self.data, {self.data["lines"][-1]["line_id"]: 0.5}, writer=self.writer, runner=longer)
        self.assertEqual(self.data["lines"][-1]["units"][0]["km"], kept)

    def test_chinese_follows_khmer_keeps_khmer_on_rebuild(self) -> None:
        from director.lines import refresh, sync_chinese

        refresh(self.data, self.table)
        lid = "EP01_SC02:d02"
        km_before = [u["km"] for u in self.data["lines"][-1]["units"]] if self.data["lines"][-1]["line_id"] == lid else None

        def chinese(prompt: str) -> str:
            rows = [json.loads(line) for line in prompt.splitlines() if line.startswith("{\"id\"")]
            self.assertTrue(all("zh_chars" in u for r in rows for u in r["units"]))
            return json.dumps({"lines": [{"id": r["id"], "units": [{"zh": "你最好给我说对了，听见没有？"}]} for r in rows]}, ensure_ascii=False)

        changed = sync_chinese(self.data, [lid], writer=self.writer, runner=chinese)
        self.assertIn(lid, changed)
        row = next(r for r in self.data["lines"] if r["line_id"] == lid)
        self.assertEqual(row["zh_new_split"], ["你最好给我说对了，听见没有？"])
        rebuilt = build_lines(self.writer, previous=self.data, table=self.table)
        again = next(r for r in rebuilt["lines"] if r["line_id"] == lid)
        self.assertEqual([u["km"] for u in again["units"]], [u["km"] for u in row["units"]])
        self.assertTrue(again["km_key"])
        if km_before is not None:
            self.assertEqual([u["km"] for u in again["units"]], km_before)

    def test_caption_reword_applies_to_writer(self) -> None:
        rows = {r["line_id"]: r for r in self.data["lines"]}
        rows["EP01_SC01:c01"]["zh_new"] = "达拉 · 考古系大四学生"
        data = build_lines(self.writer, previous=self.data, table=self.table)
        fill_khmer(data, writer=self.writer, runner=fake_gemini())
        apply_revisions(self.writer, data, self.table)
        self.assertEqual(self.writer["scenes"][0]["captions"][0]["text"], "达拉 · 考古系大四学生")
        self.assertEqual(self.writer["scenes"][0]["captions"][0]["character"], "dara")
        self.assertEqual(validate_lines(data, self.writer, self.table)[0], [])

    def test_drop_removes_line_from_writer_and_shot(self) -> None:
        rows = {r["line_id"]: r for r in self.data["lines"]}
        rows["EP01_SC02:d01"]["drop"] = True
        apply_revisions(self.writer, self.data, self.table)
        self.assertNotIn("你叫什么？", [d["line"] for d in self.writer["scenes"][1]["dialogue"]])
        shot = next(s for s in self.table["shots"] if s["shot_id"] == "SH005")
        self.assertEqual(shot["dialogue_ref"], [])
        self.assertEqual(shot["dialogue_delivery"], "none")


class RailTests(unittest.TestCase):
    def test_gate_order(self) -> None:
        self.assertEqual(LOCKABLE[:3], ["0", "A", "L"])
        self.assertEqual(UPSTREAM["L"], ["A"])
        self.assertIn("L", UPSTREAM["C"])

    def test_storyboard_waits_for_dialogue_gate_once_it_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "999-lines"
            (prod / ".pipeline").mkdir(parents=True)
            (prod / ".pipeline" / "writer.json").write_text(json.dumps(writer_fixture(), ensure_ascii=False), encoding="utf-8")
            approvals = {"gates": {"A": {"locked": True}, "S": {"locked": True}, "B": {"locked": True}}}
            self.assertTrue(virtual_locked(prod, "L", {}, approvals))
            self.assertTrue(previous_satisfied(prod, "C", {}, approvals))
            (prod / ".pipeline" / "lines.json").write_text(json.dumps(build_lines(writer_fixture()), ensure_ascii=False), encoding="utf-8")
            self.assertFalse(virtual_locked(prod, "L", {}, approvals))
            self.assertFalse(previous_satisfied(prod, "C", {}, approvals))
            approvals["gates"]["L"] = {"locked": True}
            self.assertTrue(previous_satisfied(prod, "C", {}, approvals))


class CardTests(unittest.TestCase):
    def test_speech_style_and_khmer_name(self) -> None:
        text = """## **kosal** · 果萨 / Kosal

- **身份**：前线营队长
- **声音卡**：低沉粗哑
- **说话方式**：短句；对下叫 ឯង
- **高棉名**：កុសល
- **外形卡**：高大结实的高棉男子
"""
        card = parse_character_cards(text)["kosal"]
        self.assertEqual(card["speech_style"], "短句；对下叫 ឯង")
        self.assertEqual(card["km_name"], "កុសល")
        self.assertEqual(card["identity"], "前线营队长")
        self.assertEqual(card["voice_card"], "低沉粗哑")
        self.assertEqual(card["descriptor"], "高大结实的高棉男子")


if __name__ == "__main__":
    unittest.main()
