#!/usr/bin/env python3
"""Per-image reference roles for 6.1 prompts: [图N] sentences, the double-inject guard, package wiring."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.pipeline import compile_packages_from_specs, validate_packages, write_artifact  # noqa: E402
from director.prompts import compile_reference_roles_zh, has_reference_roles  # noqa: E402


def asset(asset_id: str, kind: str, name: str, file: str, **over) -> dict:
    item = {
        "asset_id": asset_id,
        "type": kind,
        "name": name,
        "binds_to": name,
        "file": file,
        "what_it_locks": {"location": "space", "prop": "prop"}.get(kind, "identity"),
        "version": "v1",
        "lock_card": [],
        "image_prompt": "",
    }
    item.update(over)
    return item


ASSETS = {
    "assets": [
        asset("STYLE_LOCK_V1", "style", "look", "02-assets/LOOK.md", binds_to="episode"),
        asset("LOC_STOREROOM_V1", "location", "storeroom", "02-assets/scenes/storeroom/master.jpg"),
        asset("CHAR_RIN_V1", "character", "rin", "02-assets/characters/rin/master.jpg"),
        asset("CHAR_RIN_FACE_V1", "character", "rin", "02-assets/characters/rin/face.jpg"),
        asset("CHAR_RIN_SHEET_V1", "character", "rin", "02-assets/characters/rin/sheet.jpg"),
        asset("CHAR_BOPHA_V1", "character", "bopha", "02-assets/characters/bopha/master.jpg"),
        asset("PROP_BADGE_V1", "prop", "badge", "02-assets/props/badge/master.jpg"),
    ]
}

TABLE = {
    "schema": "shot-table-v2",
    "target_model": "seedance_2_0",
    "aspect": "16:9",
    "shots": [
        {"shot_id": "SH001", "scene_id": "EP01_SC01", "location_id": "storeroom", "scale": "medium", "move_type": "static", "coverage_type": "master", "one_action": "琳抬眼", "duration_sec": 4},
        {"shot_id": "SH002", "scene_id": "EP01_SC01", "location_id": "storeroom", "scale": "wide", "move_type": "static", "coverage_type": "empty", "one_action": "空仓", "duration_sec": 4},
        {"shot_id": "SH003", "scene_id": "EP01_SC01", "location_id": "storeroom", "scale": "medium", "move_type": "static", "coverage_type": "master", "one_action": "琳抬眼", "duration_sec": 4},
    ],
}


def spec(shot_id: str, **over) -> dict:
    base = {
        "shot_id": shot_id,
        "scene_id": "EP01_SC01",
        "content": "琳抬眼",
        "subject": "琳握着工牌抬眼",
        "action_now": "琳握着工牌抬眼",
        "shot_size": "medium",
        "angle": "eye",
        "focal_length": "50mm",
        "aspect_ratio": "16:9",
        "move_type": "static",
        "in_from": "琳低头看工牌",
        "out_to": "琳看向镜头",
        "left": "琳",
        "right": "储物柜",
        "eyeline": "向右上",
        "day_night": "day",
        "key_light_dir": "顶侧",
        "quality": "硬",
        "color_mood": "冷白日光灯",
        "duration_sec": 4,
        "location_state_id": "storeroom",
        "state": {"characters": {"rin": {"costume": "base"}, "bopha": {"costume": "base"}}, "props": [], "location": ""},
    }
    base.update(over)
    return base


class ReferenceRoles(unittest.TestCase):
    def test_plate_then_two_passports(self) -> None:
        text = compile_reference_roles_zh(["LOC_STOREROOM_V1", "CHAR_RIN_V1", "CHAR_BOPHA_V1"], ASSETS)
        self.assertEqual(
            text,
            "[图1] 是父图（本场空镜 storeroom）：机位、空间、光位、画幅以此为准，只改一件事。"
            "[图2] 是 rin 的 master.jpg：只锁脸和衣服，不参考构图姿势。"
            "[图3] 是 bopha 的 master.jpg：只锁脸和衣服，不参考构图姿势。"
            "各图身份边界不混，不把别的图的人物画进来。",
        )
        self.assertTrue(has_reference_roles(text))

    def test_face_sheet_prop_and_no_parent(self) -> None:
        text = compile_reference_roles_zh(
            ["LOC_STOREROOM_V1", "CHAR_RIN_FACE_V1", "CHAR_RIN_SHEET_V1", "PROP_BADGE_V1"], ASSETS, parent_first=False
        )
        self.assertIn("[图1] 是本场空镜 storeroom：机位、空间、光位以此为准，不当画布。", text)
        self.assertIn("[图2] 是 rin 的 face.jpg：只锁脸和衣服，不参考构图姿势。", text)
        self.assertIn("[图3] 是 rin 的 sheet.jpg：取与本镜机位一致的面板，不当首帧。", text)
        self.assertIn("[图4] 是道具 badge：只认这件道具的形状和状态。", text)
        self.assertNotIn("父图", text)
        self.assertTrue(text.endswith("各图身份边界不混，不把别的图的人物画进来。"))

    def test_style_asset_takes_no_number_and_unknown_ids_fall_back_to_prefix(self) -> None:
        text = compile_reference_roles_zh(["STYLE_LOCK_V1", "LOC_STOREROOM_V1", "CHAR_SOKHA_V1", "PROP_POLE_V1"], ASSETS)
        self.assertTrue(text.startswith("[图1] 是父图（本场空镜 storeroom）"))
        self.assertIn("[图2] 是 sokha 的护照：只锁脸和衣服", text)
        self.assertIn("[图3] 是道具 pole：只认这件道具的形状和状态。", text)
        self.assertNotIn("[图4]", text)
        self.assertEqual(compile_reference_roles_zh([], ASSETS), "")

    def test_guard_regex(self) -> None:
        for text in ("[图1] 是父图", "见 [图 2]", "@图1：脸", "@1：父图，@2：脸"):
            self.assertTrue(has_reference_roles(text), text)
        for text in ("", "图1是父图", "参考图逐图点名", "mail@example.com"):
            self.assertFalse(has_reference_roles(text), text)


class PackageWiring(unittest.TestCase):
    def test_zh_package_names_each_reference_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "010-demo"
            prod.mkdir()
            write_artifact(prod, "assets.json", ASSETS)
            specs = {
                "shot_specs": [
                    spec("SH001"),
                    spec("SH002", subject="空仓", action_now="空仓", state={"characters": {}, "props": [], "location": ""}),
                    spec("SH003", subject="@1 的脸对着镜头"),
                ]
            }
            data = compile_packages_from_specs(prod, "seedance_2_0", table=TABLE, specs=specs)
            self.assertEqual(validate_packages(data, ASSETS, specs), [])
            by_id = {pkg["shot_id"]: pkg for pkg in data["packages"]}
            first = by_id["SH001"]
            # medium shot: plate, then rin's passport + sheet + face, then bopha's passport
            self.assertEqual(
                first["asset_refs"],
                ["LOC_STOREROOM_V1", "CHAR_RIN_V1", "CHAR_RIN_SHEET_V1", "CHAR_RIN_FACE_V1", "CHAR_BOPHA_V1"],
            )
            self.assertEqual(first["prompt_language"], "zh")
            self.assertTrue(first["image_prompt"].startswith("数字电影 CG 静帧"))
            self.assertNotIn("写实静帧", first["image_prompt"])
            self.assertIn("[图1] 是父图（本场空镜 storeroom）", first["image_prompt"])
            self.assertIn("[图2] 是 rin 的 master.jpg：只锁脸和衣服", first["image_prompt"])
            self.assertIn("[图3] 是 rin 的 sheet.jpg：取与本镜机位一致的面板", first["image_prompt"])
            self.assertIn("[图4] 是 rin 的 face.jpg：只锁脸和衣服", first["image_prompt"])
            self.assertIn("[图5] 是 bopha 的 master.jpg", first["image_prompt"])
            self.assertLessEqual(len(first["still_ref_files"]), 5)
            self.assertEqual(first["still_ref_files"][0], "02-assets/scenes/storeroom/master.jpg")
            self.assertNotIn("sheet.jpg", first.get("still_image_prompt") or "")
            self.assertIn("[图1] 是父图（本场空镜 storeroom）", first["still_image_prompt"])
            self.assertEqual(first["image_prompt"].count("各图身份边界不混"), 1)
            self.assertNotIn("[图", first["motion_prompt"])
            # one reference only: nothing to tell apart
            self.assertEqual(by_id["SH002"]["asset_refs"], ["LOC_STOREROOM_V1"])
            self.assertNotIn("[图", by_id["SH002"]["image_prompt"])
            # the spec already names its pictures @1 style: do not inject a second numbering
            self.assertEqual(len(by_id["SH003"]["asset_refs"]), 5)
            self.assertIn("@1 的脸对着镜头", by_id["SH003"]["image_prompt"])
            self.assertNotIn("[图1]", by_id["SH003"]["image_prompt"])

    def test_en_package_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "010-demo"
            prod.mkdir()
            write_artifact(prod, "assets.json", ASSETS)
            table = dict(TABLE, target_model="minimax_h3")
            data = compile_packages_from_specs(prod, "minimax_h3", table=table, specs={"shot_specs": [spec("SH001")]})
            pkg = data["packages"][0]
            self.assertEqual(len(pkg["asset_refs"]), 5)
            self.assertEqual(pkg["prompt_language"], "en")
            self.assertNotIn("[图", pkg["image_prompt"])


if __name__ == "__main__":
    unittest.main()
