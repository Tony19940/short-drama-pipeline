#!/usr/bin/env python3
"""continuity-hard.json → package binding + costume_state lookup."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.continuity_hard import (  # noqa: E402
    hard_items_for_state,
    package_binding,
    resolve_costume_token,
)
from director.pipeline import asset_refs_for_package, compile_packages_from_specs  # noqa: E402


HARD = {
    "characters": [
        {
            "cast_id": "rin",
            "name": "琳",
            "items": ["工牌 T-0417 / TEMP", "塑料拖鞋可留"],
            "costume_bands": [
                {"episodes": [1, 2, 3], "costume_state_id": "cleaning", "aliases": ["dry"]},
                {"episodes": [4, 5, 6, 7], "costume_state_id": "line-leader"},
                {"episodes": [8, 9, 10, 11, 12, 13, 14, 15], "costume_state_id": "guest"},
            ],
        },
        {
            "cast_id": "bopha",
            "name": "波帕",
            "items": ["长衫盖脚", "暖金光", "半透明", "不碰实物", "无伤口"],
        },
    ]
}

ASSETS = {
    "assets": [
        {
            "asset_id": "CHAR_RIN_V1",
            "type": "character",
            "binds_to": "rin",
            "file": "02-assets/characters/rin/master.jpg",
        },
        {
            "asset_id": "CHAR_RIN_CLEANING_V1",
            "type": "costume_state",
            "binds_to": "rin",
            "costume_state_id": "cleaning",
            "costume_aliases": ["dry"],
            "file": "02-assets/characters/rin/master.jpg",
        },
        {
            "asset_id": "CHAR_RIN_LINE_LEADER_V1",
            "type": "costume_state",
            "binds_to": "rin",
            "costume_state_id": "line-leader",
            "file": "02-assets/characters/rin-line-leader/master.jpg",
        },
        {
            "asset_id": "CHAR_BOPHA_V1",
            "type": "character",
            "binds_to": "bopha",
            "file": "02-assets/characters/bopha/master.jpg",
        },
        {
            "asset_id": "LOC_GATE_V1",
            "type": "location",
            "binds_to": "factory-gate",
            "file": "02-assets/scenes/factory-gate/master.jpg",
        },
    ]
}


class ContinuityHardUnitTests(unittest.TestCase):
    def test_episode_band_overrides_declared_dry(self):
        self.assertEqual(resolve_costume_token(HARD, "rin", 1, "dry"), "cleaning")
        self.assertEqual(resolve_costume_token(HARD, "rin", 5, "dry"), "line-leader")
        self.assertEqual(resolve_costume_token(HARD, "rin", 8, "striped-shirt"), "guest")
        self.assertEqual(resolve_costume_token({}, "rin", 5, "dry"), "dry")

    def test_binding_keeps_restraint_enum(self):
        items = hard_items_for_state(
            HARD,
            1,
            {"characters": {"rin": {"in_frame": True, "costume": "dry"}}},
        )
        self.assertTrue(items)
        self.assertIn("琳：", items[0])
        self.assertEqual(package_binding("wrists_behind", items), "wrists_behind")
        self.assertIn("工牌 T-0417 / TEMP", package_binding("none", items))
        self.assertEqual(package_binding("none", []), "none")

    def test_out_of_frame_skipped(self):
        items = hard_items_for_state(
            HARD,
            1,
            {"characters": {"rin": {"in_frame": False, "costume": "dry"}}},
        )
        self.assertEqual(items, [])

    def test_asset_lookup_uses_costume_state_id(self):
        shot = {
            "location_id": "factory-gate",
            "scale": "full",
            "state": {
                "characters": {
                    "rin": {"costume": "dry", "binding": "none", "bound_with": "", "carrying": [], "in_frame": True}
                },
                "props": [],
                "note": "",
            },
        }
        refs, costume, _ = asset_refs_for_package(
            {},
            shot,
            ASSETS,
            table={"whose_pov": "rin"},
            writer={"series_bible": {"characters": [{"id": "rin", "name": "琳"}]}},
            hard=HARD,
            episode=1,
        )
        self.assertIn("CHAR_RIN_CLEANING_V1", refs)
        self.assertNotIn("CHAR_RIN_V1", refs)
        self.assertEqual(costume, "rin-cleaning")

        refs, costume, _ = asset_refs_for_package(
            {},
            shot,
            ASSETS,
            table={"whose_pov": "rin"},
            writer={"series_bible": {"characters": [{"id": "rin", "name": "琳"}]}},
            hard=HARD,
            episode=5,
        )
        self.assertIn("CHAR_RIN_LINE_LEADER_V1", refs)
        self.assertEqual(costume, "rin-line-leader")


class ContinuityHardCompileTests(unittest.TestCase):
    def test_compile_injects_binding_from_hard_file(self):
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "02-assets").mkdir()
            (prod / ".pipeline").mkdir()
            (prod / "02-assets" / "continuity-hard.json").write_text(
                json.dumps(HARD, ensure_ascii=False), encoding="utf-8"
            )
            (prod / ".pipeline" / "assets.json").write_text(json.dumps(ASSETS), encoding="utf-8")
            table = {
                "schema": "shot-table-v2",
                "episode_no": 1,
                "target_model": "seedance_2_0",
                "aspect": "16:9",
                "whose_pov": "琳",
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP01_SC01",
                        "location_id": "factory-gate",
                        "scale": "full",
                        "move_type": "static",
                        "coverage_type": "master",
                        "one_action": "琳进厂",
                        "duration_sec": 4,
                        "state": {
                            "characters": {
                                "rin": {
                                    "costume": "dry",
                                    "binding": "none",
                                    "bound_with": "",
                                    "carrying": [],
                                    "in_frame": True,
                                }
                            },
                            "props": [],
                            "note": "进厂",
                        },
                    }
                ],
            }
            (prod / ".pipeline" / "shot_list.json").write_text(json.dumps(table), encoding="utf-8")
            data = compile_packages_from_specs(prod, target_model="seedance_2_0", table=table, specs=None)
            pkg = data["packages"][0]
            self.assertIn("工牌 T-0417 / TEMP", pkg["continuity"]["binding"])
            self.assertTrue(pkg["continuity"]["hard_items"])
            self.assertEqual(pkg["continuity"]["costume_state_id"], "rin-cleaning")
            self.assertIn("CHAR_RIN_CLEANING_V1", pkg["asset_refs"])


if __name__ == "__main__":
    unittest.main()
