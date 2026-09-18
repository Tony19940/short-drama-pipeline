#!/usr/bin/env python3
"""Codex 5-cap still pack, missing costume plates, fail-parent chain, Gate D episode paths."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.codex_stills import (  # noqa: E402
    StillPackError,
    missing_costume_state_files,
    pack_codex_still_refs,
)
from director.pipeline import compile_packages_from_specs, validate_packages, write_artifact  # noqa: E402
from director.prompts import compile_keyframe_prompt_zh, compile_reference_roles_from_files, rewrite_still_prompt  # noqa: E402
from place_codex_frame import parent_chain_errors, place  # noqa: E402


def _write_rgb(path: Path, size=(64, 36), color=(40, 30, 20)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


def _asset(asset_id: str, kind: str, name: str, file: str, **over) -> dict:
    item = {
        "asset_id": asset_id,
        "type": kind,
        "name": name,
        "binds_to": name,
        "file": file,
        "what_it_locks": "identity",
        "version": "v1",
        "lock_card": [],
        "image_prompt": "",
    }
    item.update(over)
    return item


class PromptOpener(unittest.TestCase):
    def test_still_opener_is_cg_not_photoreal(self) -> None:
        text = compile_keyframe_prompt_zh(
            {
                "shot_size": "medium",
                "angle": "eye",
                "focal_length": "50mm",
                "in_from": "琳站着",
                "action_now": "琳抬眼",
            }
        )
        self.assertTrue(text.startswith("数字电影 CG 静帧"))
        self.assertNotIn("写实静帧", text)


class StillPack(unittest.TestCase):
    def test_seven_people_cap_at_five_and_numbering_matches(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            parent = "02-assets/scenes/line-7/master.jpg"
            _write_rgb(prod / parent)
            assets = {"assets": [_asset("LOC_LINE-7_V1", "location", "line-7", parent, binds_to="line-7")]}
            chars = {}
            for i, name in enumerate(["rin", "bopha", "chanthy", "sannang", "vithu", "srey-mom", "yeay-mei"], 1):
                master = f"02-assets/characters/{name}/master.jpg"
                face = f"02-assets/characters/{name}/face.jpg"
                _write_rgb(prod / master, color=(10 * i, 20, 30))
                _write_rgb(prod / face, color=(10 * i, 80, 30))
                assets["assets"].append(_asset(f"CHAR_{name.upper()}_V1", "character", name, master, binds_to=name))
                chars[name] = {"costume": "base", "in_frame": True}
            files = pack_codex_still_refs(
                prod,
                parent=parent,
                state={"characters": chars, "props": [], "location": ""},
                assets=assets,
                max_refs=5,
            )
            self.assertLessEqual(len(files), 5)
            self.assertEqual(files[0], parent)
            self.assertTrue(all(item.endswith("face.jpg") for item in files[1:]))
            self.assertNotIn(parent, files[1:])
            roles = compile_reference_roles_from_files(files, assets)
            for i, rel in enumerate(files, 1):
                self.assertIn(f"[图{i}]", roles)
            self.assertNotIn("[图6]", roles)
            rewritten = rewrite_still_prompt("数字电影 CG 静帧。[图9] 是旧编号。", files, assets)
            self.assertIn("[图1] 是父图", rewritten)
            self.assertNotIn("[图9]", rewritten)

    def test_missing_line_leader_fails_ep04_compile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            loc = "02-assets/scenes/line-7/master.jpg"
            _write_rgb(prod / loc)
            _write_rgb(prod / "02-assets/characters/rin/master.jpg")
            assets = {
                "assets": [
                    _asset("LOC_LINE-7_V1", "location", "line-7", loc, binds_to="line-7"),
                    _asset("CHAR_RIN_V1", "character", "rin", "02-assets/characters/rin/master.jpg", binds_to="rin"),
                    _asset(
                        "CHAR_RIN_LINE_LEADER_V1",
                        "costume_state",
                        "rin-line-leader",
                        "02-assets/characters/rin-line-leader/master.jpg",
                        binds_to="rin",
                        costume_state_id="line-leader",
                        costume_aliases=["line-leader", "vest-oversize"],
                    ),
                ]
            }
            write_artifact(prod, "assets.json", assets)
            table = {
                "schema": "shot-table-v2",
                "target_model": "seedance_2_0",
                "episode_no": 4,
                "aspect": "16:9",
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP04_SC01",
                        "location_id": "line-7",
                        "scale": "medium",
                        "move_type": "static",
                        "coverage_type": "master",
                        "one_action": "琳站着",
                        "duration_sec": 4,
                    }
                ],
            }
            specs = {
                "shot_specs": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP04_SC01",
                        "action_now": "琳站着",
                        "shot_size": "medium",
                        "angle": "eye",
                        "focal_length": "50mm",
                        "aspect_ratio": "16:9",
                        "move_type": "static",
                        "in_from": "琳站着",
                        "duration_sec": 4,
                        "location_state_id": "line-7",
                        "state": {"characters": {"rin": {"costume": "line-leader", "in_frame": True}}, "props": [], "location": ""},
                    }
                ]
            }
            data = compile_packages_from_specs(prod, "seedance_2_0", table=table, specs=specs)
            errors = list(data.get("errors") or []) + validate_packages(data, assets, specs, prod=prod)
            self.assertTrue(any("rin-line-leader/master.jpg" in e or "CHAR_RIN_LINE_LEADER_V1" in e for e in errors), errors)
            self.assertTrue(missing_costume_state_files(prod, ["CHAR_RIN_LINE_LEADER_V1"], assets))
            with self.assertRaises(StillPackError):
                pack_codex_still_refs(
                    prod,
                    parent=loc,
                    state=specs["shot_specs"][0]["state"],
                    assets=assets,
                    episode=4,
                    strict_existing=True,
                )


class ParentGate(unittest.TestCase):
    def test_fail_parent_is_rejected_and_next_uses_scene_master(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            plate = prod / "02-assets" / "scenes" / "storeroom" / "master.jpg"
            plate.parent.mkdir(parents=True)
            Image.new("RGB", (128, 72), (10, 10, 10)).save(plate)
            src = Path(raw) / "frame.png"
            Image.new("RGB", (128, 72), (40, 80, 40)).save(src)
            write_artifact(
                prod,
                "shot_list.json",
                {
                    "schema": "shot-table-v2",
                    "shots": [
                        {"shot_id": "SH007", "scene_id": "EP01_SC02"},
                        {"shot_id": "SH008", "scene_id": "EP01_SC02"},
                    ],
                },
            )
            place(prod, "SH007", "first", src, parent="02-assets/scenes/storeroom/master.jpg", identity_gate="fail")
            with self.assertRaises(ValueError):
                place(prod, "SH008", "first", src)
            with self.assertRaises(ValueError):
                place(prod, "SH008", "first", src, parent="04-frames/SH007.jpg")
            landed = place(
                prod,
                "SH008",
                "first",
                src,
                parent="02-assets/scenes/storeroom/master.jpg",
                allow_master=True,
                identity_gate="pass",
            )
            self.assertEqual(landed["parent"], "02-assets/scenes/storeroom/master.jpg")
            self.assertEqual(parent_chain_errors(prod), [])


class GateDEpisode(unittest.TestCase):
    def test_gate_d_episode_two_looks_under_ep02(self) -> None:
        from director.gates import gate_file_ready, inspect_files

        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw) / "v2show"
            (prod / ".pipeline").mkdir(parents=True)
            (prod / "04-frames" / "ep02").mkdir(parents=True)
            Image.new("RGB", (32, 18)).save(prod / "04-frames" / "ep02" / "SH001.jpg")
            table = {"schema": "shot-table-v2", "status": "locked", "episode_no": 2, "shots": [{"shot_id": "SH001", "scale": "wide"}]}
            packages = {"packages": [{"shot_id": "SH001", "keyframe_plan": "first"}]}
            qc = {
                "status": "pass",
                "face": "pass",
                "costume": "pass",
                "location": "pass",
                "left_right": "pass",
                "composition": "pass",
                "aspect_ratio": "pass",
                "light_matches_spec": "pass",
                "state_match": "pass",
            }
            kf = {
                "reviewed_by": "tonyteacher",
                "keyframes": [{"shot_id": "SH001", "first_frame_file": "04-frames/ep02/SH001.jpg", "qc": qc}],
            }
            (prod / ".pipeline" / "shot_list.ep02.json").write_text(json.dumps(table), encoding="utf-8")
            (prod / ".pipeline" / "gen_packages.ep02.json").write_text(json.dumps(packages), encoding="utf-8")
            (prod / ".pipeline" / "keyframes.ep02.json").write_text(json.dumps(kf), encoding="utf-8")
            files = inspect_files(prod, episode=2)
            self.assertEqual(files["shot_count"], 1)
            self.assertEqual(files["locked_frame_count"], 1)
            self.assertTrue(files["frames"][0]["frame"])
            self.assertFalse((prod / "04-frames" / "SH001.jpg").exists())
            ready, reason = gate_file_ready(prod, "D", files, episode=2)
            self.assertTrue(ready, reason)

    def test_fill_episode_frames_refuses_gongpai(self) -> None:
        import fill_episode_frames

        prod = ROOT / "productions" / "010-gongpai"
        argv = ["fill_episode_frames.py", "--prod", str(prod), "--episode", "2"]
        old = sys.argv
        sys.argv = argv
        try:
            with self.assertRaises(SystemExit) as ctx:
                fill_episode_frames.main()
        finally:
            sys.argv = old
        self.assertIn("禁止用空镜冒充首帧", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
