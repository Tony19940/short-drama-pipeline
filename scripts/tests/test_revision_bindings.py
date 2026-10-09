"""Regression: revision context cannot borrow an older table or output folder."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import check_prod
import check_storyboard
from director.context import ProductionContext
from director.context import using_context
from director.agents import ensure_lock_fingerprints, file_hashes, stale_reason, virtual_locked
from director.gates import inspect_files, run_check
from director.pipeline import read_artifact, write_artifact
from director.revisions import RevisionError, activate_revision, load_registry, register_revision, resolve_binding
from director.shot_repo import list_shots
from director.takes import Take, persist_take, resolve_shot_media, select_take, selected_take_id


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def revision(rev: str = "v2") -> dict:
    return {
        "episode_id": "ep01", "revision_id": rev,
        "artifacts": {"shot_list.json": f".pipeline/tables/{rev}.json", "writer.json": f".pipeline/writer.{rev}.json"},
        "frames_dir": f"04-frames/{rev}", "shots_dir": f"05-shots/{rev}/official",
        "cut_file": f".pipeline/cuts/{rev}.json",
    }


class RevisionBindings(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prod = Path(self.tmp.name) / "show"
        self.prod.mkdir()
        write(self.prod / ".pipeline/shot_list.json", {"schema": "shot-table-v2", "shots": [{"shot_id": "SH001"}]})

    def register(self, rev="v2", activate=True) -> None:
        register_revision(self.prod, revision(rev), activate=activate)

    def test_no_registry_preserves_explicit_legacy_layout(self) -> None:
        ctx = ProductionContext.resolve(self.prod, "ep01-v2")
        self.assertEqual(ctx.mode, "legacy")
        self.assertEqual(ctx.episode_id, "ep01-v2")
        self.assertEqual(ctx.artifact_name("shot_list.json"), "shot_list.ep01-v2.json")
        self.assertEqual(ctx.frame_dir(), "04-frames/ep01-v2")

    def test_prepare_and_consume_use_same_canonical_revision_token(self) -> None:
        from director.fingerprint import fingerprint_for, prepare_render, consume_render_fingerprint, load_confirmed_snapshot

        self.register()
        write(self.prod / ".pipeline/tables/v2.json", {"shots": [{"shot_id": "SH001"}]})
        specs = [{"id": "SH001", "vendor_request": {"shot_id": "SH001", "prompt": "request fixture", "media_hashes": {}}}]
        with ExitStack() as stack:
            stack.enter_context(patch("director.fingerprint._pipeline_specs", return_value=specs))
            for target in ("director.fingerprint.require_fresh_gate", "director.fingerprint.require_task_inputs",
                           "director.pipeline.assert_packages_confirmed", "director.pipeline.assert_keyframes_passed"):
                stack.enter_context(patch(target))
            stack.enter_context(patch("director.fingerprint.run_check", return_value={"ok": True}))
            self.assertEqual(fingerprint_for(self.prod, ["SH001"], 1)[0], fingerprint_for(self.prod, ["SH001"], "ep01-v2")[0])
            prepared = prepare_render(self.prod, ["SH001"], episode=1)
            consumed = consume_render_fingerprint(self.prod, prepared["fingerprint"], ["SH001"], episode="ep01-v2")
            self.assertEqual(consumed["episode"], "ep01-v2")
            snap = load_confirmed_snapshot(self.prod, consumed["snapshot"], expected_episode="ep01-v2")
            self.assertEqual(snap["shot_ids"], ["SH001"])

    def test_active_revision_binds_all_stage_paths(self) -> None:
        self.register()
        write(self.prod / ".pipeline/tables/v2.json", {"schema": "shot-table-v2", "shots": [{"shot_id": "SH009"}]})
        ctx = ProductionContext.resolve(self.prod)
        self.assertEqual(ctx.revision_id, "v2")
        self.assertEqual(ctx.episode_token, "ep01-v2")
        self.assertEqual(ctx.artifact_name("shot_list.json"), "tables/v2.json")
        self.assertEqual(ctx.frame_dir(), "04-frames/v2")
        self.assertEqual(ctx.shot_dir(), "05-shots/v2/official")
        self.assertEqual(ctx.cut_rel(), ".pipeline/cuts/v2.json")
        self.assertEqual(list_shots(self.prod)[0]["frame"], "04-frames/v2/SH009.jpg")
        self.assertEqual(list_shots(ctx)[0]["id"], "SH009")

    def test_gate_and_fingerprints_use_revision_subdirectories(self) -> None:
        self.register()
        write(self.prod / ".pipeline/tables/v2.json", {"shots": [{"shot_id": "SH001"}]})
        for rel in ("04-frames/SH001.jpg", "04-frames/v2/SH001.jpg", "04-frames/v2/SH001-last.jpg", "05-shots/SH001.mp4", "05-shots/v2/official/SH001.mp4"):
            p = self.prod / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(rel.encode())
        inspected = inspect_files(self.prod)
        self.assertTrue(inspected["frames"][0]["last"])
        self.assertEqual(inspected["video_count"], 1)
        self.assertEqual(inspected["context"]["revision_id"], "v2")
        frames = file_hashes(self.prod, "D")
        videos = file_hashes(self.prod, "E")
        self.assertIn("04-frames/v2/SH001-last.jpg", frames)
        self.assertNotIn("04-frames/SH001.jpg", frames)
        self.assertIn("05-shots/v2/official/SH001.mp4", videos)
        self.assertNotIn("05-shots/SH001.mp4", videos)
        self.assertIn(".pipeline/revisions.json", frames)

    def test_pipeline_show_does_not_virtually_lock_specs_packages_or_frames(self) -> None:
        from director.agents import previous_satisfied

        approvals = {"gates": {"C": {"locked": True}}}
        files = {"locked_frame_count": 31, "shot_count": 31}
        for gate in ("C1", "C2", "D"):
            self.assertFalse(virtual_locked(self.prod, gate, files, approvals), gate)
        self.assertFalse(previous_satisfied(self.prod, "D", files, approvals))
        self.assertFalse(previous_satisfied(self.prod, "E", files, approvals))
        approvals["gates"]["C2"] = {"locked": True}
        self.assertTrue(previous_satisfied(self.prod, "D", files, approvals))
        legacy = Path(self.tmp.name) / "legacy"
        legacy.mkdir()
        self.assertTrue(virtual_locked(legacy, "C1", files, {"gates": {"C": {"locked": True}}}))

    def test_registered_revision_cannot_inherit_file_only_virtual_lock(self) -> None:
        self.register()
        approvals = {"gates": {"C": {"locked": True}}}
        files = {"locked_frame_count": 53, "video_count": 53, "shot_count": 53, "episode_export": True}
        for gate in ("D", "E", "F"):
            self.assertFalse(virtual_locked(self.prod, gate, files, approvals))
        self.assertIn("缺指纹", stale_reason(self.prod, "C", approvals))
        result, dirty = ensure_lock_fingerprints(self.prod, approvals)
        self.assertFalse(dirty)
        self.assertNotIn("fingerprint", result["gates"]["C"])

    def test_task_context_routes_an_explicit_nonactive_revision(self) -> None:
        self.register("v2")
        self.register("v3")
        write(self.prod / ".pipeline/tables/v2.json", {"shots": [{"shot_id": "SH002"}]})
        write(self.prod / ".pipeline/tables/v3.json", {"shots": [{"shot_id": "SH003"}]})
        ctx = ProductionContext.resolve(self.prod, 1, "v2")
        with using_context(ctx):
            self.assertEqual(read_artifact(self.prod, "shot_list.json")["shots"][0]["shot_id"], "SH002")
            self.assertEqual(inspect_files(self.prod)["context"]["revision_id"], "v2")
            with patch("director.gates.subprocess.run") as called:
                called.return_value.returncode = 0
                called.return_value.stdout = ""
                called.return_value.stderr = ""
                run_check(self.prod)
            command = called.call_args.args[0]
            self.assertEqual(command[command.index("--revision") + 1], "v2")
        self.assertEqual(read_artifact(self.prod, "shot_list.json")["shots"][0]["shot_id"], "SH003")

    def test_selected_take_and_official_media_never_borrow_old_revision(self) -> None:
        self.register()
        old = self.prod / "05-shots/SH001.mp4"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old episode")
        with self.assertRaises(PermissionError):
            resolve_shot_media(self.prod, "SH001")
        current = self.prod / "05-shots/v2/official/SH001.mp4"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"new episode")
        self.assertEqual(resolve_shot_media(self.prod, "SH001"), current)
        media = self.prod / ".pipeline/takes/media/new.mp4"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"frozen take")
        take = Take("new", "SH001", "request", str(media.relative_to(self.prod)), hashlib.sha256(media.read_bytes()).hexdigest(), episode_id="ep01-v2", revision_id="v2")
        persist_take(self.prod, take)
        select_take(self.prod, "SH001", "new")
        self.assertEqual(selected_take_id(self.prod, "SH001"), "new")
        self.assertEqual(resolve_shot_media(self.prod, "SH001"), media)
        wrong = Take("old", "SH001", "old", str(media.relative_to(self.prod)), take.media_hash, episode_id="1")
        persist_take(self.prod, wrong)
        with self.assertRaisesRegex(PermissionError, "not ep01-v2"):
            select_take(self.prod, "SH001", "old")

    def test_dangling_selection_does_not_fall_back_to_official(self) -> None:
        self.register()
        current = self.prod / "05-shots/v2/official/SH001.mp4"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"new episode")
        write(self.prod / ".pipeline/takes.json", {"takes": [], "selected": {"ep01-v2:SH001": "lost"}})
        with self.assertRaisesRegex(PermissionError, "selected take missing"):
            resolve_shot_media(self.prod, "SH001")

    def test_explicit_episode_without_ep01_active_resolves_take_media(self) -> None:
        row = dict(revision(), episode_id="ep02", artifact_token="ep02-v2")
        register_revision(self.prod, row, activate=True)
        p = self.prod / ".pipeline/takes/media/ep2.mp4"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"episode two")
        take = Take("ep2", "SH001", "request", str(p.relative_to(self.prod)), hashlib.sha256(p.read_bytes()).hexdigest(), episode_id="ep02-v2", revision_id="v2")
        persist_take(self.prod, take)
        select_take(self.prod, "SH001", "ep2", episode=2)
        self.assertEqual(resolve_shot_media(self.prod, "SH001", episode=2), p)

    def test_registered_missing_table_never_borrows_unsuffixed_table(self) -> None:
        self.register()
        with self.assertRaisesRegex(RevisionError, "missing"):
            list_shots(self.prod)
        self.assertEqual(read_artifact(self.prod, "shot_list.json"), {})

    def test_registered_rows_cannot_route_frames_to_old_folder(self) -> None:
        self.register()
        write(self.prod / ".pipeline/tables/v2.json", {"shots": [{"shot_id": "SH001", "frame": "04-frames/SH001.jpg"}]})
        with self.assertRaisesRegex(ValueError, "outside registered"):
            list_shots(self.prod)

    def test_registered_rows_must_be_complete_and_unique(self) -> None:
        self.register()
        path = self.prod / ".pipeline/tables/v2.json"
        write(path, {"shots": [{"shot_id": "SH001"}, {"shot_id": "SH001"}]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            list_shots(self.prod)
        write(path, {"shots": [{"shot_id": "SH001"}, {}]})
        with self.assertRaisesRegex(ValueError, "malformed"):
            list_shots(self.prod)

    def test_registered_missing_active_requires_explicit_revision(self) -> None:
        self.register(activate=False)
        with self.assertRaisesRegex(RevisionError, "no active revision"):
            resolve_binding(self.prod)
        self.assertEqual(resolve_binding(self.prod, 1, "v2").revision_id, "v2")

    def test_unknown_revision_and_episode_never_fall_back(self) -> None:
        self.register()
        with self.assertRaises(RevisionError):
            resolve_binding(self.prod, 1, "old")
        with self.assertRaises(RevisionError):
            resolve_binding(self.prod, 2)
        with self.assertRaises(RevisionError):
            resolve_binding(self.prod, "ep01-old")

    def test_explicit_revision_overrides_active(self) -> None:
        self.register("v2")
        self.register("v3")
        write(self.prod / ".pipeline/tables/v2.json", {"shots": [{"shot_id": "SH002"}]})
        write(self.prod / ".pipeline/tables/v3.json", {"shots": [{"shot_id": "SH003"}]})
        self.assertEqual(list_shots(self.prod)[0]["id"], "SH003")
        self.assertEqual(list_shots(self.prod, revision_id="v2")[0]["id"], "SH002")
        self.assertEqual(read_artifact(self.prod, "shot_list.ep01-v2.json")["shots"][0]["shot_id"], "SH002")

    def test_global_reader_and_writer_route_to_registered_artifact(self) -> None:
        self.register()
        write_artifact(self.prod, "shot_list.json", {"shots": [{"shot_id": "SH007"}]})
        self.assertEqual(read_artifact(self.prod, "shot_list.json")["shots"][0]["shot_id"], "SH007")
        old = json.loads((self.prod / ".pipeline/shot_list.json").read_text())
        self.assertEqual(old["shots"][0]["shot_id"], "SH001")

    def test_paths_accept_local_absolute_and_reject_escape(self) -> None:
        row = revision()
        row["artifacts"]["events.json"] = str(self.prod / "narrative/events.json")
        row["cut_file"] = str(self.prod / "edits/cut.json")
        register_revision(self.prod, row, activate=True)
        ctx = ProductionContext.resolve(self.prod)
        self.assertEqual(ctx.artifact_rel("events.json"), "narrative/events.json")
        self.assertEqual(ctx.cut_rel(), "edits/cut.json")
        with self.assertRaisesRegex(ValueError, "outside .pipeline"):
            ctx.artifact_name("events.json")
        with self.assertRaises(RevisionError):
            register_revision(self.prod, dict(revision("bad"), frames_dir="../elsewhere"))
        with self.assertRaises(RevisionError):
            register_revision(self.prod, dict(revision("bad"), shots_dir=str(Path(self.tmp.name) / "elsewhere")))

    def test_invalid_registry_does_not_become_legacy(self) -> None:
        write(self.prod / ".pipeline/revisions.json", {"schema": "wrong"})
        with self.assertRaises(RevisionError):
            ProductionContext.resolve(self.prod)

    def test_registration_does_not_mutate_media_or_old_table(self) -> None:
        old = (self.prod / ".pipeline/shot_list.json").read_bytes()
        self.register(activate=False)
        self.assertEqual((self.prod / ".pipeline/shot_list.json").read_bytes(), old)
        self.assertFalse((self.prod / "04-frames").exists())
        self.assertFalse((self.prod / ".director").exists())
        activate_revision(self.prod, 1, "v2")
        self.assertEqual(load_registry(self.prod)["active"], {"ep01": "v2"})

    def test_source_report_binds_current_bytes_and_count(self) -> None:
        self.register()
        p = self.prod / ".pipeline/tables/v2.json"
        write(p, {"shots": [{"shot_id": "SH002"}, {"shot_id": "SH003"}]})
        report = resolve_binding(self.prod).source_report()
        self.assertEqual(report["shot_count"], 2)
        self.assertEqual(report["source_sha256"], hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(report["revision_id"], "v2")

    def test_checker_selects_active_and_reports_source(self) -> None:
        self.register()
        table = {"schema": "shot-table-v2", "shots": [{"shot_id": "SH009"}]}
        write(self.prod / ".pipeline/tables/v2.json", table)
        output = io.StringIO()
        with patch.object(check_storyboard, "check_v2") as checked, contextlib.redirect_stdout(output):
            check_storyboard.main(["--prod", str(self.prod)])
        self.assertEqual(checked.call_args.args[1], table)
        self.assertEqual(checked.call_args.args[2].revision_id, "v2")
        report = json.loads(output.getvalue().split("CHECK_SOURCE ", 1)[1])
        self.assertEqual(report["source_file"], ".pipeline/tables/v2.json")
        self.assertEqual(report["shot_count"], 1)

    def test_checker_blocks_missing_registered_table(self) -> None:
        self.register()
        with self.assertRaisesRegex(SystemExit, "registered revision missing"):
            check_storyboard.main(["--prod", str(self.prod)])

    def test_check_prod_forwards_episode_and_revision(self) -> None:
        with patch.object(check_prod.subprocess, "check_call") as called, contextlib.redirect_stdout(io.StringIO()):
            check_prod.main(["--prod", str(self.prod), "--episode", "2", "--revision", "v3"])
        args = called.call_args.args[0]
        self.assertEqual(args[args.index("--episode") + 1], "2")
        self.assertEqual(args[args.index("--revision") + 1], "v3")


if __name__ == "__main__":
    unittest.main()
