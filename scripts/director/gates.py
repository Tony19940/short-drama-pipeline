"""Human-lock gates. Files exist != a gate is approved."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .agents import (
    AGENTS,
    LOCKABLE,
    UNLOCK_DOWNSTREAM,
    annotate_agent,
    ensure_lock_fingerprints,
    lock_record,
    previous_satisfied,
)
from .paths import ROOT
from .store import load_approvals, save_approvals

GATES = AGENTS
GATE_ORDER = [g["id"] for g in GATES]
LEGACY_GATES = [
    {"id": "S", "label": "舞台", "tab": "stage"},
    {"id": "D", "label": "首帧", "tab": "frames"},
]


def _exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _shots(prod: Path) -> list[dict]:
    path = prod / "03-storyboard" / "shots.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("shots") or [])


def _costume_state_dirs(prod: Path) -> set[str]:
    from .pipeline import read_artifact, uses_pipeline

    if not uses_pipeline(prod):
        return set()
    character_folders: set[str] = set()
    costume_folders: set[str] = set()
    for item in (read_artifact(prod, "assets.json").get("assets") or []):
        rel = str(item.get("file") or "").replace(chr(92), "/")
        parts = [part for part in rel.split("/") if part]
        folder = ""
        if "characters" in parts:
            idx = parts.index("characters")
            if idx + 1 < len(parts):
                folder = parts[idx + 1]
        kind = str(item.get("type") or "")
        if kind == "character" and folder:
            character_folders.add(folder)
        if kind == "costume_state" and folder:
            costume_folders.add(folder)
    return costume_folders - character_folders


def _v2_frame_rows(prod: Path, episode: int = 1) -> list[dict]:
    """Count official frames from shot-table-v2 when there is no legacy shots.json."""
    from .pipeline import episode_artifact_name, read_artifact, uses_pipeline
    from place_codex_frame import episode_frame_dir

    if not uses_pipeline(prod):
        return []
    table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
    folder = episode_frame_dir(episode)
    rows = []
    for item in table.get("shots") or []:
        sid = str(item.get("shot_id") or "").strip()
        if not sid:
            continue
        rows.append(
            {
                "id": sid,
                "frame": f"{folder}/{sid}.jpg",
                "last_frame": f"{folder}/{sid}-last.jpg",
            }
        )
    return rows


def inspect_files(prod: Path, episode: int = 1) -> dict:
    shots = _shots(prod)
    frame_shots = shots or _v2_frame_rows(prod, episode)
    frames = []
    for shot in frame_shots:
        frame = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
        last = prod / shot.get("last_frame", f"04-frames/{shot['id']}-last.jpg")
        video = prod / "05-shots" / f"{shot['id']}.mp4"
        frames.append(
            {
                "id": shot["id"],
                "frame": _exists(frame),
                "last": _exists(last),
                "video": _exists(video),
                "parent": parent_still(prod, shot, shots) if shots else {"kind": "pipeline", "path": shot.get("frame", ""), "exists": _exists(frame), "reason": "shot-table-v2 首帧"},
            }
        )
    blocking = list((prod / "02-assets" / "scenes").glob("*/blocking.jpg")) if (prod / "02-assets" / "scenes").exists() else []
    characters = []
    char_root = prod / "02-assets" / "characters"
    if char_root.exists():
        for child in sorted(char_root.iterdir()):
            if child.is_dir():
                characters.append(
                    {
                        "id": child.name,
                        "master": _exists(child / "master.jpg"),
                        "face": _exists(child / "face.jpg"),
                        "front": _exists(child / "front.jpg"),
                        "side": _exists(child / "side.jpg"),
                        "back": _exists(child / "back.jpg"),
                        "sheet": _exists(child / "sheet.jpg"),
                        "costume_state": child.name in _costume_state_dirs(prod),
                    }
                )
    scenes = []
    scene_root = prod / "02-assets" / "scenes"
    if scene_root.exists():
        for child in sorted(scene_root.iterdir()):
            if child.is_dir():
                scenes.append(
                    {
                        "id": child.name,
                        "master": _exists(child / "master.jpg"),
                        "blocking": _exists(child / "blocking.jpg"),
                    }
                )
    return {
        "confirm": _exists(prod / "01-bible" / "confirm.md"),
        "blueprint": _exists(prod / "01-bible" / "blueprint.md"),
        "episode": _exists(prod / "01-bible" / "ep01.md"),
        "sets": _exists(prod / "03-storyboard" / "sets.json"),
        "coverage": _exists(prod / "03-storyboard" / "coverage.md"),
        "beats": _exists(prod / "03-storyboard" / "beats.md"),
        "shots": _exists(prod / "03-storyboard" / "shots.json"),
        "blocking": bool(blocking),
        "characters": characters,
        "scenes": scenes,
        "frames": frames,
        "review": any((prod / "06-export").glob("preview-*-vo.mp4")) or (prod / "06-export" / "preview-vo.mp4").exists(),
        "episode_export": _exists(prod / "06-export" / "ep01.mp4"),
        "source": _exists(prod / "01-bible" / "source" / "source.json") and _exists(prod / "01-bible" / "source" / "original.md"),
        "producer": _exists(prod / "01-bible" / "producer" / "plan.md") and _exists(prod / "01-bible" / "producer" / "manifest.json"),
        "qc": _exists(prod / "08-qc" / "report.json") or _exists(prod / "01-bible" / "qc" / "report.md"),
        "shot_count": len(frame_shots),
        "video_count": sum(1 for item in frames if item["video"]),
        "locked_frame_count": sum(1 for item in frames if item["frame"]),
    }


def parent_still(prod: Path, shot: dict, shots: Optional[list[dict]] = None) -> dict:
    shots = shots if shots is not None else _shots(prod)
    derived = str(shot.get("derived_from") or "")
    scene = str(shot.get("scene") or "")
    if derived.endswith(".blocking") or (shot.get("cut") == "hard" and not shot.get("from")):
        blocking = prod / "02-assets" / "scenes" / scene / "blocking.jpg"
        return {
            "kind": "blocking",
            "path": str(blocking.relative_to(prod)),
            "exists": _exists(blocking),
            "reason": f"一场第一镜从 {scene}.blocking 改",
        }
    prev_id = shot.get("from") or derived
    prev = next((item for item in shots if item.get("id") == prev_id), None)
    if prev:
        frame = prod / prev.get("frame", f"04-frames/{prev['id']}.jpg")
        return {
            "kind": "previous_frame",
            "path": str(frame.relative_to(prod)),
            "exists": _exists(frame),
            "reason": f"续镜从 {prev['id']} 首帧改",
            "from": prev["id"],
        }
    return {"kind": "missing", "path": "", "exists": False, "reason": "找不到父镜"}


def v2_storyboard_ready(prod: Path) -> tuple[bool, str]:
    """Official storyboard for pipeline shows is `.pipeline/shot_list.json` (shot-table-v2).

    Legacy coverage.md / beats.md / shots.json / blocking.jpg are not required when
    that table exists and validates. Returns ("", "") when this prod is not on v2.
    """
    from .pipeline import SHOT_TABLE_SCHEMA, read_artifact, uses_pipeline, validate_shot_list

    if not uses_pipeline(prod):
        return False, ""
    shot_list = read_artifact(prod, "shot_list.json")
    if not shot_list:
        return False, ""
    if str(shot_list.get("schema") or "") != SHOT_TABLE_SCHEMA:
        return False, ""
    from .shot_table import table_context

    context = table_context(prod, shot_list.get("target_model"))
    errors = validate_shot_list(shot_list, **context)
    if errors:
        return False, errors[0]
    count = len(shot_list.get("shots") or [])
    status = str(shot_list.get("status") or "draft")
    return True, f"分镜表 shot-table-v2 {count} 镜已过校验（{status}）"


def continue_last_frame_rule(shot: dict, prev: Optional[dict]) -> tuple[bool, str]:
    """Same-setup continue may eat the previous last frame; coverage cuts may not.

    This is the contract without checking that `{from}-last.jpg` exists yet.
    Runtime I2V still requires the file; Grok task cards can announce the rule earlier.
    """
    if shot.get("cut") != "continue" or not shot.get("from"):
        return False, "开场/硬切用锁定首帧"
    if prev is None:
        return False, f"找不到上一镜 {shot.get('from')}，用本镜设计首帧"
    overlap = set(shot.get("characters") or []) & set(prev.get("characters") or [])
    same_setup = shot.get("setup") == prev.get("setup")
    if same_setup and overlap:
        return True, f"同机位续，人物有交集，I2V 吃 {shot['from']}-last.jpg"
    if overlap and not same_setup:
        return False, "换机位用刚锁定的新首帧，不吃上一镜末帧"
    return False, "覆盖切到另一人，用刚锁定的新首帧，不误用上一镜末帧"


def designed_end_frame(prod: Path, shot: dict) -> dict:
    """Optional designed last frame. Generated `{id}-last.jpg` is never this."""
    rel = str(shot.get("end_frame") or "").strip()
    if not rel:
        return {
            "kind": "none",
            "path": "",
            "exists": False,
            "ok": True,
            "reason": "无设计尾帧，只锁首帧出片",
        }
    name = Path(rel).name.lower()
    frame_rel = str(shot.get("frame") or f"04-frames/{shot['id']}.jpg")
    if name.endswith("-last.jpg"):
        return {
            "kind": "invalid",
            "path": rel,
            "exists": False,
            "ok": False,
            "reason": "end_frame 不能是生成后抽出的 -last.jpg",
        }
    if Path(rel).as_posix() == Path(frame_rel).as_posix():
        return {
            "kind": "invalid",
            "path": rel,
            "exists": False,
            "ok": False,
            "reason": "end_frame 不能等于本镜首帧",
        }
    path = prod / rel
    exists = _exists(path)
    return {
        "kind": "designed_end",
        "path": rel,
        "exists": exists,
        "ok": exists,
        "reason": "设计尾帧，动作用这个收住" if exists else f"缺设计尾帧 {rel}",
    }


def i2v_source(prod: Path, shot: dict, shots: Optional[list[dict]] = None) -> dict:
    shots = shots if shots is not None else _shots(prod)
    designed = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
    designed_rel = str(designed.relative_to(prod))
    prev = next((item for item in shots if item.get("id") == shot.get("from")), None)
    eats, why = continue_last_frame_rule(shot, prev)
    if not eats:
        return {
            "kind": "designed_frame",
            "path": designed_rel,
            "exists": _exists(designed),
            "reason": why,
            "from": shot.get("from"),
        }
    last_rel = str((prev or {}).get("last_frame") or f"04-frames/{shot['from']}-last.jpg")
    last = prod / last_rel
    if last.exists():
        return {
            "kind": "last_frame",
            "path": str(last.relative_to(prod)),
            "exists": True,
            "reason": why,
            "from": shot.get("from"),
        }
    return {
        "kind": "designed_frame",
        "path": designed_rel,
        "exists": _exists(designed),
        "reason": why + "；上一镜末帧还没有，先用本镜设计首帧",
        "from": shot.get("from"),
    }


def run_check(prod: Path) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts" / "check_prod.py"), "--prod", str(prod)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def _c2_still_t0_note(prod: Path) -> str:
    """Warn on first-still result text without failing the C2 lock (later-ep artifacts)."""
    from .frame_desc import index_by_shot
    from .pipeline import read_artifact
    from .still_t0 import issues_for_table

    table = read_artifact(prod, "shot_list.json")
    descs = index_by_shot(read_artifact(prod, "frame_descriptions.json"))
    warns = issues_for_table(list(table.get("shots") or []), descs)
    if not warns:
        return ""
    return f"（首帧 t=0 警告 {len(warns)}：{warns[0]}）"


def gate_file_ready(prod: Path, gate_id: str, files: Optional[dict] = None, episode: int = 1) -> tuple[bool, str]:
    files = files or inspect_files(prod, episode)
    if gate_id == "0":
        if files.get("source"):
            return True, "故事源已归一到 01-bible/source/"
        from .agents import story_migrated

        if story_migrated(prod):
            return True, "已从旧剧本迁移，未改写正式剧本"
        return False, "还没有故事源。填简报后上传 Inkos 导出，或上传小说/剧本"
    if gate_id == "A":
        missing = [name for name in ("confirm", "blueprint", "episode") if not files[name]]
        return (not missing, "缺 " + ", ".join(missing) if missing else "剧本/确认/蓝图齐全")
    if gate_id == "B":
        if not files["characters"]:
            return False, "还没有角色主图"
        for item in files["characters"]:
            if item.get("costume_state"):
                if not item["master"]:
                    return False, "服装状态 %s 缺 master.jpg" % item["id"]
                continue
            if not item["master"] or not item["face"]:
                return False, "每个角色都要 master.jpg + face.jpg"
        if not files["scenes"] or any(not item["master"] for item in files["scenes"]):
            return False, "每个主场景都要空镜 master.jpg"
        return True, "角色/场景主图齐全"
    if gate_id == "P":
        if files.get("producer"):
            return True, "制片任务单已在"
        from .agents import actually_locked

        if actually_locked(load_approvals(prod), "B"):
            return True, "随美术关迁移锁定，可再生成缺口清单"
        producer_draft = (prod / "01-bible" / "producer" / "plan.draft.md").exists()
        if producer_draft:
            return False, "制片草稿待接受锁定"
        return False, "还没有制片任务单，先生成缺口清单"
    if gate_id == "S":
        if not files["sets"]:
            return False, "缺 sets.json"
        if not files["blocking"]:
            return False, "缺 blocking.jpg，先打点再出舞台"
        return True, "舞台和 blocking 已在"
    if gate_id == "C":
        v2_ok, v2_reason = v2_storyboard_ready(prod)
        if v2_ok:
            return True, v2_reason
        if v2_reason:
            return False, v2_reason
        missing = [name for name in ("coverage", "beats", "shots") if not files[name]]
        if missing:
            return False, "缺 " + ", ".join(missing)
        check = run_check(prod)
        if not check["ok"]:
            return False, check["stderr"] or check["stdout"] or "check_prod 未过"
        return True, check["stdout"] or "分镜合同已过 check_prod"
    if gate_id == "C1":
        from .pipeline import read_artifact, uses_pipeline, validate_shot_specs
        specs = read_artifact(prod, "shot_specs.json")
        writer = read_artifact(prod, "writer.json")
        if uses_pipeline(prod):
            if not specs:
                return False, "还没有分镜说明书"
            errors = validate_shot_specs(specs, writer)
            if errors:
                return False, errors[0]
            return True, "说明书已齐"
        if files.get("shots"):
            return True, "沿用旧分镜说明书字段"
        return False, "还没有分镜说明书"
    if gate_id == "C2":
        from .pipeline import packages_confirmed, read_artifact, uses_pipeline, validate_packages
        packages = read_artifact(prod, "gen_packages.json")
        assets = read_artifact(prod, "assets.json")
        specs = read_artifact(prod, "shot_specs.json")
        if uses_pipeline(prod):
            if not packages:
                return False, "还没有生成包"
            errors = validate_packages(packages, assets, specs)
            if errors:
                return False, errors[0]
            if not packages_confirmed(packages):
                return False, "生成包还没确认"
            note = _c2_still_t0_note(prod)
            return True, "生成包已确认" + note
        if files.get("shots"):
            return True, "沿用旧 video_prompt 作为生成计划"
        return False, "还没有生成包"
    if gate_id == "D":
        from .pipeline import keyframe_context, read_artifact, uses_pipeline, validate_keyframes

        if uses_pipeline(prod):
            from .pipeline import episode_artifact_name
            from place_codex_frame import episode_frame_dir, parent_chain_errors

            table = read_artifact(prod, episode_artifact_name("shot_list.json", episode))
            shots = table.get("shots") or []
            if not shots:
                return False, "还没有分镜"
            folder = episode_frame_dir(episode)
            missing = [
                str(item.get("shot_id") or "")
                for item in shots
                if str(item.get("shot_id") or "") and not _exists(prod / f"{folder}/{item['shot_id']}.jpg")
            ]
            if missing:
                return False, "缺首帧 " + ", ".join(missing)
            frames = read_artifact(prod, episode_artifact_name("keyframes.json", episode))
            if not frames:
                return False, "还没有 keyframes.json"
            errors = validate_keyframes(frames, **keyframe_context(prod, episode))
            if errors:
                return False, errors[0]
            chain = parent_chain_errors(prod, shots, episode=episode)
            if chain:
                return False, chain[0]
            return True, f"{len(shots)} 张首帧已按顺序锁，keyframes 已过校验"
        if not files["shot_count"]:
            return False, "还没有分镜"
        shots = _shots(prod)
        missing = [item["id"] for item in files["frames"] if not item["frame"]]
        if missing:
            return False, "缺首帧 " + ", ".join(missing)
        for i, shot in enumerate(shots):
            start = str(shot.get("start") or "").strip()
            if len(start) < 12:
                return False, f"{shot.get('id')} 缺第 0 秒站位 start"
            parent = parent_still(prod, shot, shots)
            if not parent.get("exists"):
                return False, parent.get("reason") or f"{shot.get('id')} 缺父图"
            frame = prod / shot.get("frame", f"04-frames/{shot['id']}.jpg")
            if not frame.exists():
                return False, f"缺首帧 {shot.get('id')}"
            if i:
                prev = shots[i - 1]
                prev_frame = prod / prev.get("frame", f"04-frames/{prev['id']}.jpg")
                if not prev_frame.exists():
                    return False, f"{shot.get('id')} 的上一镜 {prev.get('id')} 还没锁"
        frames = read_artifact(prod, "keyframes.json")
        if frames:
            errors = validate_keyframes(frames, **keyframe_context(prod))
            if errors:
                return False, errors[0]
        return True, f"{files['locked_frame_count']} 张首帧已按顺序锁，父图链齐"
    if gate_id == "E":
        from .pipeline import read_artifact, uses_pipeline, validate_clips
        if uses_pipeline(prod) and read_artifact(prod, "clips.json"):
            errors = validate_clips(read_artifact(prod, "clips.json"))
            if errors:
                return False, errors[0]
        if not files["video_count"]:
            return False, "还没有单镜视频"
        missing = [item["id"] for item in files["frames"] if not item["video"]]
        if missing:
            return False, "缺视频 " + ", ".join(missing)
        if uses_pipeline(prod):
            from .animatic import animatic_rel

            frames_locked = bool(files["frames"]) and all(item.get("frame") for item in files["frames"])
            anim = prod / animatic_rel(1)
            if frames_locked and not anim.exists():
                return False, f"缺静帧 animatic {animatic_rel(1)}；正式出片前先出 animatic（05-shots/smoke 不受此限）"
        return True, f"{files['video_count']} 条单镜已在"
    if gate_id == "E+":
        from .pipeline import read_artifact, uses_pipeline, validate_audio
        audio = read_artifact(prod, "audio.json")
        if uses_pipeline(prod) and audio:
            errors = validate_audio(audio, read_artifact(prod, "writer.json"), prod)
            if errors:
                return False, errors[0]
        if not files["review"]:
            return False, "缺带声带字的 preview-*-vo.mp4"
        return True, "审剧情轨已在"
    if gate_id == "F":
        from .pipeline import read_artifact, uses_pipeline, validate_cut
        cut = read_artifact(prod, "cut.json")
        if uses_pipeline(prod) and cut:
            errors = validate_cut(cut)
            if errors:
                return False, errors[0]
        if not files.get("episode_export"):
            return False, "缺 06-export/ep01.mp4"
        return True, "成片已在，可出审片报告"
    return False, f"未知关卡 {gate_id}"


def snapshot(prod: Path) -> dict:
    files = inspect_files(prod)
    approvals = load_approvals(prod)
    approvals, _ = ensure_lock_fingerprints(prod, approvals)
    gates = []
    for spec in GATES:
        ready, reason = gate_file_ready(prod, spec["id"], files)
        if spec["id"] == "C" and not v2_storyboard_ready(prod)[0]:
            s_ok, s_reason = gate_file_ready(prod, "S", files)
            if not s_ok:
                ready, reason = False, s_reason
        gates.append(annotate_agent(spec, prod, files, approvals, ready, reason))
    return {
        "files": files,
        "gates": gates,
        "check": run_check(prod) if files["shots"] else {"ok": False, "stdout": "", "stderr": "还没有 shots.json"},
        "approvals": approvals,
    }


def previous_locked(prod: Path, gate_id: str) -> bool:
    files = inspect_files(prod)
    approvals = load_approvals(prod)
    return previous_satisfied(prod, gate_id, files, approvals)


def _promote_on_lock(prod: Path, gate_id: str) -> None:
    if gate_id == "0":
        from .story import promote_story_drafts

        promote_story_drafts(prod)
    elif gate_id == "P":
        from .producer import promote_producer_drafts

        promote_producer_drafts(prod)
    elif gate_id == "E+":
        from .sound_contract import promote_sound_draft

        promote_sound_draft(prod)
    elif gate_id == "F":
        from .qc import promote_qc_drafts

        promote_qc_drafts(prod)


def lock_gate(prod: Path, gate_id: str, locked: bool = True) -> dict:
    if gate_id not in LOCKABLE:
        raise ValueError(f"未知关卡 {gate_id}")
    files = inspect_files(prod)
    if locked:
        _promote_on_lock(prod, gate_id)
        files = inspect_files(prod)
        ready, reason = gate_file_ready(prod, gate_id, files)
        if gate_id == "C" and not v2_storyboard_ready(prod)[0]:
            s_ok, s_reason = gate_file_ready(prod, "S", files)
            if not s_ok:
                ready, reason = False, s_reason
        if not previous_locked(prod, gate_id):
            raise PermissionError(f"上一关还没锁定，不能锁 {gate_id}")
        if not ready:
            raise PermissionError(reason)
    approvals = load_approvals(prod)
    import time

    approvals.setdefault("gates", {})
    if locked:
        reason = gate_file_ready(prod, gate_id, files)[1]
        approvals["gates"][gate_id] = lock_record(prod, gate_id, reason, int(time.time()))
        if gate_id == "C":
            s_ok, s_reason = gate_file_ready(prod, "S", files)
            if s_ok and not (approvals["gates"].get("S") or {}).get("locked"):
                approvals["gates"]["S"] = lock_record(prod, "S", s_reason, int(time.time()))
            from .pipeline import uses_pipeline
            if not uses_pipeline(prod):
                for extra, extra_reason in (("C1", "沿用旧分镜说明书"), ("C2", "沿用旧生成计划")):
                    extra_ok, extra_msg = gate_file_ready(prod, extra, files)
                    if extra_ok and not (approvals["gates"].get(extra) or {}).get("locked"):
                        approvals["gates"][extra] = lock_record(prod, extra, extra_reason or extra_msg, int(time.time()))
    else:
        for later in [gate_id] + UNLOCK_DOWNSTREAM.get(gate_id, []):
            approvals["gates"].pop(later, None)
    save_approvals(prod, approvals)
    return snapshot(prod)


def require_gate(prod: Path, gate_id: str) -> None:
    approvals = load_approvals(prod)
    if not (approvals.get("gates") or {}).get(gate_id, {}).get("locked"):
        raise PermissionError(f"关卡 {gate_id} 未锁定")


def require_fresh_gate(prod: Path, gate_id: str) -> None:
    require_gate(prod, gate_id)
    from .agents import assert_not_stale

    assert_not_stale(prod, gate_id)


def ken_burns_blocked(path: Path) -> bool:
    name = path.name.lower()
    return "kenburns" in name or "still-pass" in name or "animatic" in name or name.endswith(".kenburns.mp4")
