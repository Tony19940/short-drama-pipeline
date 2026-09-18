#!/usr/bin/env python3
"""Per-episode frame landing and package compile — real entry points."""

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

from compile_episode_packages import compile_episode, qc_pass, validate_episode  # noqa: E402
from director.pipeline import episode_artifact_name  # noqa: E402
from place_codex_frame import FRAME_SIZE, dest_rel, place  # noqa: E402


PROD = ROOT / "productions" / "009-siem-reap"


def _write_rgb(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


class EpisodeArtifactNameTests(unittest.TestCase):
    def test_ep01_keeps_historical_name(self):
        self.assertEqual(episode_artifact_name("gen_packages.json", 1), "gen_packages.json")

    def test_later_episodes_are_suffixed(self):
        self.assertEqual(episode_artifact_name("gen_packages.json", 2), "gen_packages.ep02.json")
        self.assertEqual(episode_artifact_name("keyframes.json", 8), "keyframes.ep08.json")

    def test_labeled_variant_does_not_clobber_ep01(self):
        from director.pipeline import episode_frame_dir, episode_label, episode_number, episode_shot_dir, parse_episode
        from place_codex_frame import dest_rel

        self.assertEqual(parse_episode("ep01-v2"), (1, "ep01-v2"))
        self.assertEqual(episode_number("ep01-v2"), 1)
        self.assertEqual(episode_label("ep01-v2"), "ep01-v2")
        self.assertEqual(episode_artifact_name("gen_packages.json", "ep01-v2"), "gen_packages.ep01-v2.json")
        self.assertEqual(episode_artifact_name("shot_list.json", "ep01-v2"), "shot_list.ep01-v2.json")
        self.assertEqual(episode_artifact_name("gen_packages.json", 1), "gen_packages.json")
        self.assertEqual(episode_frame_dir("ep01-v2"), "04-frames/ep01-v2")
        self.assertEqual(episode_frame_dir(1), "04-frames")
        self.assertEqual(episode_shot_dir("ep01-v2"), "05-shots/ep01-v2")
        self.assertEqual(episode_shot_dir(1), "05-shots")
        self.assertEqual(dest_rel("SH001", "first", "ep01-v2"), "04-frames/ep01-v2/SH001.jpg")
        self.assertEqual(dest_rel("SH008", "last", "ep01-v2"), "04-frames/ep01-v2/SH008-last.jpg")

    def test_qc_pass_is_n_a_not_auto_lock(self):
        qc = qc_pass({"scale": "wide", "coverage_type": "master"}, "first")
        self.assertEqual(qc["status"], "n/a")
        self.assertEqual(qc["face"], "n/a")
        tight = qc_pass({"scale": "close", "coverage_type": "close"}, "first_last")
        self.assertEqual(tight["plastic_face"], "n/a")
        self.assertEqual(tight["out_to_readable"], "n/a")

    def test_station_names_keep_ep01_and_suffix_later(self):
        from director.station_agents import shot_list_artifact_name, storyboard_md_name, writer_artifact_name

        self.assertEqual(writer_artifact_name(1), "writer.json")
        self.assertEqual(writer_artifact_name(2), "writer.ep02.json")
        self.assertEqual(shot_list_artifact_name(1), "shot_list.json")
        self.assertEqual(shot_list_artifact_name(3), "shot_list.ep03.json")
        self.assertEqual(storyboard_md_name("scene-cards.draft.md", 1), "03-storyboard/scene-cards.draft.md")
        self.assertEqual(storyboard_md_name("scene-cards.draft.md", 2), "03-storyboard/scene-cards.ep02.draft.md")


class PlaceFrameEpisodeTests(unittest.TestCase):
    def test_episode_two_lands_under_ep02_and_resizes(self):
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            parent = prod / "02-assets" / "scenes" / "granary" / "master.jpg"
            _write_rgb(parent, (64, 36), (40, 30, 20))
            src = prod / "src.png"
            Image.new("RGB", (320, 180), (12, 80, 40)).save(src)
            result = place(
                prod,
                "SH001",
                "first",
                src,
                parent="02-assets/scenes/granary/master.jpg",
                episode=2,
            )
            dest = prod / result["dest"]
            self.assertEqual(result["dest"], "04-frames/ep02/SH001.jpg")
            self.assertEqual(dest_rel("SH001", "first", 2), "04-frames/ep02/SH001.jpg")
            self.assertTrue(dest.exists())
            with Image.open(dest) as image:
                self.assertEqual(image.size, FRAME_SIZE)
                self.assertEqual(image.mode, "RGB")
            sidecar = json.loads(dest.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["parent"], "02-assets/scenes/granary/master.jpg")
            self.assertEqual(sidecar["shot"], "SH001")

    def test_labeled_variant_lands_under_ep01_v2(self):
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            parent = prod / "02-assets" / "scenes" / "factory-gate" / "master.jpg"
            _write_rgb(parent, (64, 36), (40, 30, 20))
            src = prod / "src.png"
            Image.new("RGB", (320, 180), (12, 80, 40)).save(src)
            result = place(
                prod,
                "SH001",
                "first",
                src,
                parent="02-assets/scenes/factory-gate/master.jpg",
                episode="ep01-v2",
            )
            dest = prod / result["dest"]
            self.assertEqual(result["dest"], "04-frames/ep01-v2/SH001.jpg")
            self.assertTrue(dest.exists())
            self.assertFalse((prod / "04-frames" / "SH001.jpg").exists())
            with Image.open(dest) as image:
                self.assertEqual(image.size, FRAME_SIZE)


class PackagePlanHonorTests(unittest.TestCase):
    def test_explicit_first_last_wins_on_static_insert(self):
        from director.pipeline import package_gen_mode

        mode, plan = package_gen_mode(
            {"shot_size": "insert", "move_type": "static"},
            {"coverage_type": "insert", "scale": "insert", "move_type": "static", "keyframe_plan": "first_last"},
            {"first_last_frame": True},
        )
        self.assertEqual(plan, "first_last")
        self.assertEqual(mode, "flf2v")


class CompileEpisodeTwoTests(unittest.TestCase):
    def test_ep02_table_validates_and_packages_keep_empty_keyframe_files(self):
        errors, warnings, table = validate_episode(PROD, 2)
        self.assertEqual(errors, [], msg=errors)
        self.assertGreaterEqual(len(table.get("shots") or []), 20)
        result = compile_episode(PROD, 2, confirm=True, write=False)
        self.assertTrue(result["ok"], result.get("errors"))
        packages = result["packages"]["packages"]
        self.assertEqual(len(packages), len(table["shots"]))
        for pkg in packages:
            self.assertEqual(pkg.get("keyframe_files"), [])
            self.assertTrue(pkg.get("confirmed"))
            self.assertEqual(pkg.get("prompt_language"), "zh")
            self.assertTrue(pkg.get("image_prompt"))
            self.assertTrue(pkg.get("motion_prompt"))
            self.assertIn(pkg.get("gen_mode"), {"i2v_first", "flf2v", "video_extend"})
        self.assertTrue(result["confirmed"])
        self.assertNotIn("写实历史轻度美化", packages[0]["image_prompt"])
        self.assertIn("数字电影感", packages[0]["image_prompt"])


class SeriesVideoReadyTests(unittest.TestCase):
    def test_every_episode_has_confirmed_packages_and_16x9_frames(self):
        from PIL import Image
        from director.pipeline import episode_artifact_name, packages_confirmed, read_artifact, validate_keyframes

        for episode in range(1, 9):
            table_name = "shot_list.json" if episode == 1 else f"shot_list.ep{episode:02d}.json"
            pkg_name = episode_artifact_name("gen_packages.json", episode)
            kf_name = episode_artifact_name("keyframes.json", episode)
            table = read_artifact(PROD, table_name)
            packages = read_artifact(PROD, pkg_name)
            keyframes = read_artifact(PROD, kf_name)
            self.assertTrue(table.get("shots"), f"ep{episode} shot list empty")
            self.assertTrue(packages_confirmed(packages), f"ep{episode} packages not confirmed")
            for pkg in packages.get("packages") or []:
                self.assertEqual(pkg.get("keyframe_files"), [])
            errors = validate_keyframes(
                keyframes,
                packages=packages,
                specs=read_artifact(PROD, episode_artifact_name("shot_specs.json", episode) if episode > 1 else "shot_specs.json"),
                table=table,
                prod=PROD,
            )
            self.assertEqual(errors, [], msg=f"ep{episode}: {errors[:5]}")
            for item in keyframes.get("keyframes") or []:
                first = PROD / item["first_frame_file"]
                self.assertTrue(first.exists(), item["first_frame_file"])
                with Image.open(first) as image:
                    self.assertEqual(image.size, FRAME_SIZE)
                    self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
