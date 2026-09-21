#!/usr/bin/env python3
"""Batch A regression: story fidelity, immutable request, cache, confirm, QC."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.context import ProductionContext  # noqa: E402
from director.pipeline import compile_packages_from_specs, parse_artifact_filename, write_artifact  # noqa: E402
from director.shot_repo import list_shots, select_shots  # noqa: E402
from director.shot_table import BINDING_UNKNOWN, normalize_state, sanitize_shot_table  # noqa: E402
from director.station_agents import (  # noqa: E402
    _load_design_cache,
    _repair_writer_lines,
    _save_design_cache,
    _split_overlong_shots,
    clear_design_cache,
)
from director.vendor_request import (  # noqa: E402
    DurationOutOfRange,
    UnsupportedTaskKind,
    VendorRequest,
    resolve_render_seconds,
    seedance_mode_for_task,
    task_kind_for_gen_mode,
    vendor_request_from_package,
)
from director.video_profiles import UnknownProfileError, get_profile  # noqa: E402
from place_codex_frame import place, read_sidecar  # noqa: E402
from render_seedance_packages import seedance_mode  # noqa: E402
from video_backends.seedance_ark import SeedanceArk  # noqa: E402


class ProfilesAndRequest(unittest.TestCase):
    def test_unknown_model_is_an_error(self) -> None:
        with self.assertRaises(UnknownProfileError):
            get_profile("not-a-real-model")

    def test_seedance_25_twenty_seconds_stays_twenty(self) -> None:
        seconds = resolve_render_seconds(
            {"duration_sec": 20, "target_model": "seedance_2_5", "seedance_max_sec": 30, "seedance_min_sec": 4}
        )
        self.assertEqual(seconds, 20)
        req = VendorRequest(
            provider="ark",
            model="doubao-seedance-2-5-260628",
            profile_id="seedance_2_5",
            task_kind="first_frame",
            ratio="16:9",
            resolution="720p",
            duration_sec=20,
            generate_audio=True,
            prompt="听完再看她",
            shot_id="SH020",
        )
        self.assertEqual(req.duration_sec, 20)
        self.assertEqual(req.model, "doubao-seedance-2-5-260628")
        self.assertEqual(req.profile_id, "seedance_2_5")

    def test_over_max_does_not_clamp(self) -> None:
        with self.assertRaises(DurationOutOfRange):
            resolve_render_seconds({"duration_sec": 20, "target_model": "seedance_2_0"})

    def test_env_default_does_not_override_confirmed_request(self) -> None:
        old = os.environ.get("ARK_SEEDANCE_MODEL")
        old_key = os.environ.get("ARK_API_KEY")
        os.environ["ARK_API_KEY"] = old_key or "test-key"
        os.environ["ARK_SEEDANCE_MODEL"] = "doubao-seedance-2-0-mini-260615"
        try:
            backend = SeedanceArk.from_request(
                VendorRequest(
                    provider="ark",
                    model="doubao-seedance-2-5-260628",
                    profile_id="seedance_2_5",
                    task_kind="first_frame",
                    ratio="16:9",
                    resolution="720p",
                    duration_sec=20,
                    generate_audio=True,
                    prompt="x",
                    shot_id="SH001",
                )
            )
            self.assertEqual(backend.model, "doubao-seedance-2-5-260628")
            self.assertEqual(backend.max_duration, 30)
            self.assertEqual(backend.clamp_duration(20), 20)
        finally:
            if old is None:
                os.environ.pop("ARK_SEEDANCE_MODEL", None)
            else:
                os.environ["ARK_SEEDANCE_MODEL"] = old
            if old_key is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = old_key

    def test_extend_is_not_mapped_to_i2v(self) -> None:
        self.assertEqual(task_kind_for_gen_mode("video_extend"), "extend")
        self.assertEqual(seedance_mode_for_task("extend"), "extend")
        self.assertEqual(seedance_mode("video_extend"), "extend")
        old_key = os.environ.get("ARK_API_KEY")
        os.environ["ARK_API_KEY"] = old_key or "test-key"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "a.jpg"
                Image.new("RGB", (64, 36), (1, 2, 3)).save(image)
                backend = SeedanceArk()
                with self.assertRaises(RuntimeError) as ctx:
                    backend.build_payload(image, "x", 4, mode="video_extend")
                self.assertIn("reference_video", str(ctx.exception))
                self.assertNotIn("submit as i2v", str(ctx.exception))
        finally:
            if old_key is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = old_key


class StoryFidelity(unittest.TestCase):
    def test_unmatched_line_is_not_replaced_with_the_next_unused(self) -> None:
        writer = {
            "scenes": [
                {
                    "scene_id": "EP01_SC01",
                    "dialogue": [
                        {"character": "琳", "line": "第一句。", "line_id": "EP01_SC01:d01"},
                        {"character": "春安", "line": "第二句。", "line_id": "EP01_SC01:d02"},
                    ],
                }
            ]
        }
        shots = [{"shot_id": "SH001", "dialogue_ref": [{"character": "琳", "line": "这句剧本里没有。"}]}]
        proposals = _repair_writer_lines(shots, writer, "EP01_SC01")
        self.assertEqual(shots[0]["dialogue_ref"][0]["line"], "这句剧本里没有。")
        self.assertTrue(proposals)
        self.assertEqual(proposals[0]["kind"], "unmatched_dialogue")

    def test_overlong_shot_is_not_auto_split_into_a_listen_beat(self) -> None:
        shot = {
            "shot_id": "SH001",
            "one_action": "她伸手拿起钥匙再藏进掌心。",
            "duration_sec": 20,
            "dialogue_ref": [
                {"character": "琳", "line": "第一句很长很长很长很长很长很长很长。"},
                {"character": "春安", "line": "第二句也很长很长很长很长很长。"},
            ],
        }
        out = _split_overlong_shots([shot], 15)
        self.assertEqual(len(out), 1)
        self.assertIn("replan", out[0])
        self.assertEqual(out[0]["dialogue_ref"], shot["dialogue_ref"])
        self.assertNotIn("听着，停一拍", json.dumps(out, ensure_ascii=False))

    def test_incomplete_binding_is_not_rewritten_to_none(self) -> None:
        data = sanitize_shot_table(
            {
                "schema": "shot-table-v2",
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP01_SC01",
                        "state": {
                            "characters": {"rin": {"costume": "base", "binding": "wrists_behind"}},
                            "note": "反剪但没写绑具",
                        },
                    }
                ],
            }
        )
        binding = data["shots"][0]["state"]["characters"]["rin"]["binding"]
        self.assertEqual(binding, "wrists_behind")
        self.assertNotEqual(binding, "none")
        dirty = normalize_state({"characters": {"rin": {"costume": "base", "binding": "hogtied"}}})
        self.assertEqual(dirty["characters"]["rin"]["binding"], "hogtied")
        cleaned = sanitize_shot_table(
            {
                "schema": "shot-table-v2",
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP01_SC01",
                        "state": {"characters": {"rin": {"costume": "base", "binding": "hogtied"}}, "note": "x"},
                    }
                ],
            }
        )
        self.assertEqual(cleaned["shots"][0]["state"]["characters"]["rin"]["binding"], BINDING_UNKNOWN)


class DesignCache(unittest.TestCase):
    def test_same_scene_id_does_not_keep_old_header_when_inputs_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            prod.mkdir()
            write_artifact(
                prod,
                "writer.json",
                {"scenes": [{"scene_id": "S1", "dialogue": [{"character": "琳", "line": "旧词。"}]}]},
            )
            _save_design_cache(
                prod,
                {
                    "key": "old",
                    "header": {"whose_pov": "旧"},
                    "analysis": {"scene_cards": [{"scene_id": "S1"}]},
                    "scenes": {"S1": [{"shot_id": "SH001"}]},
                },
            )
            write_artifact(
                prod,
                "writer.json",
                {"scenes": [{"scene_id": "S1", "dialogue": [{"character": "琳", "line": "改过的词。"}]}]},
            )
            cache = _load_design_cache(prod, "new")
            self.assertIsNone(cache.get("header"))
            self.assertIsNone(cache.get("analysis"))
            self.assertEqual(cache.get("scenes"), {})
            clear_design_cache(prod)


class ConfirmAndRepo(unittest.TestCase):
    def test_replacing_first_frame_bytes_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "show"
            first = prod / "04-frames" / "SH001.jpg"
            first.parent.mkdir(parents=True)
            Image.new("RGB", (64, 36), (10, 10, 10)).save(first)
            pkg = {
                "shot_id": "SH001",
                "target_model": "seedance_2_5",
                "gen_mode": "i2v_first",
                "motion_prompt": "听完再看",
                "duration_sec": 20,
                "seedance_min_sec": 4,
                "seedance_max_sec": 30,
                "generate_audio": True,
                "aspect_ratio": "16:9",
            }
            a = vendor_request_from_package(prod, pkg, {"first_frame_file": "04-frames/SH001.jpg"}, episode=1)
            Image.new("RGB", (64, 36), (200, 10, 10)).save(first)
            b = vendor_request_from_package(prod, pkg, {"first_frame_file": "04-frames/SH001.jpg"}, episode=1)
            self.assertNotEqual(a.fingerprint(), b.fingerprint())

    def test_v2_project_without_shots_json_lists_from_shot_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "v2"
            write_artifact(
                prod,
                "shot_list.json",
                {"schema": "shot-table-v2", "shots": [{"shot_id": "SH001"}, {"shot_id": "SH002"}]},
            )
            self.assertFalse((prod / "03-storyboard" / "shots.json").exists())
            ids = [row["id"] for row in list_shots(prod)]
            self.assertEqual(ids, ["SH001", "SH002"])
            self.assertEqual([row["id"] for row in select_shots(prod, ["SH002"])], ["SH002"])

    def test_place_does_not_auto_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp)
            plate = prod / "02-assets" / "scenes" / "room" / "master.jpg"
            plate.parent.mkdir(parents=True)
            Image.new("RGB", (128, 72), (10, 10, 10)).save(plate)
            src = Path(tmp) / "frame.png"
            Image.new("RGB", (128, 72), (40, 80, 40)).save(src)
            place(prod, "SH001", "first", src, parent="02-assets/scenes/room/master.jpg")
            meta = read_sidecar(prod, "04-frames/SH001.jpg")
            self.assertEqual(meta.get("identity_gate"), "unknown")
            with self.assertRaises(ValueError):
                place(prod, "SH002", "first", src, parent="04-frames/SH001.jpg")

    def test_artifact_kind_is_parsed_from_suffix(self) -> None:
        self.assertEqual(parse_artifact_filename("shot_list.json"), ("shot_list.json", 1))
        self.assertEqual(parse_artifact_filename("shot_list.ep02.json"), ("shot_list.json", "ep02"))
        self.assertEqual(parse_artifact_filename("gen_packages.ep01-v2.json"), ("gen_packages.json", "ep01-v2"))

    def test_production_context_isolates_revision_labels(self) -> None:
        ctx = ProductionContext.resolve(Path("/tmp/show"), "ep01-v2")
        self.assertEqual(ctx.episode_no, 1)
        self.assertEqual(ctx.episode_id, "ep01-v2")
        self.assertEqual(ctx.artifact_name("shot_list.json"), "shot_list.ep01-v2.json")
        self.assertEqual(ctx.shot_dir(), "05-shots/ep01-v2")


class CompileDuration(unittest.TestCase):
    def test_compile_writes_profile_max_and_keeps_20s(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "p"
            write_artifact(prod, "assets.json", {"assets": [{"asset_id": "LOC", "type": "location", "file": "02-assets/scenes/x/master.jpg"}]})
            table = {
                "schema": "shot-table-v2",
                "target_model": "seedance_2_5",
                "shots": [
                    {
                        "shot_id": "SH001",
                        "scene_id": "EP01_SC01",
                        "duration_sec": 20,
                        "one_action": "她听完",
                        "dialogue_ref": [],
                        "left": "琳",
                        "right": "门",
                        "eyeline": "看门",
                    }
                ],
            }
            specs = {
                "shot_specs": [
                    {
                        "shot_id": "SH001",
                        "duration_sec": 20,
                        "action_now": "听",
                        "dialogue_line": "",
                        "left": "琳",
                        "right": "门",
                        "eyeline": "看门",
                    }
                ]
            }
            data = compile_packages_from_specs(prod, target_model="seedance_2_5", table=table, specs=specs)
            pkg = data["packages"][0]
            self.assertEqual(pkg["seedance_max_sec"], 30)
            self.assertEqual(int(pkg["render_duration_sec"]), 20)
            self.assertNotIn("duration 20", " ".join(data.get("errors") or []))


if __name__ == "__main__":
    unittest.main()
