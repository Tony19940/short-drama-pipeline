#!/usr/bin/env python3
"""Name cards: placement rules, dialogue-gate text, keyframe space note, cut timing, ffmpeg overlay."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.lines import writer_rows  # noqa: E402
from director.name_cards import (  # noqa: E402
    card_texts,
    coretext_binary,
    ffmpeg_overlay_args,
    normalize_card,
    overlay_plan,
    place_texts,
    render_card,
    shot_starts,
    space_note_zh,
    validate_name_cards,
)


def lines_fixture(km: str = "តារា · និស្សិតបុរាណវិទ្យា") -> dict:
    return {"lines": [
        {"line_id": "EP01_SC01:c01", "kind": "caption", "caption_kind": "intro", "speaker": "dara", "zh": "达拉 · 考古系大四学生", "km": km},
        {"line_id": "EP01_SC01:c02", "kind": "caption", "caption_kind": "place_time", "speaker": "", "zh": "1549 · 吴哥以南", "km": "១៥៤៩"},
    ]}


def shot(sid: str, duration: float, card: dict | None = None, who: tuple[str, ...] = ("dara",)) -> dict:
    item = {"shot_id": sid, "duration_sec": duration, "state": {"characters": {c: {"in_frame": True} for c in who}}}
    if card is not None:
        item["name_card"] = card
    return item


class PlacementTests(unittest.TestCase):
    def test_defaults_fit_short_shots(self) -> None:
        card = normalize_card({"character": "dara", "side": "left"}, {"duration_sec": 2.0})
        self.assertEqual(card["x"], 0.05)
        self.assertEqual(card["hold_sec"], 1.7)
        self.assertEqual(normalize_card({"character": "dara"}, {"duration_sec": 6})["hold_sec"], 2.5)

    def test_clean_card_passes(self) -> None:
        table = {"shots": [shot("SH004", 6, {"character": "dara", "side": "left", "y": 0.58})]}
        self.assertEqual(validate_name_cards(table, lines_fixture()), ([], []))

    def test_rules(self) -> None:
        table = {"shots": [
            shot("SH001", 2, {"character": "dara", "side": "middle", "y": 0.9, "hold_sec": 5}),
            shot("SH002", 6, {"character": "vibol"}, who=("dara",)),
            shot("SH003", 6, {"character": "dara", "y": 0.2}),
        ]}
        errors, warnings = validate_name_cards(table, lines_fixture())
        blob = "\n".join(errors)
        self.assertIn("SH001 name_card side", blob)
        self.assertIn("SH001 name_card y 0.9", blob)
        self.assertIn("SH001 name_card holds 5.0s", blob)
        self.assertIn("past the 2.0s shot", blob)
        self.assertIn("SH002 name_card for vibol, who is not in frame", blob)
        self.assertIn("SH002 name_card for vibol has no intro caption", blob)
        self.assertTrue(any("second name card for dara" in w for w in warnings))

    def test_khmer_must_read_name_and_role(self) -> None:
        table = {"shots": [shot("SH004", 6, {"character": "dara"})]}
        errors, _ = validate_name_cards(table, lines_fixture(km="តារា"))
        self.assertTrue(any("name · role" in e for e in errors))

    def test_unplaced_card_warns(self) -> None:
        _errors, warnings = validate_name_cards({"shots": [shot("SH004", 6)]}, lines_fixture())
        self.assertTrue(any("not placed on any shot" in w for w in warnings))

    def test_texts_split_name_and_role(self) -> None:
        text = card_texts(lines_fixture())["dara"]
        self.assertEqual((text["name_km"], text["role_km"]), ("តារា", "និស្សិតបុរាណវិទ្យា"))
        self.assertNotIn("", card_texts(lines_fixture()))

    def test_writer_caption_names_its_person(self) -> None:
        writer = {"scenes": [{"scene_id": "EP01_SC01", "captions": [{"kind": "intro", "character": "dara", "text": "达拉 · 考古系"}]}]}
        row = writer_rows(writer)[0]
        self.assertEqual((row["kind"], row["caption_kind"], row["speaker"]), ("caption", "intro", "dara"))

    def test_keyframe_prompt_leaves_room_and_no_text(self) -> None:
        note = space_note_zh({"duration_sec": 6, "name_card": {"character": "dara", "side": "left", "y": 0.58}})
        self.assertIn("画面左侧", note)
        self.assertIn("画面里不写任何字", note)
        self.assertEqual(space_note_zh({"duration_sec": 6}), "")


class PlaceCardTests(unittest.TestCase):
    def table(self, *cards) -> dict:
        shots = []
        for index, card in enumerate(cards, start=1):
            item = shot(f"SH{index:03d}", 4)
            item["scene_id"] = "EP01_SC01"
            if card is not None:
                item["place_card"] = card
            shots.append(item)
        return {"shots": shots}

    def test_text_splits_time_and_place(self) -> None:
        lines = lines_fixture()
        lines["lines"][1]["km"] = "១៥៤៩ · ខាងត្បូងអង្គរ"
        text = place_texts(lines)["EP01_SC01"]
        self.assertEqual((text["line1_km"], text["line2_km"], text["zh"]), ("១៥៤៩", "ខាងត្បូងអង្គរ", "1549 · 吴哥以南"))

    def test_placement_rules(self) -> None:
        errors, warnings = validate_name_cards(self.table({"side": "left", "y": 0.08}), lines_fixture())
        self.assertEqual(errors, [])
        self.assertFalse(any("place/time card" in w for w in warnings))
        _errors, warnings = validate_name_cards(self.table(None), lines_fixture())
        self.assertTrue(any("place/time card 「1549 · 吴哥以南」 is not placed" in w for w in warnings), warnings)
        errors, _ = validate_name_cards(self.table({"side": "left"}, {"side": "right"}), lines_fixture())
        self.assertTrue(any("second place_card for scene EP01_SC01" in e for e in errors), errors)
        no_caption = {"lines": [lines_fixture()["lines"][0]]}
        errors, _ = validate_name_cards(self.table({"side": "left"}), no_caption)
        self.assertTrue(any("has no place_time caption" in e for e in errors), errors)
        both = self.table({"side": "left", "y": 0.5})
        both["shots"][0]["name_card"] = {"character": "dara", "side": "left", "y": 0.58}
        errors, _ = validate_name_cards(both, lines_fixture())
        self.assertTrue(any("overlap" in e for e in errors), errors)

    def test_keyframe_note_and_cut_plan(self) -> None:
        item = {"duration_sec": 4, "place_card": {"side": "left", "y": 0.08}}
        self.assertIn("画面左侧上方留一块干净的空白（天空、墙面或暗部），后期在那里叠地点时间卡", space_note_zh(item))
        table = self.table({"side": "left", "start_sec": 0.3, "hold_sec": 2.6})
        plan = overlay_plan(table, {"timeline": [{"shot_id": "SH001", "output_duration_sec": 4}]})
        self.assertEqual((plan[0]["kind"], plan[0]["scene_id"], plan[0]["t0"], plan[0]["t1"]), ("place", "EP01_SC01", 0.3, 2.9))


class CutTests(unittest.TestCase):
    def test_times_follow_the_cut(self) -> None:
        cut = {"timeline": [
            {"shot_id": "SH001", "output_duration_sec": 2.0},
            {"shot_id": "SH002", "in_sec": 0.5, "out_sec": 3.5, "speed": 1.5},
            {"shot_id": "SH004", "output_duration_sec": 6.0},
        ]}
        self.assertEqual(shot_starts(cut), {"SH001": 0.0, "SH002": 2.0, "SH004": 4.0})
        table = {"shots": [
            shot("SH003", 3, {"character": "dara"}),
            shot("SH004", 6, {"character": "dara", "start_sec": 0.5, "hold_sec": 2.5}),
        ]}
        plan = overlay_plan(table, cut)
        self.assertEqual(len(plan), 1)  # SH003 was cut
        self.assertEqual((plan[0]["t0"], plan[0]["t1"]), (4.5, 7.0))

    def test_ffmpeg_args(self) -> None:
        plan = [{"character": "dara", "side": "left", "x": 0.05, "y": 0.5, "start_sec": 0.5, "hold_sec": 2.0, "t0": 4.5, "t1": 6.5}]
        args = ffmpeg_overlay_args(Path("in.mp4"), plan, [Path("dara.png")], Path("out.mp4"), 1280, 720)
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("enable='between(t,4.500,6.500)'", graph)
        self.assertIn("fade=t=out:st=1.750", graph)
        self.assertIn("overlay=x=40:y=336", graph)
        self.assertEqual(args[args.index("-map") + 1], "[v1]")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("swiftc"), "needs ffmpeg and swiftc (macOS)")
class RenderTests(unittest.TestCase):
    def test_card_appears_only_in_its_window(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            coretext = coretext_binary(SCRIPTS / "khmer_coretext.swift")
            png = render_card("តារា", "និស្សិតបុរាណវិទ្យា", 360, tmp / "card.png", coretext)
            self.assertGreater(Image.open(png).getbbox()[2], 50)
            video = tmp / "base.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x204060:s=640x360:d=2:r=25",
                            "-pix_fmt", "yuv420p", str(video)], check=True)
            plan = [{"character": "dara", "side": "left", "x": 0.1, "y": 0.4, "start_sec": 0.5, "hold_sec": 1.0, "t0": 0.5, "t1": 1.5}]
            out = tmp / "out.mp4"
            subprocess.run(ffmpeg_overlay_args(video, plan, [png], out, 640, 360), check=True)

            def frame_at(t: float) -> Image.Image:
                still = tmp / f"f{t}.png"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(still)], check=True)
                return Image.open(still).convert("RGB")

            box = (64, 144, 300, 230)
            before = frame_at(0.1).crop(box).getextrema()
            during = frame_at(1.0).crop(box).getextrema()
            self.assertLess(max(hi - lo for lo, hi in before), 12)  # flat background
            self.assertGreater(max(hi - lo for lo, hi in during), 120)  # white text on it


if __name__ == "__main__":
    unittest.main()
