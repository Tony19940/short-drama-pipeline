#!/usr/bin/env python3
"""Batch B/C audit: timing, setup anchors, refs, QC layers, extend, policy."""

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

from director.animatic import (  # noqa: E402
    animatic_approval_status,
    animatic_input_fingerprint,
    require_animatic_approval,
    write_animatic_approval,
)
from director.prompts import (  # noqa: E402
    action_timing_zh,
    assemble_motion_prompt,
    compile_keyframe_prompt_zh,
    shot_dialogue_items,
)
from director.qc_layers import evaluate_clip_layers, layers_allow_auto_pass  # noqa: E402
from director.setup_anchors import camera_projection_changed, setup_id_of  # noqa: E402
from director.shot_table import orientation_errors  # noqa: E402
from director.show_policy import ShowPolicy, load_show_policy, model_capabilities, still_style_opener  # noqa: E402
from director.takes import EditSegment, Take, persist_take, take_from_render  # noqa: E402
from director.vendor_request import seedance_mode_for_task  # noqa: E402
from place_codex_frame import AspectMismatchError, write_frame_jpeg  # noqa: E402
from video_backends.seedance_ark import SeedanceArk  # noqa: E402


def _jpg(path: Path, size=(128, 72), color=(20, 30, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


class ActionTiming(unittest.TestCase):
    def test_eight_seconds_is_not_one_point_five_plus_hold(self) -> None:
        text, beats = action_timing_zh("她伸手去够钥匙", "手已伸出", "钥匙仍在地上", 8)
        self.assertEqual(beats[0]["to_sec"], 3.0)
        self.assertIn("0.0–3s", text)
        self.assertNotIn("0.0–1.5s", text)
        self.assertIn("3–8s", text)

    def test_director_plan_wins(self) -> None:
        shot = {
            "t0_phase": "hold",
            "action_timing": [
                {"from_sec": 0.0, "to_sec": 5.0, "text": "先听完那句否认"},
                {"from_sec": 5.0, "to_sec": 8.0, "text": "眼下移到证物"},
            ],
        }
        text, beats = action_timing_zh("发现证物", "视线还在脸上", "眼已下移", 8, shot=shot)
        self.assertTrue(text.startswith("0.0s 先停住"))
        self.assertEqual([b["from_sec"] for b in beats], [0.0, 5.0])
        self.assertIn("先听完那句否认", text)

    def test_four_second_default_still_scales_to_one_five(self) -> None:
        text, beats = action_timing_zh("春安把旧钥匙扔到琳脚边", "钥匙仍在春安手里", "钥匙停在琳脚边地上", 4)
        self.assertEqual(beats[0]["to_sec"], 1.5)
        self.assertIn("0.0–1.5s", text)


class DialogueIdentity(unittest.TestCase):
    def test_same_text_different_line_id_is_kept(self) -> None:
        items = shot_dialogue_items(
            {},
            {
                "dialogue_ref": [
                    {"line_id": "a1", "character": "琳", "line": "不是我拿的。"},
                    {"line_id": "a2", "character": "春安", "line": "不是我拿的。"},
                    {"line_id": "a3", "character": "波帕", "line": "第三句。"},
                ]
            },
        )
        self.assertEqual(len(items), 3)
        self.assertEqual([item["line_id"] for item in items], ["a1", "a2", "a3"])


class PromptTrim(unittest.TestCase):
    def test_continuity_survives_trim(self) -> None:
        result = assemble_motion_prompt(
            [
                {"tag": "geo", "text": "【空间锁】" + "门房在画左，" * 40 + "。"},
                {"tag": "lock", "text": "【人物锁】琳：" + "瘦小缩肩，" * 20 + "100% 以参考图为准。", "short": "【人物锁】琳：100% 以参考图为准。"},
                {"tag": "timing", "text": "【动作时间轴】0.0–3s：听。"},
                {"tag": "continuity", "text": "【连戏】琳穿清洁围裙，胸前 T-0417。"},
                {"tag": "style", "text": "数字电影 CG 质感。"},
                {"tag": "audio", "text": "【声音】无音乐。"},
            ],
            limit=500,
        )
        self.assertNotIn("continuity", result["dropped"])
        self.assertIn("【连戏】琳穿清洁围裙，胸前 T-0417。", result["prompt"])


class AspectAndStyle(unittest.TestCase):
    def test_keyframe_follows_project_aspect_and_style(self) -> None:
        wide_cg = compile_keyframe_prompt_zh({"in_from": "站着", "aspect_ratio": "16:9", "art_direction": "digital_cg"})
        tall_real = compile_keyframe_prompt_zh({"in_from": "站着", "aspect_ratio": "9:16", "art_direction": "photoreal"})
        self.assertIn("16:9", wide_cg)
        self.assertIn("数字电影 CG", wide_cg)
        self.assertIn("9:16", tall_real)
        self.assertIn("电影写实静帧", tall_real)
        self.assertNotIn("16:9", tall_real)

    def test_place_refuses_stretch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "square.jpg"
            dest = Path(raw) / "out.jpg"
            _jpg(src, size=(100, 100))
            with self.assertRaises(AspectMismatchError):
                write_frame_jpeg(src, dest, aspect="16:9", crop=False)
            write_frame_jpeg(src, dest, aspect="16:9", crop=True)
            with Image.open(dest) as image:
                self.assertEqual(image.size, (1672, 941))
            portrait = Path(raw) / "p.jpg"
            dest_p = Path(raw) / "out-p.jpg"
            _jpg(portrait, size=(72, 128))
            write_frame_jpeg(portrait, dest_p, aspect="9:16", crop=False)
            with Image.open(dest_p) as image:
                self.assertEqual(image.size, (941, 1672))


class SetupAnchors(unittest.TestCase):
    def test_reverse_is_a_new_setup(self) -> None:
        front = {"scene_id": "SC01", "coverage_type": "single", "camera_side": "front", "scale": "medium"}
        reverse = {"scene_id": "SC01", "coverage_type": "reverse", "camera_side": "behind", "scale": "medium"}
        self.assertTrue(camera_projection_changed(front, reverse))
        self.assertNotEqual(setup_id_of(front), setup_id_of(reverse))

    def test_reverse_facing_flip_is_not_an_error(self) -> None:
        errors = orientation_errors(
            [
                {
                    "shot_id": "SH001",
                    "scene_id": "SC01",
                    "coverage_type": "single",
                    "camera_side": "front",
                    "body_facing": "朝镜头",
                    "one_action": "琳看着春安",
                },
                {
                    "shot_id": "SH002",
                    "scene_id": "SC01",
                    "coverage_type": "reverse",
                    "camera_side": "behind",
                    "body_facing": "背对镜头",
                    "one_action": "反打春安听着",
                },
            ]
        )
        self.assertFalse(any("facing flips" in e for e in errors), errors)

    def test_same_setup_flip_without_turn_is_error(self) -> None:
        errors = orientation_errors(
            [
                {
                    "shot_id": "SH001",
                    "scene_id": "SC01",
                    "coverage_type": "single",
                    "camera_side": "front",
                    "body_facing": "朝镜头",
                    "one_action": "琳看着春安",
                },
                {
                    "shot_id": "SH002",
                    "scene_id": "SC01",
                    "coverage_type": "single",
                    "camera_side": "front",
                    "body_facing": "背对镜头",
                    "one_action": "琳仍站着",
                },
            ]
        )
        self.assertTrue(any("facing flips" in e for e in errors), errors)


class StillBudget(unittest.TestCase):
    def test_five_people_and_prop_reports_drop(self) -> None:
        from director.codex_stills import last_still_pack_report, pack_codex_still_refs

        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            parent = "02-assets/scenes/line/master.jpg"
            _jpg(prod / parent)
            assets = {"assets": [{"asset_id": "LOC", "type": "location", "name": "line", "file": parent, "binds_to": "line"}]}
            chars = {}
            for i, name in enumerate(["rin", "bopha", "chanthy", "sannang", "vithu"], 1):
                master = f"02-assets/characters/{name}/master.jpg"
                face = f"02-assets/characters/{name}/face.jpg"
                _jpg(prod / master, color=(10 * i, 20, 30))
                _jpg(prod / face, color=(10 * i, 80, 30))
                assets["assets"].append({
                    "asset_id": f"CHAR_{name.upper()}",
                    "type": "character",
                    "name": name,
                    "binds_to": name,
                    "file": master,
                })
                chars[name] = {"costume": "base", "in_frame": True, "carrying": ["old-key"] if name == "rin" else []}
            prop = "02-assets/props/old-key/master.jpg"
            _jpg(prod / prop)
            assets["assets"].append({
                "asset_id": "PROP_OLD_KEY",
                "type": "prop",
                "name": "old-key",
                "binds_to": "old-key",
                "file": prop,
            })
            files = pack_codex_still_refs(
                prod,
                parent=parent,
                state={"characters": chars, "props": ["old-key"], "location": ""},
                assets=assets,
                max_refs=5,
            )
            report = last_still_pack_report()
            self.assertEqual(files[0], parent)
            self.assertIn(prop, files)
            self.assertTrue(report["dropped"], report)
            self.assertTrue(report["risk"])


class QcLayers(unittest.TestCase):
    def test_text_pass_is_not_visual_pass(self) -> None:
        layers = evaluate_clip_layers(
            technical_ok=True,
            text_notes=[],
            visual_review={"status": "pass"},
            media_hash="aaa",
        )
        self.assertEqual(layers["text"]["status"], "pass")
        self.assertEqual(layers["visual"]["status"], "unknown")
        self.assertFalse(layers_allow_auto_pass(layers))

    def test_bound_visual_review_can_pass(self) -> None:
        layers = evaluate_clip_layers(
            technical_ok=True,
            visual_review={"status": "pass", "image_sha256": "abc"},
            media_hash="abc",
        )
        self.assertEqual(layers["visual"]["status"], "pass")
        self.assertTrue(layers_allow_auto_pass(layers))

    def test_vlm_score_is_not_automatic_pass(self) -> None:
        layers = evaluate_clip_layers(technical_ok=True, vlm_score=0.99, media_hash="x")
        self.assertNotEqual(layers["visual"]["status"], "pass")


class AnimaticApproval(unittest.TestCase):
    def test_approval_binds_to_input_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            (prod / "03-storyboard").mkdir()
            (prod / "04-frames").mkdir()
            _jpg(prod / "04-frames" / "SH001.jpg")
            (prod / ".pipeline").mkdir()
            (prod / ".pipeline" / "shot_list.json").write_text(
                json.dumps({
                    "schema": "shot-table-v2",
                    "shots": [{"shot_id": "SH001", "duration_sec": 4, "one_action": "站着"}],
                }),
                encoding="utf-8",
            )
            first = animatic_input_fingerprint(prod, 1)
            write_animatic_approval(prod, 1, reviewer="tonyteacher")
            self.assertTrue(animatic_approval_status(prod, 1)["ok"])
            require_animatic_approval(prod, 1)
            _jpg(prod / "04-frames" / "SH001.jpg", color=(9, 9, 9))
            status = animatic_approval_status(prod, 1)
            self.assertTrue(status["stale"])
            self.assertNotEqual(status["current"], first)
            with self.assertRaises(PermissionError):
                require_animatic_approval(prod, 1)


class SeedanceTasks(unittest.TestCase):
    def test_extend_payload_uses_source_video(self) -> None:
        self.assertEqual(seedance_mode_for_task("extend"), "extend")
        old = os.environ.get("ARK_API_KEY")
        os.environ["ARK_API_KEY"] = old or "test-key"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "a.jpg"
                video = Path(tmp) / "src.mp4"
                Image.new("RGB", (64, 36), (1, 2, 3)).save(image)
                video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"clip")
                backend = SeedanceArk(model="doubao-seedance-2-5-260628", min_duration=4, max_duration=30)
                payload = backend.build_payload(image, "接着演", 8, mode="extend", source_video=video)
                roles = [item.get("role") for item in payload["content"] if isinstance(item, dict)]
                self.assertIn("reference_video", roles)
                self.assertNotIn("first_frame", roles)
                self.assertEqual(payload["omni_reference_task_type"], "extend")
                self.assertEqual(payload["ratio"], "adaptive")
                self.assertEqual(payload["duration"], 8)
                edit = backend.build_payload(image, "修这一段", 4, mode="edit", source_video=video)
                self.assertEqual(edit["omni_reference_task_type"], "edit")
                self.assertEqual(edit["duration"], -1)
                ref = backend.build_payload(image, "参考", 4, mode="reference", refs=[image])
                self.assertEqual(ref["omni_reference_task_type"], "reference")
                self.assertNotIn("first_frame", [item.get("role") for item in ref["content"]])
        finally:
            if old is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = old

    def test_stale_ticket_does_not_reuse(self) -> None:
        old = os.environ.get("ARK_API_KEY")
        os.environ["ARK_API_KEY"] = old or "test-key"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "SH001.mp4"
                dest.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"oldclipxxxx")
                ticket = dest.with_suffix(dest.suffix + ".ark-task.json")
                ticket.write_text(json.dumps({"task_id": "cgt-old", "request_hash": "deadbeef"}), encoding="utf-8")
                first = Path(tmp) / "first.jpg"
                first.write_bytes(b"newbytes")
                backend = SeedanceArk()
                called = {"submit": 0}

                def submit(*args, **kwargs):
                    called["submit"] += 1
                    return "cgt-new"

                backend.submit = submit  # type: ignore[method-assign]
                backend.wait_url = lambda task_id: "http://example.local/x.mp4"  # type: ignore[method-assign]
                backend.download = lambda url, path: path.write_bytes(b"\x00\x00\x00\x18ftypisomnew")  # type: ignore[method-assign]
                backend.render(first, "new prompt", 4, dest)
                self.assertEqual(called["submit"], 1)
                stored = json.loads(ticket.read_text(encoding="utf-8"))
                self.assertEqual(stored["task_id"], "cgt-new")
                self.assertNotEqual(stored.get("request_hash"), "deadbeef")
        finally:
            if old is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = old


class PolicyAndTakes(unittest.TestCase):
    def test_capabilities_are_not_show_policy(self) -> None:
        caps = model_capabilities("seedance_2_5")
        self.assertEqual(caps.max_shot_sec, 30)
        self.assertIn("extend", caps.task_kinds)
        policy = ShowPolicy(production_id="demo", aspect="9:16", art_direction="photoreal")
        self.assertEqual(policy.aspect, "9:16")
        self.assertIn("9:16", still_style_opener(policy.aspect, policy.art_direction))
        self.assertIn("16:9", caps.aspects)
        self.assertNotEqual(policy.art_direction, "digital_cg")

    def test_take_and_edit_segment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            prod = Path(raw)
            dest = prod / "05-shots" / "SH001.mp4"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"\x00\x00\x00\x18ftypisomtake")
            take = persist_take(prod, take_from_render(shot_id="SH001", dest=dest, request_hash="abc123", task_id="cgt-1"))
            self.assertEqual(take.shot_id, "SH001")
            self.assertTrue(take.media_hash)
            seg = EditSegment("seg-1", take.take_id, "SH001", 0.0, 2.5)
            self.assertEqual(seg.out_sec, 2.5)
            self.assertLess(seg.out_sec, 4.0)


if __name__ == "__main__":
    unittest.main()
