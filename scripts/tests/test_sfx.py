#!/usr/bin/env python3
"""SFX planner: Chinese labels, shot-table events, disk checks. No Freesound."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.pipeline import validate_audio  # noqa: E402
from director.sfx import labels_to_tags, plan_events, resolve_overrides, run_mix  # noqa: E402


def _tags(labels) -> list[str]:
    return [item["tag"] for item in labels_to_tags(labels) if item.get("tag")]


class SfxTests(unittest.TestCase):
    def test_labels_to_tags(self) -> None:
        self.assertEqual(_tags(["雷声", "暴雨砸河面", "落水"]), ["thunder", "rain", "splash"])
        self.assertEqual(_tags(["箭矢"]), ["arrow", "arrow_hit"])
        self.assertEqual(_tags(["人马陷泥"]), ["horse", "horse_water", "mud"])
        self.assertEqual(_tags(["麻绳勒腕", "草绳套落下"]), ["rope"])
        self.assertTrue(any(item.get("unmapped") for item in labels_to_tags(["宇宙激光"])))

    def test_factory_labels_to_tags(self) -> None:
        self.assertEqual(_tags(["车轮卡旧门槛，响"]), ["cart_bump"])
        self.assertEqual(_tags(["钥匙扔到脚边"]), ["keys_drop"])
        self.assertEqual(_tags(["扫帚刮地"]), ["broom_sweep"])
        self.assertEqual(_tags(["柜门吱呀"]), ["cabinet_squeak"])
        self.assertEqual(_tags(["抹灰"]), ["cloth_wipe"])
        self.assertEqual(_tags(["退撞柜门", "扫把掉了"]), ["cabinet_bump", "broom_drop"])
        self.assertEqual(_tags(["门外喊她"]), ["door_call"])
        self.assertEqual(_tags(["脚步不停"]), ["footsteps_indoor"])
        self.assertEqual(_tags(["脚步"]), ["footsteps"])
        self.assertEqual(_tags(["布甩在地上"]), ["cloth_throw"])
        self.assertEqual(_tags(["笔帽拧开"]), ["pen_click"])
        self.assertEqual(_tags(["塞进围裙口袋"]), ["pocket"])
        self.assertEqual(_tags(["刷卡"]), ["badge"])

    def test_plan_uses_internal_cuts_for_splash(self) -> None:
        table = [
            {
                "shot_id": "SH001",
                "scene_id": "SC01",
                "location_id": "modern-channel",
                "light": {"day_night": "storm-day"},
                "key_sfx": ["雷声", "暴雨砸河面", "落水"],
                "internal_cuts": [{"at_sec": 3, "one_action": "坠入河心"}, {"at_sec": 5, "one_action": "没入"}],
                "dialogue_ref": [],
            },
            {
                "shot_id": "SH002",
                "scene_id": "SC01",
                "location_id": "modern-channel",
                "key_sfx": ["呛水、急流拍岸"],
                "internal_cuts": [],
                "dialogue_ref": [{"line": "什么人？"}],
            },
        ]
        timeline = [
            {"shot_id": "SH001", "start": 0.0, "duration": 8.0, "end": 8.0, "file": ""},
            {"shot_id": "SH002", "start": 8.0, "duration": 5.0, "end": 13.0, "file": ""},
        ]
        events = plan_events(table, timeline)
        tags = [ev["tag"] for ev in events]
        self.assertIn("river", tags)
        self.assertIn("rain", tags)
        splashes = [ev for ev in events if ev["kind"] == "spot" and ev["tag"] == "splash" and ev["shot_id"] == "SH001"]
        self.assertEqual(sorted(round(ev["at"], 1) for ev in splashes), [3.0, 5.0])
        thunders = [ev for ev in events if ev["tag"] == "thunder"]
        self.assertTrue(any(abs(ev["at"] - 0.0) < 0.01 for ev in thunders))

    def test_overrides_replace_planner(self) -> None:
        timeline = [
            {"shot_id": "SH001", "start": 0.0, "duration": 6.0, "end": 6.0, "file": ""},
            {"shot_id": "SH002", "start": 6.0, "duration": 4.0, "end": 10.0, "file": ""},
        ]
        events = resolve_overrides(
            {
                "beds": [{"tag": "river", "from_shot": "SH001", "to_shot": "SH002", "vol": 0.2}],
                "spots": [{"tag": "splash", "shot_id": "SH002", "at_sec": 1.5, "vol": 0.6, "why": "落水"}],
            },
            timeline,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["end"], 10.0)
        self.assertAlmostEqual(events[1]["at"], 7.5)

    def test_validate_audio_missing_sfx_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp)
            errors = validate_audio({"sfx_file": "07-dubbing/sfx/ep01-sfx.m4a"}, {}, prod)
            self.assertTrue(any("sfx_file" in item for item in errors))
            dest = prod / "07-dubbing" / "sfx"
            dest.mkdir(parents=True)
            (dest / "ep01-sfx.m4a").write_bytes(b"x")
            self.assertEqual(validate_audio({"sfx_file": "07-dubbing/sfx/ep01-sfx.m4a"}, {}, prod), [])

    def test_plan_factory_location_beds(self) -> None:
        table = [
            {
                "shot_id": "SH001",
                "scene_id": "SC01",
                "location_id": "factory-gate",
                "key_sfx": ["车轮卡旧门槛，响"],
                "internal_cuts": [],
                "dialogue_ref": [],
            },
            {
                "shot_id": "SH007",
                "scene_id": "SC02",
                "location_id": "storeroom",
                "key_sfx": ["扫帚刮地"],
                "internal_cuts": [],
                "dialogue_ref": [],
            },
            {
                "shot_id": "SH018",
                "scene_id": "SC03",
                "location_id": "line-7",
                "key_sfx": ["脚步不停"],
                "internal_cuts": [],
                "dialogue_ref": [],
            },
        ]
        timeline = [
            {"shot_id": "SH001", "start": 0.0, "duration": 7.0, "end": 7.0, "file": ""},
            {"shot_id": "SH007", "start": 7.0, "duration": 8.0, "end": 15.0, "file": ""},
            {"shot_id": "SH018", "start": 15.0, "duration": 8.0, "end": 23.0, "file": ""},
        ]
        events = plan_events(table, timeline)
        tags = [ev["tag"] for ev in events]
        self.assertIn("factory_yard", tags)
        self.assertIn("room_tone", tags)
        self.assertIn("factory", tags)
        self.assertIn("cart_bump", tags)
        self.assertIn("broom_sweep", tags)
        self.assertIn("footsteps_indoor", tags)
        self.assertNotIn("river", tags)
        self.assertNotIn("footsteps", tags)
        indoor = [ev for ev in events if ev["tag"] == "footsteps_indoor"]
        self.assertTrue(indoor)
        self.assertEqual(indoor[0]["kind"], "loop")

    def test_dry_run_009_uses_overrides(self) -> None:
        prod = ROOT / "productions" / "009-siem-reap"
        if not (prod / ".pipeline" / "shot_list.json").exists():
            self.skipTest("009 shot_list missing")
        result = run_mix(prod, episode=1, dry_run=True, preview=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], "overrides")
        self.assertGreaterEqual(result["event_count"], 30)
        self.assertFalse(result["writes_shots_json"])

    def test_dry_run_010_maps_factory_cues(self) -> None:
        prod = ROOT / "productions" / "010-gongpai"
        if not (prod / ".pipeline" / "shot_list.json").exists():
            self.skipTest("010 shot_list missing")
        result = run_mix(prod, episode=1, dry_run=True, preview=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "shot_table")
        self.assertEqual(result["unmapped_labels"], [])
        self.assertGreaterEqual(result["event_count"], 11)
        self.assertFalse(result["writes_shots_json"])


if __name__ == "__main__":
    unittest.main()
