#!/usr/bin/env python3
"""Director-layer gates, parent stills, I2V source, queued GPU jobs."""

from __future__ import annotations

import json
import subprocess
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from director.frames import generate_still, resolve_asset_parent, resolve_shot_parent  # noqa: E402
from director.gates import (  # noqa: E402
    i2v_source,
    ken_burns_blocked,
    lock_gate,
    parent_still,
    run_check,
    snapshot,
)
from director.jobs import assemble_episode, enqueue_render, gpu_configured  # noqa: E402
from director.production import render_blocking, save_shots  # noqa: E402


PROD = ROOT / "productions" / "003-sreymom-engagement"


class DirectorTests(unittest.TestCase):
    def test_003_check_prod_passes(self) -> None:
        result = run_check(PROD)
        self.assertTrue(result["ok"], result["stderr"] or result["stdout"])

    def test_parent_still_opening_uses_blocking(self) -> None:
        shots = json.loads((PROD / "03-storyboard" / "shots.json").read_text())["shots"]
        parent = parent_still(PROD, shots[0], shots)
        self.assertEqual(parent["kind"], "blocking")
        self.assertTrue(parent["exists"])
        self.assertIn("blocking", parent["path"])

    def test_continue_without_overlap_does_not_use_last_frame(self) -> None:
        shots = json.loads((PROD / "03-storyboard" / "shots.json").read_text())["shots"]
        sh002 = next(s for s in shots if s["id"] == "SH002")
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            last = prod / "04-frames" / "SH001-last.jpg"
            last.write_bytes((prod / "04-frames" / "SH001.jpg").read_bytes())
            source = i2v_source(prod, sh002, shots)
            self.assertEqual(source["kind"], "designed_frame")
            self.assertIn("另一人", source["reason"])

    def test_continue_with_overlap_uses_last_frame(self) -> None:
        shots = json.loads((PROD / "03-storyboard" / "shots.json").read_text())["shots"]
        sh006 = next(s for s in shots if s["id"] == "SH006")
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            last = prod / "04-frames" / "SH005-last.jpg"
            last.write_bytes((prod / "04-frames" / "SH005.jpg").read_bytes())
            # SH006 is a coverage cut (master -> single); designed frame wins.
            source = i2v_source(prod, sh006, shots)
            self.assertEqual(source["kind"], "designed_frame")
            self.assertTrue(source["path"].endswith("SH006.jpg"))
            # Same setup + overlap still eats the previous last frame.
            data = json.loads((prod / "03-storyboard" / "shots.json").read_text())
            data["shots"] = shots
            prev = next(s for s in data["shots"] if s["id"] == "SH005")
            sh006["setup"] = prev["setup"]
            source = i2v_source(prod, sh006, data["shots"])
            self.assertEqual(source["kind"], "last_frame")
            self.assertTrue(source["path"].endswith("SH005-last.jpg"))

    def test_004_coverage_cut_uses_new_start_frame(self) -> None:
        prod = ROOT / "productions" / "004-yuye-jinlian"
        shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
        sh002 = next(s for s in shots if s["id"] == "SH002")
        sh007 = next(s for s in shots if s["id"] == "SH007")
        sh004 = next(s for s in shots if s["id"] == "SH004")
        self.assertEqual(i2v_source(prod, sh002, shots)["kind"], "designed_frame")
        self.assertTrue(i2v_source(prod, sh002, shots)["path"].endswith("SH002.jpg"))
        self.assertEqual(i2v_source(prod, sh007, shots)["kind"], "designed_frame")
        self.assertTrue(i2v_source(prod, sh007, shots)["path"].endswith("SH007.jpg"))
        self.assertEqual(i2v_source(prod, sh004, shots)["kind"], "designed_frame")
        self.assertTrue(i2v_source(prod, sh004, shots)["path"].endswith("SH004.jpg"))

    def test_missing_blocking_blocks_stage_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director"))
            blocking = prod / "02-assets" / "scenes" / "restaurant-private" / "blocking.jpg"
            blocking.unlink()
            master = prod / "02-assets" / "scenes" / "restaurant-private" / "master.jpg"
            master.unlink()
            with self.assertRaises(PermissionError):
                render_blocking(prod)

    def test_shot_still_missing_parent_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            (prod / "04-frames" / "SH001.jpg").unlink()
            with self.assertRaises(PermissionError):
                resolve_shot_parent(prod, "SH002")

    def test_shot_still_is_edit_from_parent(self) -> None:
        parent = resolve_shot_parent(PROD, "SH002")
        self.assertEqual(parent["kind"], "edit")
        self.assertTrue(parent["path"].endswith("SH001.jpg"))

    def test_master_second_generation_is_edit(self) -> None:
        parent = resolve_asset_parent(PROD, "character", "sreymom", "master")
        self.assertEqual(parent["kind"], "edit")
        self.assertTrue(parent["exists"])

    def test_edit_without_parent_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            generate_still(PROD, target="SH001", prompt="x", mode="edit", parent_rel=None)

    def test_generate_with_parent_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            generate_still(
                PROD,
                target="SH001",
                prompt="x",
                mode="generate",
                parent_rel="04-frames/SH001.jpg",
            )

    def test_render_without_locks_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            with self.assertRaises(PermissionError):
                enqueue_render(prod, ["SH001"])

    def test_render_without_gpu_stays_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            old = os.environ.get("LOCAL_H3_BASE")
            old_ark = os.environ.get("ARK_API_KEY")
            os.environ.pop("LOCAL_H3_BASE", None)
            os.environ.pop("ARK_API_KEY", None)
            try:
                for gate in ("A", "B", "S", "C"):
                    lock_gate(prod, gate, True)
                from director.fingerprint import prepare_render
                from director.jobs import enqueue_render_confirmed

                prepared = prepare_render(prod, ["SH001"])
                job = enqueue_render_confirmed(prod, prepared["fingerprint"], ["SH001"])
                self.assertEqual(job["status"], "queued")
                self.assertFalse(job["gpu"])
                self.assertIn("queued", " ".join(job["log"]).lower())
            finally:
                if old is not None:
                    os.environ["LOCAL_H3_BASE"] = old
                if old_ark is not None:
                    os.environ["ARK_API_KEY"] = old_ark
                else:
                    os.environ.pop("ARK_API_KEY", None)

    def test_ken_burns_not_assemble_path(self) -> None:
        self.assertTrue(ken_burns_blocked(Path("05-shots/SH001.kenburns.mp4")))
        disabled = ROOT / "scripts" / "_disabled" / "stills-to-shots.sh"
        self.assertTrue(disabled.exists())
        self.assertFalse((ROOT / "scripts" / "stills-to-shots.sh").exists())
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director"))
            shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
            for shot in shots:
                (prod / "05-shots" / f"{shot['id']}.mp4").write_bytes(b"not a video")
            (prod / "05-shots" / "SH001.kenburns.mp4").write_bytes(b"not a video")
            with self.assertRaises(PermissionError):
                assemble_episode(prod)

    def test_save_shots_keeps_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            data = json.loads((prod / "03-storyboard" / "shots.json").read_text())
            data["shots"][1]["expression"] = "mocking"
            result = save_shots(prod, data)
            self.assertTrue(result["check"]["ok"], result["check"])


    def test_invalid_shots_roll_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "03-storyboard" / "shots.json").read_text()
            data = json.loads(original)
            data["shots"][1]["new_info"] = data["shots"][0]["new_info"]
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)

    def test_api_health_and_queued_render(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app

        client = TestClient(app)
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        prod = client.get("/api/productions/003-sreymom-engagement")
        self.assertEqual(prod.status_code, 200)
        self.assertEqual(len(prod.json()["gates"]["gates"]), 10)
        blocked = client.post("/api/productions/003-sreymom-engagement/render", json={"shotIds": ["SH001"]})
        self.assertEqual(blocked.status_code, 409)


    def test_get_does_not_create_director_dir(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003-sreymom-engagement"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            import director.paths as paths

            old_root = paths.PRODUCTIONS
            paths.PRODUCTIONS = prod.parent
            try:
                client = TestClient(app)
                res = client.get("/api/productions/003-sreymom-engagement")
                self.assertEqual(res.status_code, 200)
                self.assertFalse((prod / ".director").exists())
            finally:
                paths.PRODUCTIONS = old_root

    def test_mock_gpu_writes_shot_and_last_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            old_gpu = os.environ.get("LOCAL_H3_BASE")
            os.environ["LOCAL_H3_BASE"] = "http://127.0.0.1:9"
            try:
                for gate in ("A", "B", "S", "C"):
                    lock_gate(prod, gate, True)

                def fake_run(cmd, capture_output=True, text=True):
                    dest = prod / "05-shots" / "SH001.mp4"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(b"fake-mp4")
                    last = prod / "04-frames" / "SH001-last.jpg"
                    last.write_bytes((prod / "04-frames" / "SH001.jpg").read_bytes())
                    class R:
                        returncode = 0
                        stdout = "wrote SH001"
                        stderr = ""
                    return R()

                import director.jobs as jobs
                import time
                old_run = jobs.subprocess.run
                jobs.subprocess.run = fake_run
                try:
                    from director.fingerprint import prepare_render
                    from director.jobs import enqueue_render_confirmed

                    prepared = prepare_render(prod, ["SH001"])
                    job = enqueue_render_confirmed(prod, prepared["fingerprint"], ["SH001"])
                    for _ in range(40):
                        data = jobs.load_jobs(prod)
                        current = next(item for item in data["jobs"] if item["id"] == job["id"])
                        if current["status"] in {"ready", "failed"}:
                            job = current
                            break
                        time.sleep(0.05)
                    self.assertEqual(job["status"], "ready", job)
                    self.assertTrue((prod / "05-shots" / "SH001.mp4").exists())
                    self.assertTrue((prod / "04-frames" / "SH001-last.jpg").exists())
                finally:
                    jobs.subprocess.run = old_run
            finally:
                if old_gpu is None:
                    os.environ.pop("LOCAL_H3_BASE", None)
                else:
                    os.environ["LOCAL_H3_BASE"] = old_gpu



    def test_video_prompt_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "03-storyboard" / "shots.json").read_text()
            data = json.loads(original)
            data["shots"][1].pop("video_prompt")
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)

    def test_line_cannot_enter_video_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "03-storyboard" / "shots.json").read_text()
            data = json.loads(original)
            data["shots"][1]["video_prompt"] += data["shots"][1]["line"]
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)

    def test_static_cannot_orbit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "03-storyboard" / "shots.json").read_text()
            data = json.loads(original)
            data["shots"][0]["camera"] = "orbit around the table"
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)

    def test_new_frame_without_sheet_rejected(self) -> None:
        from director.frames import lock_candidate, upload_candidate
        from director.prompts import missing_sheets

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
            sh002 = next(s for s in shots if s["id"] == "SH002")
            self.assertIn("sreypov", missing_sheets(prod, sh002))
            for gate in ("A", "B", "S", "C"):
                lock_gate(prod, gate, True)
            created = upload_candidate(prod, "SH002", "SH002.jpg", b"fake-jpg", "04-frames/SH001.jpg")
            with self.assertRaises(PermissionError):
                lock_candidate(prod, created["id"], "04-frames/SH002.jpg")
            self.assertTrue((prod / "04-frames" / "SH002.jpg").exists())

    def test_front_and_sheet_edit_from_master(self) -> None:
        front = resolve_asset_parent(PROD, "character", "sreymom", "front")
        sheet = resolve_asset_parent(PROD, "character", "sreymom", "sheet")
        self.assertEqual(front["kind"], "edit")
        self.assertTrue(front["path"].endswith("master.jpg"))
        self.assertEqual(sheet["kind"], "edit")

    def test_inbox_image_becomes_candidate_not_locked_frame(self) -> None:
        from director.inbox import scan_inbox, task_for_shot
        from director.paths import director_dir

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "04-frames" / "SH002.jpg").read_bytes()
            task_for_shot(prod, "SH002")
            inbox = director_dir(prod, create=True) / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / "SH002.jpg").write_bytes(b"inbox-candidate")
            result = scan_inbox(prod)
            self.assertEqual(len(result["ingested"]), 1)
            self.assertEqual((prod / "04-frames" / "SH002.jpg").read_bytes(), original)
            candidate = director_dir(prod) / "candidates" / result["ingested"][0]["candidate"]
            self.assertTrue(candidate.exists())
            self.assertEqual(candidate.read_bytes(), b"inbox-candidate")

    def test_compile_prompt_keeps_dialogue_out(self) -> None:
        from director.prompts import compile_h3_fields, compile_video_prompt

        shots = json.loads((PROD / "03-storyboard" / "shots.json").read_text())["shots"]
        sh002 = next(s for s in shots if s["id"] == "SH002")
        compiled = compile_video_prompt(sh002)
        self.assertIn("slow push", compiled.lower())
        self.assertNotIn("工厂妹", compiled)
        self.assertIn("No spoken dialogue", compiled)
        self.assertIn("integrated_multimodal_description:", compiled)
        self.assertIn("overall_soundscape:", compiled)
        self.assertIn("non_diegetic_music: N/A", compiled)
        self.assertNotIn(sh002["line"], compiled)
        fields = compile_h3_fields(sh002)
        self.assertEqual(fields["non_diegetic_music"], "N/A")
        self.assertTrue(fields["overall_soundscape"])
        self.assertIn("Stay inside the same room", compiled)
        self.assertIn("this private dining room", compiled.lower())
        self.assertTrue(compiled.startswith("For the target video, at 0.00 seconds"))
        self.assertIn("<Picture 1>", compiled)
        self.assertIn("[Shot 1]", compiled)
        self.assertIn("one body beat", compiled.lower())
        self.assertLess(compiled.index("0.00 seconds"), compiled.index("integrated_multimodal_description:"))

    def test_h3_alignment_end_frame_and_identity_refs(self) -> None:
        from director.prompts import compile_h3_fields, compile_video_prompt

        shot = {
            "id": "SH099",
            "seconds": 8,
            "lens": "35mm",
            "setup": "master",
            "move": "static",
            "start": "She stands in the aisle",
            "camera": "locked-off static camera",
            "action": "She takes one step and holds",
            "look": "same factory-floor",
            "scene": "factory-floor",
            "video_prompt": "Vertical 9:16 photoreal Khmer master. One step only.",
            "line": "这句对白不能进画面",
            "end_frame": "04-frames/SH099-end.jpg",
        }
        last_as_end = dict(shot, end_frame="04-frames/SH099-last.jpg")
        i2v = compile_video_prompt(last_as_end)
        self.assertIn("at 0.00 seconds", i2v)
        self.assertNotIn("Picture 2", i2v)
        self.assertNotIn(shot["line"], i2v)

        flf = compile_h3_fields(shot, refs=["02-assets/characters/sophea/sheet.jpg"])
        self.assertIn("8.00-second mark", flf["alignment"])
        self.assertIn("Picture 2", flf["alignment"])
        self.assertIn("designed end pose", flf["integrated_multimodal_description"])
        self.assertIn("identity only", flf["integrated_multimodal_description"])
        self.assertIn("do not replace picture 1", flf["integrated_multimodal_description"].lower())
        self.assertEqual(flf["non_diegetic_music"], "N/A")
        compiled = compile_video_prompt(shot, refs=["02-assets/characters/sophea/sheet.jpg"])
        self.assertTrue(compiled.startswith("How the reference pictures align"))
        self.assertIn("\n\nintegrated_multimodal_description:", compiled)
        self.assertNotIn(shot["line"], compiled)

    def test_004_compile_locks_same_room(self) -> None:
        from director.prompts import compile_video_prompt

        prod = ROOT / "productions" / "004-yuye-jinlian"
        shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
        sh001 = next(s for s in shots if s["id"] == "SH001")
        compiled = compile_video_prompt(sh001)
        self.assertIn("Stay inside the same room", compiled)
        self.assertIn("factory-floor", compiled.lower())
        self.assertNotIn("restaurant", sh001["action"].lower())



    def test_create_production_from_template(self) -> None:
        from director.production import create_production
        import director.paths as paths

        with tempfile.TemporaryDirectory() as tmp:
            dest_root = Path(tmp) / "productions"
            dest_root.mkdir()
            old = paths.PRODUCTIONS
            paths.PRODUCTIONS = dest_root
            try:
                created = create_production("009-demo-reverse", "反推试验")
                dest = dest_root / "009-demo-reverse"
                self.assertEqual(created["id"], "009-demo-reverse")
                self.assertTrue((dest / "01-bible" / "ep01.md").exists())
                self.assertTrue((dest / "00-reverse" / "source").exists())
                self.assertFalse((dest / "03-storyboard" / "shots.draft.json").exists())
            finally:
                paths.PRODUCTIONS = old


    def test_reverse_video_writes_draft_not_official_shots(self) -> None:
        from director.reverse import analyze_production, ingest_video, localize_production

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "009-demo-reverse"
            shutil.copytree(ROOT / "productions" / "_template", prod)
            (prod / "00-reverse" / "source").mkdir(parents=True, exist_ok=True)
            video = Path(tmp) / "cut.mp4"
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=720x1280:d=2.0:r=24",
                "-f", "lavfi", "-i", "color=c=blue:s=720x1280:d=2.5:r=24",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
                str(video),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            official_before = (prod / "03-storyboard" / "shots.json").read_text()
            ingest_video(prod, video, "cut.mp4")
            result = analyze_production(prod, use_grok=False)
            self.assertGreaterEqual(result["analysis"]["shot_count"], 2)
            self.assertTrue((prod / "00-reverse" / "original.shots.json").exists())
            self.assertTrue((prod / "03-storyboard" / "shots.draft.json").exists())
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), official_before)
            localized = localize_production(prod, use_grok=False)
            self.assertIn("sophea", str(localized["draft"]).lower())
            self.assertTrue((prod / "00-reverse" / "localized.shots.json").exists())
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), official_before)
            self.assertNotIn("qipao", (localized["draft"]["shots"][0].get("video_prompt") or "").lower())


    def test_reverse_api_upload_analyze_localize(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app
        import director.paths as paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            productions = root / "productions"
            shutil.copytree(ROOT / "productions" / "_template", productions / "009-demo-reverse")
            video = root / "cut.mp4"
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=720x1280:d=2.0:r=24",
                    "-f", "lavfi", "-i", "color=c=blue:s=720x1280:d=2.5:r=24",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
                    str(video),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            old = paths.PRODUCTIONS
            paths.PRODUCTIONS = productions
            try:
                client = TestClient(app)
                with video.open("rb") as handle:
                    uploaded = client.post(
                        "/api/productions/009-demo-reverse/reverse/upload",
                        files={"file": ("cut.mp4", handle, "video/mp4")},
                    )
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                analyzed = client.post(
                    "/api/productions/009-demo-reverse/reverse/analyze",
                    json={"useGrok": False},
                )
                self.assertEqual(analyzed.status_code, 200, analyzed.text)
                localized = client.post(
                    "/api/productions/009-demo-reverse/reverse/localize",
                    json={"useGrok": False, "brief": "金边制衣厂"},
                )
                self.assertEqual(localized.status_code, 200, localized.text)
                board = client.get("/api/productions/009-demo-reverse/shots/draft")
                self.assertGreaterEqual(len(board.json().get("shots") or []), 2)
                official = client.get("/api/productions/009-demo-reverse/shots")
                self.assertEqual(len(official.json().get("shots") or []), 1)
            finally:
                paths.PRODUCTIONS = old


    def test_default_aspect_is_widescreen(self) -> None:
        from director.defaults import DEFAULT_ASPECT, production_aspect

        self.assertEqual(DEFAULT_ASPECT, "16:9")
        self.assertEqual(production_aspect(), "16:9")
        self.assertEqual(production_aspect(explicit="9:16"), "9:16")
        self.assertEqual(
            production_aspect(ROOT / "productions" / "004-yuye-jinlian"),
            "9:16",
        )
        self.assertEqual(
            production_aspect(ROOT / "productions" / "010-gongpai"),
            "16:9",
        )

    def test_vocab_templates_compile_legal_moves(self) -> None:
        from director.inbox import task_for_asset
        from director.prompts import camera_for_move, compose_video_prompt, character_sheet_prompt, load_template
        from director.scriptwriter import heuristic_package

        self.assertIn("slow push in on one subject", camera_for_move("push"))
        self.assertIn("no orbit", camera_for_move("static"))
        formula = load_template("video-prompt-formula.md")
        self.assertIn("16:9 photoreal Khmer", formula)
        self.assertIn("orbit", load_template("camera-moves.md"))
        prompt = compose_video_prompt(
            {
                "setup": "close",
                "scale": "close",
                "move": "push",
                "lens": "85mm",
                "camera": camera_for_move("push"),
                "action": "start still, perform one body beat (她挽袖), hold the end pose",
                "look": "same factory-floor axis",
            }
        )
        self.assertIn("Widescreen 16:9", prompt)
        self.assertIn("slow push in", prompt)
        self.assertNotIn("orbit the subject", prompt)
        sheet = character_sheet_prompt("sophea", "sheet")
        self.assertIn("Top row", sheet)
        self.assertIn("No new face", sheet)
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                prod,
                ignore=shutil.ignore_patterns(".director"),
            )
            (prod / "02-assets" / "characters" / "sophea" / "master.jpg").write_bytes(b"master")
            task = task_for_asset(prod, "character", "sophea", "sheet")
            self.assertIn("reference sheet", task["prompt"].lower())
            package = heuristic_package(prod)
            first = package["shots"]["shots"][0]
            self.assertIn("Vertical 9:16", first["video_prompt"])
            self.assertIn("locked-off static camera", first["camera"])

    def test_scriptwriter_uses_coverage_and_existing_slugs(self) -> None:

        from director.breakdown import breakdown_package, prompt_has_action
        from director.scriptwriter import parse_coverage_table

        prod = ROOT / "productions" / "004-yuye-jinlian"
        coverage = (prod / "03-storyboard" / "coverage.md").read_text()
        rows = parse_coverage_table(coverage, prod)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["setup"], "master")
        self.assertEqual(rows[1]["move"], "push")
        self.assertEqual(rows[2]["move"], "pull")
        self.assertEqual(rows[-1]["setup"], "insert")
        package = breakdown_package(prod)
        people = {name for shot in package["shots"]["shots"] for name in shot["characters"]}
        self.assertIn("ros", people)
        self.assertNotIn("yeay-ros", people)
        self.assertTrue(str(package["beat_source"]).startswith("coverage.md"))
        shots = package["shots"]["shots"]
        self.assertGreaterEqual(len(shots), 8)
        self.assertLessEqual(len(shots), 16)
        self.assertEqual(package["shots"]["directing"], "scene-rig-v1")
        self.assertTrue(all(shot.get("rig_id") for shot in shots))
        self.assertTrue(all(prompt_has_action(shot["video_prompt"], shot["action"]) for shot in shots))
        self.assertTrue(all(shot.get("shot_job") for shot in shots))
        self.assertFalse(any("holds the look after" in str(shot.get("action") or "") and not shot.get("shot_job") for shot in shots))
        self.assertTrue(all(shot.get("handle") == 2 for shot in shots))

    def test_scriptwriter_writes_draft_not_official(self) -> None:

        from director.scriptwriter import draft_script

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                prod,
                ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"),
            )
            bible = (prod / "01-bible" / "ep01.md").read_text()
            blueprint = (prod / "01-bible" / "blueprint.md").read_text()
            official = prod / "03-storyboard" / "shots.json"
            before = official.read_text() if official.exists() else None
            result = draft_script(prod, use_grok=False)
            self.assertGreaterEqual(result["shot_count"], 3)
            self.assertTrue((prod / "03-storyboard" / "shots.draft.json").exists())
            self.assertTrue((prod / "01-bible" / "blueprint.draft.md").exists())
            self.assertTrue((prod / "03-storyboard" / "voiceover.draft.md").exists())
            self.assertEqual((prod / "01-bible" / "ep01.md").read_text(), bible)
            self.assertEqual((prod / "01-bible" / "blueprint.md").read_text(), blueprint)
            if before is None:
                self.assertFalse(official.exists())
            else:
                self.assertEqual(official.read_text(), before)
            draft = json.loads((prod / "03-storyboard" / "shots.draft.json").read_text())
            first = draft["shots"][0]
            self.assertEqual(first["cut"], "hard")
            self.assertTrue(str(first["derived_from"]).endswith(".blocking"))
            self.assertNotIn("工厂妹", first.get("video_prompt", ""))
            self.assertIn("line", first)
            people = {name for shot in draft["shots"] for name in shot.get("characters") or []}
            self.assertIn("ros", people)
            self.assertNotIn("yeay-ros", people)
            self.assertGreaterEqual(len(draft["shots"]), 8)
            self.assertTrue(all(shot.get("shot_job") for shot in draft["shots"]))
            self.assertTrue(str(result.get("overview", {}).get("beat_source") or "").startswith("coverage.md"))
            self.assertFalse((prod / "02-assets" / "characters" / "yeay-ros").exists() or False)
            # leftover empty folder from older writer should not be reseeded as a real character
            self.assertNotIn("yeay-ros", people)

    def test_breakdown_uses_scene_rigs_and_this_shot_action(self) -> None:
        from director.breakdown import breakdown_package, prompt_has_action

        pkg = breakdown_package(ROOT / "productions" / "005-defeat-named")
        shots = pkg["shots"]["shots"]
        self.assertEqual(pkg["shots"]["directing"], "scene-rig-v1")
        self.assertGreaterEqual(len(shots), 8)
        self.assertLessEqual(len(shots), 16)
        people = [shot for shot in shots if shot.get("setup") != "insert"]
        static = [shot for shot in people if shot.get("move") == "static"]
        self.assertLessEqual(len(static) * 2, len(people))
        actions = [shot["action"] for shot in shots]
        self.assertEqual(len(actions), len(set(actions)))
        spoken_secs = [int(shot["seconds"]) for shot in shots if shot.get("line_kind") in {"dialogue", "inner"}]
        self.assertTrue(spoken_secs)
        self.assertFalse(len(set(spoken_secs)) == 1 and spoken_secs[0] >= 5)
        self.assertTrue(all(shot.get("shot_job") for shot in shots))
        continue_shots = [shot for shot in shots if shot.get("cut") == "continue"]
        self.assertTrue(continue_shots)
        for shot in continue_shots:
            start = shot["start"].lower()
            self.assertTrue(
                "mid-action" in start or "halfway" in start or "already lifting" in start or "already turning" in start,
                shot["start"],
            )
            self.assertNotEqual(start, shot["action"].lower())
        for shot in shots:
            self.assertTrue(shot.get("rig_id"))
            self.assertTrue(prompt_has_action(shot["video_prompt"], shot["action"]))
            self.assertEqual(shot.get("handle"), 2)
            self.assertEqual(shot.get("render_seconds"), int(shot["seconds"]) + 2)
        self.assertTrue(any("oxcart" in shot["action"].lower() for shot in shots))
        self.assertTrue(any("palm-leaf rubbing" in shot["action"].lower() and "banana-leaf" not in shot["action"].lower() for shot in shots))

    def test_scriptwriter_api_does_not_accept_as_official(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app
        import director.paths as paths

        with tempfile.TemporaryDirectory() as tmp:
            productions = Path(tmp) / "productions"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                productions / "004-yuye-jinlian",
                ignore=shutil.ignore_patterns(".director"),
            )
            old = paths.PRODUCTIONS
            paths.PRODUCTIONS = productions
            try:
                client = TestClient(app)
                written = client.post(
                    "/api/productions/004-yuye-jinlian/scriptwriter",
                    json={"useGrok": False},
                )
                self.assertEqual(written.status_code, 200, written.text)
                self.assertGreaterEqual(written.json()["shot_count"], 3)
                official_before = (productions / "004-yuye-jinlian" / "03-storyboard" / "shots.json").read_text()
                official = client.get("/api/productions/004-yuye-jinlian/shots")
                self.assertGreaterEqual(len(official.json().get("shots") or []), 8)
                self.assertEqual(
                    (productions / "004-yuye-jinlian" / "03-storyboard" / "shots.json").read_text(),
                    official_before,
                )
                draft = client.get("/api/productions/004-yuye-jinlian/shots/draft")
                self.assertGreaterEqual(len(draft.json().get("shots") or []), 3)
            finally:
                paths.PRODUCTIONS = old


    def test_004_template_draft_cannot_accept(self) -> None:
        from director.production import accept_shot_draft

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                prod,
                ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"),
            )
            draft_path = prod / "03-storyboard" / "shots.draft.json"
            data = json.loads(draft_path.read_text())
            data["shots"][0]["action"] = "start still, perform one body beat (她要丢工), hold the end pose"
            data["shots"][0]["video_prompt"] += " 她要丢工"
            draft_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            official_before = (prod / "03-storyboard" / "shots.json").read_text()
            with self.assertRaises(PermissionError):
                accept_shot_draft(prod)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), official_before)

    def test_004_rewritten_draft_accepts_in_temp(self) -> None:
        from director.production import accept_shot_draft

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                prod,
                ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"),
            )
            result = accept_shot_draft(prod)
            self.assertTrue(result["check"]["ok"], result["check"])
            self.assertTrue((prod / "03-storyboard" / "shots.json").exists())
            self.assertTrue((ROOT / "productions" / "004-yuye-jinlian" / "03-storyboard" / "shots.json").exists())
            self.assertNotEqual(
                (prod / "03-storyboard" / "shots.json").resolve(),
                (ROOT / "productions" / "004-yuye-jinlian" / "03-storyboard" / "shots.json").resolve(),
            )

    def test_review_draft_does_not_write_shots(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app
        import director.paths as paths

        with tempfile.TemporaryDirectory() as tmp:
            productions = Path(tmp) / "productions"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                productions / "004-yuye-jinlian",
                ignore=shutil.ignore_patterns(".director"),
            )
            old = paths.PRODUCTIONS
            paths.PRODUCTIONS = productions
            try:
                client = TestClient(app)
                reviewed = client.post(
                    "/api/productions/004-yuye-jinlian/review-draft",
                    json={"source": "draft"},
                )
                self.assertEqual(reviewed.status_code, 200, reviewed.text)
                self.assertIn(reviewed.json()["verdict"], {"APPROVE", "APPROVE_WITH_NOTES", "REVISE"})
                official_before = (productions / "004-yuye-jinlian" / "03-storyboard" / "shots.json").read_text()
                self.assertTrue((productions / "004-yuye-jinlian" / "03-storyboard" / "review.draft.md").exists())
                self.assertEqual(
                    (productions / "004-yuye-jinlian" / "03-storyboard" / "shots.json").read_text(),
                    official_before,
                )
                accepted = client.post("/api/productions/004-yuye-jinlian/shots/draft/accept")
                self.assertEqual(accepted.status_code, 200, accepted.text)
            finally:
                paths.PRODUCTIONS = old
            self.assertTrue((ROOT / "productions" / "004-yuye-jinlian" / "03-storyboard" / "shots.json").exists())

    def test_render_requires_fresh_fingerprint(self) -> None:
        from director.fingerprint import prepare_render
        from director.jobs import enqueue_render_confirmed

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            old = os.environ.get("LOCAL_H3_BASE")
            old_ark = os.environ.get("ARK_API_KEY")
            os.environ.pop("LOCAL_H3_BASE", None)
            os.environ.pop("ARK_API_KEY", None)
            try:
                for gate in ("A", "B", "S", "C"):
                    lock_gate(prod, gate, True)
                with self.assertRaises(PermissionError):
                    enqueue_render_confirmed(prod, None, ["SH001"])
                prepared = prepare_render(prod, ["SH001"])
                data = json.loads((prod / "03-storyboard" / "shots.json").read_text())
                data["shots"][0]["video_prompt"] += " extra still hold"
                (prod / "03-storyboard" / "shots.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                with self.assertRaises(PermissionError):
                    enqueue_render_confirmed(prod, prepared["fingerprint"], ["SH001"])
                lock_gate(prod, "C", True)
                fresh = prepare_render(prod, ["SH001"])
                job = enqueue_render_confirmed(prod, fresh["fingerprint"], ["SH001"])
                self.assertEqual(job["status"], "queued")
                with self.assertRaises(PermissionError):
                    enqueue_render_confirmed(prod, fresh["fingerprint"], ["SH001"])
            finally:
                if old is not None:
                    os.environ["LOCAL_H3_BASE"] = old
                if old_ark is not None:
                    os.environ["ARK_API_KEY"] = old_ark
                else:
                    os.environ.pop("ARK_API_KEY", None)

    def test_review_contract_fails_without_vo_or_audio(self) -> None:
        from director.review_contract import evaluate_review_contract, freeze_review_contract

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            freeze_review_contract(prod, ["SH001"])
            result = evaluate_review_contract(prod)
            self.assertEqual(result["required"], "fail")
            self.assertTrue(any("preview" in item or "mp4" in item for item in result["failures"]))
            (prod / "05-shots").mkdir(parents=True, exist_ok=True)
            (prod / "06-export").mkdir(parents=True, exist_ok=True)
            (prod / "05-shots" / "SH001.mp4").write_bytes(b"not a video")
            ken = prod / "06-export" / "preview-kenburns-vo.mp4"
            ken.write_bytes(b"not a video")
            freeze_review_contract(prod, ["SH001"])
            result = evaluate_review_contract(prod, ken)
            self.assertEqual(result["required"], "fail")
            self.assertTrue(any("Ken Burns" in item for item in result["failures"]))
            silent = prod / "06-export" / "preview-partial-vo.mp4"
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=1:r=24",
                    str(silent),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = evaluate_review_contract(prod, silent)
            self.assertEqual(result["required"], "fail")
            self.assertTrue(any("音轨" in item for item in result["failures"]))

    def test_codex_asset_lands_in_folder_and_studio_sees_it(self) -> None:
        from PIL import Image
        from director.production import assets
        from director.paths import media_url
        from place_codex_asset import place

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(
                ROOT / "productions" / "004-yuye-jinlian",
                prod,
                ignore=shutil.ignore_patterns(".director"),
            )
            src = Path(tmp) / "codex-face.png"
            Image.new("RGB", (64, 112), (180, 40, 40)).save(src)
            result = place(prod, "character", "sophea", "face", src)
            self.assertEqual(result["dest"], "02-assets/characters/sophea/face.jpg")
            self.assertTrue((prod / result["dest"]).exists())
            self.assertTrue(result["previous"])
            self.assertTrue((prod / result["previous"]).exists())
            data = assets(prod)
            sophea = next(item for item in data["characters"] if item["id"] == "sophea")
            self.assertTrue(sophea["face_url"].startswith("/media/004/02-assets/characters/sophea/face.jpg?v="))
            bell = next(item for item in data["props"] if "bell" in item["id"])
            self.assertTrue(bell["master_url"])
    def test_codex_frame_lands_in_04_frames(self) -> None:
        from PIL import Image
        from place_codex_frame import place

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "009"
            (prod / "04-frames").mkdir(parents=True)
            plate = prod / "02-assets" / "scenes" / "modern-channel" / "master.jpg"
            plate.parent.mkdir(parents=True)
            Image.new("RGB", (128, 72), (10, 10, 10)).save(plate)
            src = Path(tmp) / "codex-sh001.png"
            Image.new("RGB", (128, 72), (40, 80, 40)).save(src)
            with self.assertRaises(ValueError):
                place(prod, "SH001", "first", src)
            with self.assertRaises(FileNotFoundError):
                place(prod, "SH001", "first", src, parent="02-assets/scenes/nowhere/master.jpg")
            with self.assertRaises(ValueError):
                place(prod, "SH001", "first", src, parent="03-storyboard/whatever.jpg")
            result = place(prod, "SH001", "first", src, parent="02-assets/scenes/modern-channel/master.jpg")
            self.assertEqual(result["dest"], "04-frames/SH001.jpg")
            self.assertTrue((prod / result["dest"]).exists())
            self.assertIsNone(result["previous"])
            meta = json.loads((prod / "04-frames" / "SH001.json").read_text())
            self.assertEqual(meta["parent"], "02-assets/scenes/modern-channel/master.jpg")
            self.assertEqual(len(meta["src_sha256"]), 64)
            again = Path(tmp) / "codex-sh001b.png"
            Image.new("RGB", (128, 72), (80, 40, 40)).save(again)
            second = place(prod, "SH001", "first", again, parent="02-assets/scenes/modern-channel/master.jpg")
            self.assertTrue(second["previous"])
            self.assertTrue((prod / "04-frames" / "SH001-v1.json").exists())
            self.assertEqual(json.loads((prod / "04-frames" / "SH001.json").read_text())["previous"], "04-frames/SH001-v1.jpg")
            with self.assertRaises(FileNotFoundError):
                place(prod, "SH004", "last", src)
            place(prod, "SH004", "first", src, parent="04-frames/SH001.jpg")
            last = place(prod, "SH004", "last", src)
            self.assertEqual(last["dest"], "04-frames/SH004-last.jpg")
            self.assertEqual(last["parent"], "04-frames/SH004.jpg")

    def test_codex_frame_defaults_to_prev_first_and_rejects_master(self) -> None:
        from PIL import Image
        from director.pipeline import write_artifact
        from place_codex_frame import parent_chain_errors, place

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "010"
            (prod / "04-frames").mkdir(parents=True)
            plate = prod / "02-assets" / "scenes" / "storeroom" / "master.jpg"
            plate.parent.mkdir(parents=True)
            Image.new("RGB", (128, 72), (10, 10, 10)).save(plate)
            src = Path(tmp) / "frame.png"
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
            place(prod, "SH007", "first", src, parent="02-assets/scenes/storeroom/master.jpg")
            place(prod, "SH007", "last", src)
            landed = place(prod, "SH008", "first", src)
            self.assertEqual(landed["parent"], "04-frames/SH007-last.jpg")
            with self.assertRaises(ValueError):
                place(prod, "SH008", "first", src, parent="02-assets/scenes/storeroom/master.jpg")
            self.assertEqual(parent_chain_errors(prod), [])
            meta = json.loads((prod / "04-frames" / "SH008.json").read_text(encoding="utf-8"))
            meta["parent"] = "02-assets/scenes/storeroom/master.jpg"
            meta["allow_master"] = False
            (prod / "04-frames" / "SH008.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertTrue(any("SH008 parent is scene master" in e for e in parent_chain_errors(prod)))
            allowed = place(prod, "SH008", "first", src, parent="02-assets/scenes/storeroom/master.jpg", allow_master=True)
            self.assertEqual(allowed["parent"], "02-assets/scenes/storeroom/master.jpg")
            self.assertEqual(parent_chain_errors(prod), [])

    def test_start_required_and_cannot_copy_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            original = (prod / "03-storyboard" / "shots.json").read_text()
            data = json.loads(original)
            data["shots"][1]["start"] = ""
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)
            data = json.loads(original)
            data["shots"][1]["start"] = data["shots"][1]["action"]
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)
            data = json.loads(original)
            data["shots"][1]["start"] = data["shots"][0]["start"]
            with self.assertRaises(PermissionError):
                save_shots(prod, data)
            self.assertEqual((prod / "03-storyboard" / "shots.json").read_text(), original)

    def test_still_prompt_is_start_not_action(self) -> None:
        from director.prompts import compile_still_prompt

        prod = ROOT / "productions" / "004-yuye-jinlian"
        shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
        sh003 = next(s for s in shots if s["id"] == "SH003")
        still = compile_still_prompt(sh003).lower()
        self.assertIn("deep aisle", still)
        self.assertIn("edit the parent", still)
        self.assertIn("one change", still)
        self.assertIn("second 0", still)
        self.assertIn("seated sewing", still)
        self.assertNotIn("slams the defect box", still)
        self.assertNotIn("walks from the deep aisle", still)
        from director.breakdown import breakdown_package
        draft = breakdown_package(prod)["shots"]["shots"]
        cont = next(shot for shot in draft if shot.get("cut") == "continue")
        mid = compile_still_prompt(cont).lower()
        self.assertIn("mid-action", mid)
        self.assertIn("halfway", mid)
        self.assertNotIn("do not show walking-in", mid)

    def test_lock_frame_requires_previous_shot(self) -> None:
        from director.frames import lock_candidate, upload_candidate
        from director.prompts import missing_sheets

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            src = ROOT / "productions" / "004-yuye-jinlian"
            shutil.copytree(src, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            for gate in ("A", "B", "S", "C"):
                lock_gate(prod, gate, True)
            (prod / "04-frames" / "SH001.jpg").unlink()
            created = upload_candidate(prod, "SH002", "SH002.jpg", b"fake-jpg", "04-frames/SH001.jpg")
            with self.assertRaises(PermissionError):
                lock_candidate(prod, created["id"], "04-frames/SH002.jpg")
            shutil.copyfile(prod / "04-frames" / "SH002.jpg", prod / "04-frames" / "SH001.jpg")
            # SH002 still needs sheets; 004 has them, so lock should now pass parent order.
            self.assertFalse(missing_sheets(prod, json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"][1]))
            locked = lock_candidate(prod, created["id"], "04-frames/SH002.jpg")
            self.assertEqual(locked["dest"], "04-frames/SH002.jpg")

    def test_line_kinds_and_intro_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            src = ROOT / "productions" / "004-yuye-jinlian"
            shutil.copytree(src, prod, ignore=shutil.ignore_patterns(".director", "00-reverse"))
            shutil.copy(prod / "03-storyboard" / "shots.draft.json", prod / "03-storyboard" / "shots.json")
            from director.production import save_shots

            result = save_shots(prod, json.loads((prod / "03-storyboard" / "shots.json").read_text()))
            self.assertTrue(result["check"]["ok"], result["check"])
            data = json.loads((prod / "03-storyboard" / "shots.json").read_text())
            data["shots"][2]["line_kind"] = "intro"
            data["shots"][2]["speaker"] = ""
            data["shots"][2]["line"] = "厂长皮萨来了。"
            data["shots"][2]["caption"] = "厂长皮萨"
            with self.assertRaises(PermissionError):
                save_shots(prod, data)


    def test_designed_end_frame_sets_flf_and_rejects_last_jpg(self) -> None:
        from director.gates import designed_end_frame
        from director.prompts import video_mode

        prod = ROOT / "productions" / "004-yuye-jinlian"
        shots = json.loads((prod / "03-storyboard" / "shots.json").read_text())["shots"]
        sh004 = next(s for s in shots if s["id"] == "SH004")
        self.assertEqual(video_mode(sh004, "designed_frame", ["02-assets/characters/sophea/sheet.jpg"]), "i2v")
        self.assertEqual(i2v_source(prod, sh004, shots)["kind"], "designed_frame")
        self.assertTrue(i2v_source(prod, sh004, shots)["path"].endswith("SH004.jpg"))

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "004"
            shutil.copytree(prod, copy, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            data = json.loads((copy / "03-storyboard" / "shots.json").read_text())
            shot = next(s for s in data["shots"] if s["id"] == "SH004")
            shot["end_frame"] = "04-frames/SH004-last.jpg"
            with self.assertRaises(PermissionError):
                save_shots(copy, data)
            shot["end_frame"] = "04-frames/SH004-end.jpg"
            (copy / "04-frames" / "SH004-end.jpg").write_bytes((copy / "04-frames" / "SH004.jpg").read_bytes())
            result = save_shots(copy, data)
            self.assertTrue(result["check"]["ok"], result["check"])
            end = designed_end_frame(copy, shot)
            self.assertTrue(end["ok"])
            self.assertEqual(video_mode(shot, "designed_frame", ["02-assets/characters/sophea/sheet.jpg"]), "flf")
            from director.fingerprint import shot_spec

            spec = shot_spec(copy, shot, data["shots"])
            self.assertEqual(spec["mode"], "flf")
            self.assertEqual(spec["end_frame"], "04-frames/SH004-end.jpg")
            self.assertEqual(spec["source_kind"], "designed_frame")

    def test_gpu_adapter_keeps_first_frame_and_hangs_refs(self) -> None:
        import importlib.util

        path = ROOT / "scripts" / "video_backends" / "runpod_i2v_server.py"
        spec = importlib.util.spec_from_file_location("runpod_i2v_server", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.turbo_available = lambda: False
        workflow = mod.build_prompt("first.jpg", "hold still", 6, 768, 1344, None, 1)
        self.assertEqual(workflow["104"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertNotIn("204", workflow)
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["1", 0])

        workflow = mod.build_prompt("first.jpg", "hold still", 6, 768, 1344, "end.jpg", 1)
        self.assertEqual(workflow["104"]["inputs"]["last_frame"], ["2", 0])
        self.assertNotIn("204", workflow)

        workflow = mod.build_prompt(
            "first.jpg",
            "hold still",
            6,
            768,
            1344,
            "end.jpg",
            1,
            ref_names=["face.jpg"],
            mode="flf",
        )
        self.assertEqual(workflow["104"]["inputs"]["last_frame"], ["2", 0])
        self.assertNotIn("204", workflow)

        workflow = mod.build_prompt(
            "first.jpg",
            "hold still",
            6,
            768,
            1344,
            None,
            1,
            ref_names=["face.jpg"],
            mode="r2v",
        )
        self.assertEqual(workflow["104"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["1", 0])
        self.assertNotIn("204", workflow)
        orig = mod.find_ref_unet
        mod.find_ref_unet = lambda: "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        try:
            workflow = mod.build_prompt(
                "first.jpg",
                "hold still",
                6,
                768,
                1344,
                None,
                1,
                ref_names=["face.jpg"],
                mode="r2v",
            )
        finally:
            mod.find_ref_unet = orig
        self.assertEqual(workflow["204"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(workflow["16"]["inputs"]["conditioning"], ["205", 0])
        self.assertEqual(workflow["204"]["inputs"]["ref_images"], ["211", 0])
        self.assertEqual(workflow["6"]["inputs"]["unet_name"], mod.UNET)

    def test_eight_agents_and_legacy_locks(self) -> None:
        snap = snapshot(PROD)
        self.assertEqual(len(snap["gates"]), 10)
        self.assertEqual([g["id"] for g in snap["gates"]], ["0", "A", "B", "C", "C1", "C2", "D", "E", "E+", "F"])
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            for gate in ("A", "B", "S", "C"):
                lock_gate(prod, gate, True)
            data = snapshot(prod)
            by_id = {g["id"]: g for g in data["gates"]}
            self.assertTrue(by_id["A"]["locked"])
            self.assertTrue(by_id["B"]["locked"])
            self.assertTrue(by_id["C"]["locked"])
            self.assertIn(by_id["0"]["status"], {"locked", "draft"})

    def test_upstream_edit_stales_director_and_blocks_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            for gate in ("A", "B", "S", "C"):
                lock_gate(prod, gate, True)
            from director.fingerprint import prepare_render

            prepared = prepare_render(prod, ["SH001"])
            self.assertTrue(prepared["fingerprint"])
            ep = prod / "01-bible" / "ep01.md"
            ep.write_text(ep.read_text(encoding="utf-8") + "\n改了一句。\n", encoding="utf-8")
            data = snapshot(prod)
            by_id = {g["id"]: g for g in data["gates"]}
            self.assertTrue(by_id["C"]["stale"] or by_id["A"]["stale"])
            with self.assertRaises(PermissionError):
                prepare_render(prod, ["SH001"])
            lock_gate(prod, "A", True)
            lock_gate(prod, "C", True)
            prepared = prepare_render(prod, ["SH001"])
            self.assertTrue(prepared["fingerprint"])

    def test_launch_inkos_opens_without_writing(self) -> None:
        from director import inkos as inkos_mod

        opened = []
        inkos_mod._open_url = lambda url: opened.append(url)
        inkos_mod._port_open = lambda host, port: True
        inkos_mod._which_inkos = lambda: ""
        result = inkos_mod.launch_inkos({"title": "雨夜", "logline": "她替人挨罚"})
        self.assertTrue(result["ok"])
        self.assertTrue(opened)
        self.assertIn("4567", result["opened"])
        self.assertFalse(result.get("started"))

    def test_writer_check_accepts_visible_action_not_just_then(self) -> None:
        from director.writer_checks import check_episode

        prod = ROOT / "productions" / "005-defeat-named"
        issues = check_episode(prod)
        self.assertNotIn("中段缺少可看见的情节推进", issues)

    def test_story_classify_and_producer_tasks(self) -> None:
        from director.story import classify_text, ingest_upload
        from director.producer import write_producer_draft

        self.assertEqual(classify_text("第1集\nSH001 车间"), "script")
        self.assertEqual(classify_text("很久以前有一个女孩在金边长大。"), "novel")
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            result = ingest_upload(prod, "story.md", "第1集\n女主走进车间。".encode("utf-8"))
            self.assertEqual(result["kind"], "script")
            self.assertIn("original.draft.md", result["drafts"])
            self.assertFalse((prod / "01-bible" / "source" / "original.md").exists())
            tasks = write_producer_draft(prod)
            self.assertIn("manifest.draft.json", tasks["drafts"])
            self.assertFalse((prod / "01-bible" / "producer" / "manifest.json").exists())

    def test_line_kind_aliases_and_gpu_caps(self) -> None:
        from director.gpu_caps import gpu_capabilities
        from director.production import save_shots

        caps = gpu_capabilities(force=True)
        self.assertFalse(caps["ref2va"])
        self.assertIn("不", caps["note"] + caps.get("reason", ""))
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            src = ROOT / "productions" / "004-yuye-jinlian"
            shutil.copytree(src, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            data = json.loads((prod / "03-storyboard" / "shots.json").read_text())
            data["shots"][0]["line_kind"] = "inner_voice"
            data["shots"][0]["speaker"] = data["shots"][0]["characters"][0]
            data["shots"][0]["line"] = "她不敢回头。"
            data["shots"][0]["caption"] = "不敢回头"
            result = save_shots(prod, data)
            self.assertTrue(result["check"]["ok"], result["check"])

    def test_004_migration_does_not_rewrite_picture(self) -> None:
        src = ROOT / "productions" / "004-yuye-jinlian"
        shots = src / "03-storyboard" / "shots.json"
        ep = src / "01-bible" / "ep01.md"
        video = src / "06-export" / "ep01.mp4"
        before_shots = shots.read_bytes()
        before_ep = ep.read_bytes()
        before_video = video.read_bytes() if video.exists() else b""
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "004"
            shutil.copytree(src, prod)
            data = snapshot(prod)
            self.assertEqual(len(data["gates"]), 10)
            by_id = {g["id"]: g for g in data["gates"]}
            self.assertTrue(by_id["0"]["locked"] or by_id["0"].get("migrated"))
            self.assertTrue(by_id["C"]["locked"])
            self.assertTrue((prod / "05-shots" / "SH001.mp4").exists())
        self.assertEqual(shots.read_bytes(), before_shots)
        self.assertEqual(ep.read_bytes(), before_ep)
        if before_video:
            self.assertEqual(video.read_bytes(), before_video)

    def test_knowledge_is_layered(self) -> None:
        from director.knowledge import load_for, prompt_block

        packed = load_for("writer")
        self.assertIn("rules", packed)
        self.assertIn("writer", packed)
        self.assertNotIn("camera", packed)
        block = prompt_block("camera")
        self.assertIn("FL2VA", block)
        self.assertNotIn("千军", block)
        writer = prompt_block("writer")
        self.assertIn("先让人站住", writer)
        self.assertIn("只升级一件事", writer)
        director = prompt_block("director")
        self.assertIn("宫格", director)
        self.assertIn("摄影机契约", director)
        art = prompt_block("art")
        self.assertIn("电影感", art)
        sound = prompt_block("edit")
        self.assertIn("意图", sound)
        self.assertNotIn("可灵 9 字段", writer)

    def test_storyboard_grid_is_preview_only(self) -> None:
        from director.grid import storyboard_grid

        prod = ROOT / "productions" / "004-yuye-jinlian"
        grid = storyboard_grid(prod)
        self.assertGreaterEqual(grid["count"], 8)
        self.assertTrue(grid["cells"][0]["url"] or grid["cells"][0]["missing"])
        self.assertIn("只给人看", grid["note"])
        self.assertNotIn("H3 输入", "".join(cell.get("image") or "" for cell in grid["cells"]))

    def test_sound_contract_has_intention(self) -> None:
        from director.sound_contract import build_sound_contract

        prod = ROOT / "productions" / "004-yuye-jinlian"
        contract = build_sound_contract(prod)
        self.assertTrue(contract["cues"])
        self.assertIn("intention", contract["cues"][0])
        self.assertTrue(contract["cues"][0]["intention"])

    def test_i2v_source_uses_shot_last_frame_field(self) -> None:
        shots = json.loads((PROD / "03-storyboard" / "shots.json").read_text())["shots"]
        sh006 = next(s for s in shots if s["id"] == "SH006")
        prev = next(s for s in shots if s["id"] == "SH005")
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            alt = prod / "04-frames-b"
            alt.mkdir()
            last = alt / "SH005-last.jpg"
            last.write_bytes((prod / "04-frames" / "SH005.jpg").read_bytes())
            prev["last_frame"] = "04-frames-b/SH005-last.jpg"
            sh006["setup"] = prev["setup"]
            source = i2v_source(prod, sh006, shots)
            self.assertEqual(source["kind"], "last_frame")
            self.assertTrue(source["path"].endswith("04-frames-b/SH005-last.jpg"))

    def test_render_shots_accepts_storyboard_and_video_dir(self) -> None:
        from render_shots import last_frame_path, load_shots
        prod = ROOT / "productions" / "005-defeat-named"
        shots = load_shots(prod, "03-storyboard/shots.b.json")
        self.assertEqual(len(shots), 10)
        self.assertTrue(str(shots[0].get("frame", "")).startswith("04-frames-b/"))
        last = last_frame_path(prod, shots[0])
        self.assertTrue(str(last).endswith("04-frames-b/SH001-last.jpg"))


    def test_pipeline_rejects_writer_camera_and_unconfirmed_package(self) -> None:
        from director.pipeline import (
            confirm_packages,
            duration_for_shot,
            raise_if,
            validate_packages,
            validate_shot_list,
            validate_shot_specs,
            validate_writer,
            write_artifact,
        )

        writer = {"series_bible": {"logline": "x", "characters": [{"name": "A"}], "locations": [{"location_id": "loc"}]}, "episode_outline": [{"episode_no": 1}], "scenes": [{"scene_id": "SC1", "heading": "INT. X - DAY", "location_id": "loc", "time_of_day": "day", "int_ext": "int", "present_cast": ["a"], "scene_job": "change", "whose_scene": "a", "start_state": "sit", "end_state": "stand", "action": "She puts the cup down.", "dialogue": [{"speaker": "a", "line": "我要走了。"}], "unfilmable_check": "pass", "mute_test": "pass", "preach_check": "pass"}]}
        self.assertEqual(validate_writer(writer), [])
        bad = dict(writer)
        bad["scenes"] = [dict(writer["scenes"][0], action="镜头推进到她的眼睛", mute_test="fail")]
        self.assertTrue(validate_writer(bad))
        design = {"shots": [{"shot_id": "SH001", "beat": "hook", "shot_job": "see the torch take", "coverage_type": "master", "move_needed": "static"}], "left_right_lock": "Dara left", "visible_change_without_dialogue": "pass", "design_steps_done": [1, 2, 3, 4, 5, 6, 7]}
        self.assertEqual(validate_shot_list(design), [])
        design_bad = {"shots": [{"shot_id": "SH001", "beat": "hook", "shot_job": "x", "coverage_type": "reaction", "prompt": "a prompt"}], "visible_change_without_dialogue": "pass"}
        self.assertTrue(any("shot_job" in err or "prompt" in err or "reaction" in err for err in validate_shot_list(design_bad)))
        spec_bad = {"shot_specs": [{"shot_id": "SH001", "dialogue_line": "另一句", "image_prompt": "no"}]}
        self.assertTrue(validate_shot_specs(spec_bad, writer))
        pkg = {"packages": [{"shot_id": "SH001", "target_model": "minimax_h3", "episode_target_model": "minimax_h3", "asset_refs": ["CHAR_A_V1"], "keyframe_files": ["04-frames/SH001.jpg"], "image_prompt": "still", "motion_prompt": "hold", "prompt_language": "en", "gen_mode": "i2v_first", "confirmed": False}], "episode_target_model": "minimax_h3"}
        self.assertTrue(any("keyframe" in err for err in validate_packages(pkg, {"assets": [{"asset_id": "CHAR_A_V1"}]})))
        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            write_artifact(prod, "gen_packages.json", {"packages": [{"shot_id": "SH001", "target_model": "minimax_h3", "episode_target_model": "minimax_h3", "asset_refs": ["CHAR_SREYMOM_V1"], "keyframe_files": [], "image_prompt": "still of the table", "motion_prompt": "almost no move, breath only", "prompt_language": "en", "gen_mode": "i2v_first", "confirmed": False}], "episode_target_model": "minimax_h3"})
            write_artifact(prod, "assets.json", {"assets": [{"asset_id": "CHAR_SREYMOM_V1", "type": "character", "name": "sreymom", "binds_to": "sreymom", "file": "02-assets/characters/sreymom/master.jpg", "what_it_locks": "identity", "version": "v1", "lock_card": [], "image_prompt": "passport"}]})
            with self.assertRaises(PermissionError):
                from director.frames import request_shot_still
                from director.gates import lock_gate
                for gate in ("A", "B", "S", "C"):
                    lock_gate(prod, gate, True)
                request_shot_still(prod, "SH001")
            confirmed = confirm_packages(prod, True)
            self.assertTrue(confirmed["confirmed"])
            self.assertEqual(duration_for_shot(prod, "SH001", 9), 9)

    def test_keyframe_gate_needs_human_signature_state_and_no_silent_nits(self) -> None:
        from PIL import Image
        from director.pipeline import validate_keyframes

        def qc(**over):
            base = {"status": "pass", "face": "pass", "costume": "pass", "location": "pass", "left_right": "pass",
                    "composition": "pass", "aspect_ratio": "pass", "light_matches_spec": "pass", "state_match": "pass"}
            base.update(over)
            return base

        packages = {"packages": [{"shot_id": "SH001", "keyframe_plan": "first_last"}, {"shot_id": "SH002", "keyframe_plan": "first"}]}
        table = {"shots": [{"shot_id": "SH001", "scale": "wide", "coverage_type": "master"}, {"shot_id": "SH002", "scale": "insert", "coverage_type": "insert"}]}
        good = {
            "reviewed_by": "tonyteacher",
            "keyframes": [
                {"shot_id": "SH001", "first_frame_file": "04-frames/SH001.jpg", "last_frame_file": "04-frames/SH001-last.jpg", "qc": qc(out_to_readable="pass")},
                {"shot_id": "SH002", "first_frame_file": "04-frames/SH002.jpg", "qc": qc(plastic_face="pass", anatomy="pass")},
            ],
        }
        self.assertEqual(validate_keyframes(good, packages=packages, table=table), [])

        unsigned = dict(good, reviewed_by="")
        self.assertTrue(any("reviewed_by" in e for e in validate_keyframes(unsigned, packages=packages, table=table)))

        no_last = json.loads(json.dumps(good))
        del no_last["keyframes"][0]["last_frame_file"]
        del no_last["keyframes"][0]["qc"]["out_to_readable"]
        errors = validate_keyframes(no_last, packages=packages, table=table)
        self.assertTrue(any("no last_frame_file" in e for e in errors), errors)
        self.assertTrue(any("out_to_readable" in e for e in errors), errors)

        no_tight = json.loads(json.dumps(good))
        del no_tight["keyframes"][1]["qc"]["anatomy"]
        self.assertTrue(any("needs qc.anatomy" in e for e in validate_keyframes(no_tight, packages=packages, table=table)))

        silent_nit = json.loads(json.dumps(good))
        silent_nit["keyframes"][0]["qc"]["notes"] = "绳在身前"
        errors = validate_keyframes(silent_nit, packages=packages, table=table)
        self.assertTrue(any("no waived_by" in e for e in errors), errors)
        silent_nit["keyframes"][0]["qc"]["waived_by"] = "tonyteacher"
        self.assertEqual(validate_keyframes(silent_nit, packages=packages, table=table), [])

        mixed = json.loads(json.dumps(good))
        mixed["keyframes"][0]["qc"]["costume"] = "fail"
        errors = validate_keyframes(mixed, packages=packages, table=table)
        self.assertTrue(any("fail items (costume) but status pass" in e for e in errors), errors)
        mixed["keyframes"][0]["qc"]["state_match"] = "maybe"
        self.assertTrue(any("must be pass / fail / n/a" in e for e in validate_keyframes(mixed, packages=packages, table=table)))

        legacy = {"reviewed_by": "x", "keyframes": [{"shot_id": "SH001", "first_frame_file": "04-frames/SH001.jpg", "qc": {"status": "pass", "face": "pass", "costume": "pass", "location": "pass", "left_right": "pass", "composition": "pass", "aspect_ratio": "pass"}}]}
        errors = validate_keyframes(legacy)
        self.assertTrue(any("missing light_matches_spec" in e for e in errors), errors)
        self.assertTrue(any("missing state_match" in e for e in errors), errors)

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "009"
            (prod / "04-frames").mkdir(parents=True)
            Image.new("RGB", (32, 18)).save(prod / "04-frames" / "SH001.jpg")
            errors = validate_keyframes(good, packages=packages, table=table, prod=prod)
            self.assertTrue(any("missing on disk: 04-frames/SH001-last.jpg" in e for e in errors), errors)
            self.assertTrue(any("missing on disk: 04-frames/SH002.jpg" in e for e in errors), errors)

    def test_cut_trims_to_spec_duration(self) -> None:
        from director.pipeline import default_cut_from_specs, duration_for_shot, write_artifact

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            write_artifact(prod, "shot_specs.json", {"shot_specs": [{"shot_id": "SH001", "duration_sec": 2, "subject": "a", "action_now": "x", "shot_size": "close", "angle": "eye", "height": "eye", "focal_length": "50mm", "aspect_ratio": "9:16", "move_type": "static", "move_detail": "hold", "move_reason": "hold", "intensity": 0, "left": "a", "right": "", "eyeline": "right", "body_facing": "right", "day_night": "day", "key_light_dir": "side", "quality": "soft", "color_mood": "warm", "axis_side": "left", "in_from": "open", "out_to": "hold"}]})
            cut = default_cut_from_specs(prod, ["SH001"])
            self.assertEqual(cut["timeline"][0]["out_point"], 2)
            self.assertEqual(duration_for_shot(prod, "SH001", 5), 2)



    def test_station_agent_needs_key_and_stays_in_lane(self) -> None:
        from director.grok_text import TextError
        from director.station_agents import run_station_agent, STATION_VALIDATORS, _merge_status
        from director.pipeline import validate_shot_list, validate_writer

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "003"
            shutil.copytree(PROD, prod, ignore=shutil.ignore_patterns(".director", "05-shots", "06-export"))
            old = os.environ.get("XAI_API_KEY")
            old_sub = os.environ.get("DIRECTOR_DISABLE_GROK_SUBSCRIPTION")
            os.environ.pop("XAI_API_KEY", None)
            os.environ["DIRECTOR_DISABLE_GROK_SUBSCRIPTION"] = "1"
            try:
                with self.assertRaises(TextError):
                    run_station_agent(prod, "design")
            finally:
                if old is not None:
                    os.environ["XAI_API_KEY"] = old
                else:
                    os.environ.pop("XAI_API_KEY", None)
                if old_sub is None:
                    os.environ.pop("DIRECTOR_DISABLE_GROK_SUBSCRIPTION", None)
                else:
                    os.environ["DIRECTOR_DISABLE_GROK_SUBSCRIPTION"] = old_sub
            writer_bad = {"scenes": [{"scene_id": "SC1", "action": "镜头推进到她的眼睛", "mute_test": "fail"}]}
            self.assertTrue(validate_writer(writer_bad))
            design_bad = {"shots": [{"shot_id": "SH001", "beat": "x", "shot_job": "", "coverage_type": "reaction", "prompt": "hi"}]}
            self.assertTrue(validate_shot_list(design_bad))
            merged = _merge_status({"packages": [{"shot_id": "SH001", "confirmed": True, "keyframe_files": ["x.jpg"]}]}, "package")
            self.assertFalse(merged["confirmed"])
            self.assertEqual(merged["packages"][0]["keyframe_files"], [])

    def test_breakdown_without_key_is_rules_not_director(self) -> None:
        from fastapi.testclient import TestClient
        from director_server import app
        import director.paths as paths

        with tempfile.TemporaryDirectory() as tmp:
            productions = Path(tmp) / "productions"
            shutil.copytree(
                ROOT / "productions" / "005-defeat-named",
                productions / "005-defeat-named",
                ignore=shutil.ignore_patterns(".director"),
            )
            old_prod = paths.PRODUCTIONS
            old_key = os.environ.get("XAI_API_KEY")
            old_sub = os.environ.get("DIRECTOR_DISABLE_GROK_SUBSCRIPTION")
            os.environ.pop("XAI_API_KEY", None)
            os.environ["DIRECTOR_DISABLE_GROK_SUBSCRIPTION"] = "1"
            paths.PRODUCTIONS = productions
            try:
                client = TestClient(app)
                written = client.post("/api/productions/005-defeat-named/breakdown", json={})
                self.assertEqual(written.status_code, 200, written.text)
                body = written.json()
                self.assertFalse(body.get("used_tokens"))
                self.assertIn("规则", body.get("note") or body.get("origin") or "")
            finally:
                paths.PRODUCTIONS = old_prod
                if old_key is not None:
                    os.environ["XAI_API_KEY"] = old_key
                else:
                    os.environ.pop("XAI_API_KEY", None)
                if old_sub is None:
                    os.environ.pop("DIRECTOR_DISABLE_GROK_SUBSCRIPTION", None)
                else:
                    os.environ["DIRECTOR_DISABLE_GROK_SUBSCRIPTION"] = old_sub



    def test_grok_subscription_backend_detected(self) -> None:
        from director.grok_text import text_backend, text_configured, chat_json, parse_json_content

        os.environ.pop("XAI_API_KEY", None)
        os.environ.pop("DIRECTOR_DISABLE_GROK_SUBSCRIPTION", None)
        self.assertTrue(text_configured())
        self.assertEqual(text_backend(), "grok-subscription")
        self.assertEqual(parse_json_content('{"ok": true}'), {"ok": True})
        premature = '{"shots":[{"shot_id":"SH001","duration_sec":4}] ,{"shot_id":"SH002","duration_sec":5}]}'
        recovered = parse_json_content(premature)
        self.assertEqual([s["shot_id"] for s in recovered["shots"]], ["SH001", "SH002"])
        os.environ["DIRECTOR_DISABLE_GROK_SUBSCRIPTION"] = "1"
        try:
            self.assertFalse(text_configured())
        finally:
            os.environ.pop("DIRECTOR_DISABLE_GROK_SUBSCRIPTION", None)




    def test_seedance_payload_uses_first_frame_role(self) -> None:
        from video_backends.seedance_ark import SeedanceArk
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "first.jpg"
            image.write_bytes(b"fakejpg")
            end = Path(tmp) / "end.jpg"
            end.write_bytes(b"fakeend")
            ref = Path(tmp) / "face.jpg"
            ref.write_bytes(b"fakeref")
            old = os.environ.get("ARK_API_KEY")
            old_model = os.environ.get("ARK_SEEDANCE_MODEL")
            old_res = os.environ.get("ARK_RESOLUTION")
            old_audio = os.environ.get("ARK_GENERATE_AUDIO")
            os.environ["ARK_API_KEY"] = "test-key"
            os.environ["ARK_SEEDANCE_MODEL"] = "doubao-seedance-2-0-mini-260615"
            os.environ["ARK_RESOLUTION"] = "480p"
            os.environ.pop("ARK_GENERATE_AUDIO", None)
            try:
                backend = SeedanceArk()
                payload = backend.build_payload(image, "中文动作", 6, refs=[ref], mode="flf", last_frame=end)
                i2v = backend.build_payload(image, "中文动作", 4, refs=[ref], mode="i2v")
                silent = backend.build_payload(image, "中文动作", 4, mode="i2v", generate_audio=False)
            finally:
                if old is not None:
                    os.environ["ARK_API_KEY"] = old
                else:
                    os.environ.pop("ARK_API_KEY", None)
                if old_model is not None:
                    os.environ["ARK_SEEDANCE_MODEL"] = old_model
                else:
                    os.environ.pop("ARK_SEEDANCE_MODEL", None)
                if old_res is not None:
                    os.environ["ARK_RESOLUTION"] = old_res
                else:
                    os.environ.pop("ARK_RESOLUTION", None)
                if old_audio is not None:
                    os.environ["ARK_GENERATE_AUDIO"] = old_audio
                else:
                    os.environ.pop("ARK_GENERATE_AUDIO", None)
            roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
            self.assertEqual(payload["model"], "doubao-seedance-2-0-mini-260615")
            self.assertEqual(payload["resolution"], "480p")
            self.assertNotIn("reference_image", roles)
            self.assertEqual(payload["duration"], 6)
            self.assertIn("first_frame", roles)
            self.assertIn("last_frame", roles)
            self.assertFalse(payload["watermark"])
            self.assertTrue(payload["generate_audio"])
            self.assertTrue(i2v["generate_audio"])
            self.assertFalse(silent["generate_audio"])
            i2v_roles = [item.get("role") for item in i2v["content"] if item.get("type") == "image_url"]
            self.assertIn("reference_image", i2v_roles)
            self.assertNotIn("last_frame", i2v_roles)

    def test_backends_refuse_out_of_range_seconds_instead_of_clamping(self) -> None:
        from unittest import mock

        from video_backends.compshare_h3 import CompShareH3
        from video_backends.seedance_ark import SeedanceArk

        env = {"ARK_API_KEY": "test-key", "ARK_SEEDANCE_MODEL": "doubao-seedance-2-0-mini-260615", "COMPSHARE_API_KEY": "sk-ml-test"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env):
            image = Path(tmp) / "first.jpg"
            image.write_bytes(b"fakejpg")
            backend = SeedanceArk()
            self.assertEqual(backend.clamp_duration(15), 15)
            self.assertEqual(backend.build_payload(image, "中文动作", 4, mode="i2v")["duration"], 4)
            with self.assertRaises(RuntimeError) as ctx:
                backend.build_payload(image, "中文动作", 20, mode="i2v")
            self.assertEqual(str(ctx.exception), "秒数 20 不在 doubao-seedance-2-0-mini-260615 档内 [4,15]，改分镜表，不替人改")
            with self.assertRaises(RuntimeError):
                backend.clamp_duration(0)
            # render names the shot and stops before any ticket or task is written
            dest = Path(tmp) / "SH003.mp4"
            backend.submit = lambda *a, **k: self.fail("must not submit")  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                backend.render(image, "prompt", 3, dest)
            self.assertTrue(str(ctx.exception).startswith("SH003 秒数 3 不在 "))
            self.assertFalse(dest.with_suffix(".mp4.ark-task.json").exists())
            h3 = CompShareH3()
            self.assertEqual(h3.clamp_duration(6), 6)
            with self.assertRaises(RuntimeError) as ctx:
                h3.clamp_duration(16, shot_id="SH010")
            self.assertEqual(str(ctx.exception), "SH010 秒数 16 不在 MiniMax-H3 档内 [4,15]，改分镜表，不替人改")
            h3.points = lambda: self.fail("must not spend points")  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError):
                h3.render(image, "prompt", 2, Path(tmp) / "SH011.mp4")

    def test_seedance_render_resumes_ticket_instead_of_resubmitting(self) -> None:
        from video_backends.seedance_ark import SeedanceArk
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "SH001.mp4"
            dest.write_bytes(b"x" * 2048)
            old = os.environ.get("ARK_API_KEY")
            os.environ["ARK_API_KEY"] = "test-key"
            try:
                backend = SeedanceArk()
                called = {"submit": 0}
                def boom(*args, **kwargs):
                    called["submit"] += 1
                    raise AssertionError("should not create a second task")
                backend.submit = boom  # type: ignore[method-assign]
                backend.render(Path(tmp)/"first.jpg", "prompt", 4, dest)
            finally:
                if old is not None:
                    os.environ["ARK_API_KEY"] = old
                else:
                    os.environ.pop("ARK_API_KEY", None)
            self.assertEqual(called["submit"], 0)
            self.assertTrue(dest.exists())

    def test_seedance_cancel_and_create_task_parse_empty_body(self) -> None:
        from unittest import mock

        from video_backends.seedance_ark import SeedanceArk

        class FakeResp:
            def __init__(self, status_code: int, text: str = "") -> None:
                self.status_code = status_code
                self.text = text

            def json(self):
                raise ValueError("empty")

        with mock.patch.dict(os.environ, {"ARK_API_KEY": "test-key"}):
            backend = SeedanceArk()
        self.assertEqual(backend._json_body(FakeResp(200, "")), {})
        self.assertEqual(backend._json_body(FakeResp(400, "not-json"))["error"]["code"], "InvalidJSON")

    def test_seedance_render_uses_existing_task_id(self) -> None:
        from video_backends.seedance_ark import SeedanceArk
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "SH002.mp4"
            ticket = dest.with_suffix(dest.suffix + ".ark-task.json")
            ticket.write_text('{"task_id": "cgt-existing"}\n', encoding="utf-8")
            old = os.environ.get("ARK_API_KEY")
            os.environ["ARK_API_KEY"] = "test-key"
            try:
                backend = SeedanceArk()
                called = {"submit": 0, "wait": []}
                def boom(*args, **kwargs):
                    called["submit"] += 1
                    raise AssertionError("should resume")
                def wait(task_id):
                    called["wait"].append(task_id)
                    return "http://example.local/out.mp4"
                def fake_download(url, path):
                    path.write_bytes(b"downloaded")
                backend.submit = boom  # type: ignore[method-assign]
                backend.wait_url = wait  # type: ignore[method-assign]
                backend.download = fake_download  # type: ignore[method-assign]
                backend.render(Path(tmp)/"first.jpg", "prompt", 4, dest)
            finally:
                if old is not None:
                    os.environ["ARK_API_KEY"] = old
                else:
                    os.environ.pop("ARK_API_KEY", None)
            self.assertEqual(called["submit"], 0)
            self.assertEqual(called["wait"], ["cgt-existing"])
            self.assertEqual(dest.read_bytes(), b"downloaded")

    def test_seedance_package_plan_does_not_need_shots_json(self) -> None:
        from render_seedance_packages import build_plan, plan_shot, seedance_mode

        self.assertEqual(seedance_mode("flf2v"), "flf")
        self.assertEqual(seedance_mode("i2v_first"), "i2v")
        self.assertEqual(seedance_mode("video_extend"), "i2v")
        prod = ROOT / "productions" / "009-siem-reap"
        if not (prod / "03-storyboard" / "shots.json").exists():
            plan = build_plan(prod, ["SH001", "SH002", "SH004", "SH015"])
            by_id = {item["shot_id"]: item for item in plan["shots"]}
            self.assertTrue(plan["ok_count"] >= 4, plan)
            self.assertFalse(plan["writes_shots_json"])
            self.assertFalse(plan["overwrites_designed_last"])
            self.assertEqual(by_id["SH004"]["seedance_mode"], "flf")
            self.assertTrue(by_id["SH004"]["use_last_frame"])
            self.assertEqual(by_id["SH002"]["seedance_mode"], "i2v")
            self.assertFalse(by_id["SH002"]["use_last_frame"])
            self.assertEqual(by_id["SH015"]["extracted_last"], "05-shots/SH015-last.jpg")
            self.assertNotEqual(by_id["SH004"]["extracted_last"], by_id["SH004"]["last_frame"])
        pkg = {"shot_id": "SH099", "gen_mode": "flf2v", "keyframe_plan": "first_last", "confirmed": True, "motion_prompt": "动一下", "duration_sec": 4, "asset_refs": []}
        planned = plan_shot(prod, pkg, {"SH099": {"shot_id": "SH099", "qc": {"status": "pass"}}}, {})
        self.assertFalse(planned["ok"])
        self.assertTrue(any("missing first" in err or "missing last" in err for err in planned["errors"]))

    def test_seedance_prompt_is_chinese_not_h3_fields(self) -> None:
        from director.prompts import compile_seedance_prompt
        prompt = compile_seedance_prompt(
            {"id": "SH001", "action": "速卡蹲在石槽前伸手摸凹痕", "setup": "master", "camera": "固定机位"},
            {"action_now": "速卡蹲在石槽前伸手摸凹痕", "move_detail": "固定机位", "shot_size": "中近景", "dialogue_line": "水往哪走，河床都替你记着。"},
        )
        self.assertIn("速卡蹲在石槽前", prompt)
        self.assertNotIn("integrated_multimodal_description", prompt)
        self.assertIn("对白不进画面", prompt)

    def test_gate_c_accepts_v2_shot_list_without_legacy_shots(self) -> None:
        from director.gates import gate_file_ready, inspect_files, v2_storyboard_ready
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "v2show"
            (prod / ".pipeline").mkdir(parents=True)
            (prod / "03-storyboard").mkdir(parents=True)
            table = {
                "schema": "shot-table-v2",
                "status": "locked",
                "target_model": "seedance_2_0",
                "shots": [{"shot_id": "SH001"}],
            }
            (prod / ".pipeline" / "shot_list.json").write_text(
                json.dumps(table, ensure_ascii=False), encoding="utf-8"
            )
            with patch("director.pipeline.validate_shot_list", return_value=[]):
                ok, reason = v2_storyboard_ready(prod)
                self.assertTrue(ok, reason)
                ready, ready_reason = gate_file_ready(prod, "C", inspect_files(prod))
                self.assertTrue(ready, ready_reason)
                self.assertFalse((prod / "03-storyboard" / "shots.json").exists())
                self.assertFalse((prod / "03-storyboard" / "coverage.md").exists())

    def test_gate_d_accepts_pipeline_keyframes_without_shots_json(self) -> None:
        from director.gates import gate_file_ready, inspect_files
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "v2show"
            (prod / ".pipeline").mkdir(parents=True)
            (prod / "04-frames").mkdir(parents=True)
            Image.new("RGB", (32, 18)).save(prod / "04-frames" / "SH001.jpg")
            table = {"schema": "shot-table-v2", "status": "locked", "shots": [{"shot_id": "SH001", "scale": "wide"}]}
            packages = {"packages": [{"shot_id": "SH001", "keyframe_plan": "first"}]}
            kf = {
                "reviewed_by": "tonyteacher",
                "keyframes": [
                    {
                        "shot_id": "SH001",
                        "first_frame_file": "04-frames/SH001.jpg",
                        "qc": {
                            "status": "pass",
                            "face": "pass",
                            "costume": "pass",
                            "location": "pass",
                            "left_right": "pass",
                            "composition": "pass",
                            "aspect_ratio": "pass",
                            "light_matches_spec": "pass",
                            "state_match": "pass",
                        },
                    }
                ],
            }
            (prod / ".pipeline" / "shot_list.json").write_text(json.dumps(table), encoding="utf-8")
            (prod / ".pipeline" / "gen_packages.json").write_text(json.dumps(packages), encoding="utf-8")
            (prod / ".pipeline" / "keyframes.json").write_text(json.dumps(kf), encoding="utf-8")
            files = inspect_files(prod)
            self.assertEqual(files["shot_count"], 1)
            self.assertEqual(files["locked_frame_count"], 1)
            self.assertFalse((prod / "03-storyboard" / "shots.json").exists())
            ready, reason = gate_file_ready(prod, "D", files)
            self.assertTrue(ready, reason)

    def test_gate_e_requires_animatic_only_for_official_videos(self) -> None:
        from director.gates import gate_file_ready, inspect_files

        with tempfile.TemporaryDirectory() as tmp:
            prod = Path(tmp) / "v2show"
            (prod / ".pipeline").mkdir(parents=True)
            (prod / "04-frames").mkdir(parents=True)
            (prod / ".pipeline" / "shot_list.json").write_text(
                json.dumps({"schema": "shot-table-v2", "shots": [{"shot_id": "SH001"}]}),
                encoding="utf-8",
            )
            files = inspect_files(prod)
            ready, reason = gate_file_ready(prod, "E", files)
            self.assertFalse(ready)
            self.assertIn("还没有单镜视频", reason)
            (prod / "05-shots").mkdir(parents=True)
            (prod / "05-shots" / "SH001.mp4").write_bytes(b"x" * 32)
            (prod / "04-frames" / "SH001.jpg").write_bytes(b"x")
            files = inspect_files(prod)
            ready, reason = gate_file_ready(prod, "E", files)
            self.assertFalse(ready)
            self.assertIn("animatic", reason)


class SeedanceMotionOneSetupTests(unittest.TestCase):
    def test_out_to_cut_language_is_stripped_and_internal_cuts_stay_off(self) -> None:
        from director.prompts import compile_seedance_motion_from_spec, sanitize_camera_state
        from director.video_profiles import get_profile

        self.assertEqual(sanitize_camera_state("立刻切她的怕"), "")
        self.assertEqual(sanitize_camera_state("肩刚出白衬衫，切琳的眼"), "肩刚出白衬衫")
        self.assertEqual(sanitize_camera_state("画面下缘切在小腿"), "画面下缘切在小腿")
        motion = compile_seedance_motion_from_spec(
            {
                "in_from": "她还盯工牌",
                "out_to": "立刻切她的怕",
                "action_now": "从琳肩后看见胸口透光",
                "duration_sec": 4,
                "internal_cuts": [{"at_sec": 3, "scale": "close", "one_action": "切她的怕"}],
            },
            {},
            get_profile("seedance_2_0"),
        )
        self.assertNotIn("立刻切", motion)
        self.assertNotIn("片内切", motion)
        self.assertNotIn("切到", motion)
        self.assertIn("整段停在本机位", motion)
        self.assertIn("从起幅开始：她还盯工牌。", motion)


if __name__ == "__main__":

    unittest.main()
