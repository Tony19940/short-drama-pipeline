#!/usr/bin/env python3
"""Compile and lock per-episode specs / packages / keyframe stubs for 009-siem-reap.

EP01 keeps historical filenames (shot_list.json, gen_packages.json, 04-frames/SH001.jpg).
EP02+ uses shot_list.epNN.json, gen_packages.epNN.json, 04-frames/epNN/.
Does not write 03-storyboard/shots.json and does not fill package keyframe_files.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.pipeline import (  # noqa: E402
    compile_packages_from_specs,
    episode_artifact_name,
    episode_frame_dir,
    episode_label,
    episode_number,
    packages_confirmed,
    parse_episode,
    read_artifact,
    validate_keyframes,
    validate_packages,
    write_artifact,
)
from director.production import load_json, read_text  # noqa: E402
from director.shot_table import (  # noqa: E402
    compile_specs_from_shot_table,
    render_shot_table_md,
    sanitize_shot_table,
    validate_shot_table,
)
from director.video_profiles import get_profile, resolve_target_model  # noqa: E402

SERIES_CAST = [
    {"id": "sokha", "name": "速卡"},
    {"id": "yunlong", "name": "云朗"},
    {"id": "padong", "name": "帕东"},
    {"id": "sari", "name": "萨里"},
    {"id": "shamon", "name": "沙蒙"},
    {"id": "patrol", "name": "高棉巡丁"},
    {"id": "guard", "name": "守卫"},
    {"id": "guard", "name": "寨兵甲"},
    {"id": "patrol", "name": "寨兵乙"},
    {"id": "siamese-rider", "name": "暹罗游骑"},
    {"id": "siamese-envoy", "name": "暹罗来使"},
    {"id": "siamese-captive", "name": "暹罗卒"},
    {"id": "siamese-captain", "name": "暹罗军头"},
    {"id": "scout", "name": "斥候"},
    {"id": "guide", "name": "导游"},
    {"id": "tourist", "name": "游客甲"},
]


def shot_list_name(episode) -> str:
    return episode_artifact_name("shot_list.json", episode)


def sets_rel(episode) -> str:
    label = episode_label(episode)
    return "03-storyboard/sets.json" if not label else f"03-storyboard/sets.{label}.json"


def load_table(prod: Path, episode: int) -> dict:
    name = shot_list_name(episode)
    data = read_artifact(prod, name)
    if not data.get("shots"):
        raise SystemExit(f"missing or empty {name}")
    return data


def writer_from_table(table: dict) -> dict:
    scenes: dict[str, dict] = {}
    for shot in table.get("shots") or []:
        sid = str(shot.get("scene_id") or "")
        if not sid:
            continue
        scene = scenes.setdefault(
            sid,
            {
                "scene_id": sid,
                "location_id": shot.get("location_id") or "",
                "dialogue": [],
            },
        )
        if shot.get("location_id") and not scene.get("location_id"):
            scene["location_id"] = shot.get("location_id")
        for item in shot.get("dialogue_ref") or []:
            if isinstance(item, dict) and str(item.get("line") or "").strip():
                scene["dialogue"].append(
                    {
                        "character": item.get("character") or item.get("speaker") or "",
                        "line": item.get("line"),
                    }
                )
    chars = []
    seen = set()
    for item in SERIES_CAST:
        key = (item["id"], item["name"])
        if key in seen:
            continue
        seen.add(key)
        chars.append(item)
    return {
        "series_bible": {"characters": chars, "logline": "暹粒", "locations": []},
        "scenes": list(scenes.values()),
        "episode_outline": [{"title": f"第 {int(table.get('episode_no') or 1):02d} 集"}],
    }


def load_sets(prod: Path, episode: int) -> dict:
    path = prod / sets_rel(episode)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return load_json(prod, "03-storyboard/sets.json", {"sets": []})


def load_writer(prod: Path, episode: int, table: Optional[dict] = None) -> dict:
    from director.pipeline import episode_artifact_name, read_artifact

    data = read_artifact(prod, episode_artifact_name("writer.json", episode))
    if data.get("scenes"):
        return data
    return writer_from_table(table or {})


def validate_episode(prod: Path, episode: int, table: Optional[dict] = None) -> tuple[list[str], list[str], dict]:
    table = sanitize_shot_table(table or load_table(prod, episode), writer=None)
    writer = load_writer(prod, episode, table)
    table = sanitize_shot_table(table, writer=writer)
    sets = load_sets(prod, episode)
    look = read_text(prod, "02-assets/LOOK.md")
    model = resolve_target_model(prod, table.get("target_model") or "seedance_2_0")
    profile = get_profile(model)
    errors, warnings = validate_shot_table(
        table,
        writer=writer,
        sets=sets,
        profile=profile,
        look_text=look,
        prod=prod,
    )
    return errors, warnings, table


def compile_episode(
    prod: Path,
    episode,
    *,
    confirm: bool = True,
    write: bool = True,
    from_table: bool = False,
) -> dict:
    ep_no, label = parse_episode(episode)
    errors, warnings, table = validate_episode(prod, episode)
    if errors and not from_table:
        return {"ok": False, "episode": episode, "errors": errors, "warnings": warnings}
    if errors and from_table:
        warnings = list(warnings) + [f"[from-table] {item}" for item in errors]
    specs = compile_specs_from_shot_table(table, aspect=table.get("aspect") or "16:9")
    packages = compile_packages_from_specs(
        prod,
        target_model=table.get("target_model") or "seedance_2_0",
        table=table,
        specs=specs,
        writer=load_writer(prod, episode, table),
        frame_descriptions=read_artifact(prod, episode_artifact_name("frame_descriptions.json", episode)),
    )
    if confirm:
        packages["confirmed"] = True
        packages["status"] = "ready"
        for item in packages.get("packages") or []:
            item["confirmed"] = True
            item["keyframe_files"] = []
    pkg_errors = validate_packages(packages, read_artifact(prod, "assets.json"), specs, prod=prod)
    pkg_errors = list(pkg_errors) + list(packages.get("errors") or [])
    if pkg_errors and not from_table:
        return {
            "ok": False,
            "episode": episode,
            "errors": pkg_errors,
            "warnings": warnings,
            "packages": packages,
            "specs": specs,
            "table": table,
        }
    if pkg_errors and from_table:
        warnings = list(warnings) + [f"[from-table] {item}" for item in pkg_errors]
    result = {
        "ok": True,
        "episode": episode,
        "errors": [] if from_table else [],
        "warnings": warnings,
        "shot_count": len(table.get("shots") or []),
        "package_count": len(packages.get("packages") or []),
        "confirmed": packages_confirmed(packages),
        "table": table,
        "specs": specs,
        "packages": packages,
    }
    if write:
        table_out = dict(table)
        table_out["status"] = "ready"
        table_out["agent"] = "design"
        table_out["updated_at"] = int(time.time())
        table_out["warnings"] = warnings
        write_artifact(prod, shot_list_name(episode), table_out)
        specs["status"] = "ready"
        specs["origin"] = "compiled-from-shot-table"
        write_artifact(prod, episode_artifact_name("shot_specs.json", episode), specs)
        packages["origin"] = "compiled-from-shot-table"
        packages["episode_no"] = ep_no
        packages["episode_label"] = label or f"ep{ep_no:02d}"
        write_artifact(prod, episode_artifact_name("gen_packages.json", episode), packages)
        sidecar = episode_artifact_name("gen_packages.seedance_2_5.json", episode)
        wrote_25 = ""
        # Labeled variants never inherit or overwrite the unsuffixed 2.5 lock.
        if (prod / ".pipeline" / sidecar).exists():
            extra = compile_packages_from_specs(
                prod,
                target_model="seedance_2_5",
                table=table,
                specs=specs,
                writer=load_writer(prod, episode, table),
                frame_descriptions=read_artifact(prod, episode_artifact_name("frame_descriptions.json", episode)),
            )
            extra["origin"] = "compiled-from-shot-table"
            extra["episode_no"] = ep_no
            extra["episode_label"] = label or f"ep{ep_no:02d}"
            extra["confirmed"] = False
            extra["status"] = "draft"
            for item in extra.get("packages") or []:
                item["confirmed"] = False
                item["keyframe_files"] = []
                item["generate_audio"] = True
            write_artifact(prod, sidecar, extra)
            wrote_25 = sidecar
        profile = get_profile(resolve_target_model(prod, table.get("target_model") or "seedance_2_0"))
        md = render_shot_table_md(
            table_out,
            title=f"第 {ep_no:02d} 集" + (f" · {label}" if label else ""),
            profile=profile,
            warnings=warnings,
        )
        md_name = "03-storyboard/shot-list.md" if not label else f"03-storyboard/shot-list.{label}.md"
        dest = prod / md_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        result["wrote"] = {
            "shot_list": shot_list_name(episode),
            "shot_specs": episode_artifact_name("shot_specs.json", episode),
            "gen_packages": episode_artifact_name("gen_packages.json", episode),
            "table_md": md_name,
        }
        if wrote_25:
            result["wrote"]["gen_packages_2_5"] = wrote_25
    return result


def qc_pass(shot: dict, plan: str) -> dict:
    scale = str(shot.get("scale") or "")
    coverage = str(shot.get("coverage_type") or "")
    tight = scale in {"close", "otc", "insert"} or coverage in {"close", "reaction"}
    qc = {
        "status": "n/a",
        "face": "n/a",
        "costume": "n/a",
        "location": "n/a",
        "left_right": "n/a",
        "composition": "n/a",
        "aspect_ratio": "n/a",
        "light_matches_spec": "n/a",
        "state_match": "n/a",
    }
    if plan == "first_last":
        qc["out_to_readable"] = "n/a"
    if tight:
        qc["plastic_face"] = "n/a"
        qc["anatomy"] = "n/a"
    return qc


def build_keyframes(prod: Path, episode, *, reviewed_by: str = "tonyteacher") -> dict:
    table = load_table(prod, episode)
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    plans = {
        str(item.get("shot_id")): str(item.get("keyframe_plan") or "first")
        for item in (packages.get("packages") or [])
    }
    shots = {str(item.get("shot_id")): item for item in (table.get("shots") or [])}
    folder = episode_frame_dir(episode)
    frames = []
    missing = []
    for sid, shot in shots.items():
        plan = plans.get(sid) or "first"
        first_rel = f"{folder}/{sid}.jpg"
        last_rel = f"{folder}/{sid}-last.jpg"
        item = {
            "shot_id": sid,
            "first_frame_file": first_rel,
            "qc": qc_pass(shot, plan),
        }
        if plan == "first_last":
            item["last_frame_file"] = last_rel
        if not (prod / first_rel).exists():
            missing.append(first_rel)
        if plan == "first_last" and not (prod / last_rel).exists():
            missing.append(last_rel)
        frames.append(item)
    payload = {
        "project_id": prod.name,
        "agent": "keyframes",
        "status": "ready" if not missing else "draft",
        "origin": f"series-prep-{episode_label(episode) or f'ep{episode_number(episode):02d}'}",
        "reviewed_by": reviewed_by,
        "episode_no": episode_number(episode),
        "target_model": table.get("target_model") or "seedance_2_0",
        "aspect_ratio": table.get("aspect") or "16:9",
        "updated_at": int(time.time()),
        "notes": "用户授权推进到可出视频，不另等人审。keyframe_files 仍为空。",
        "keyframes": frames,
    }
    errors = []
    if missing:
        errors = [f"missing {path}" for path in missing]
    else:
        errors = validate_keyframes(
            payload,
            packages=packages,
            specs=read_artifact(prod, episode_artifact_name("shot_specs.json", episode)),
            table=table,
            prod=prod,
        )
    if not errors:
        write_artifact(prod, episode_artifact_name("keyframes.json", episode), payload)
    return {"ok": not errors, "errors": errors, "missing": missing, "payload": payload, "count": len(frames)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", required=True, help="集数或标签：1、2、ep01-v2")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-confirm", action="store_true")
    parser.add_argument("--from-table", action="store_true", help="从表确定性编包；校验失败仍写包，不覆盖无后缀锁画")
    parser.add_argument("--keyframes", action="store_true", help="write keyframes artifact if frames exist")
    args = parser.parse_args()
    prod = Path(args.prod)
    if not prod.is_absolute():
        prod = (ROOT / prod).resolve()
    if args.validate_only:
        errors, warnings, table = validate_episode(prod, args.episode)
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings, "shots": len(table.get("shots") or [])}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    result = compile_episode(
        prod, args.episode, confirm=not args.no_confirm, write=True, from_table=args.from_table
    )
    printable = {k: result[k] for k in ("ok", "episode", "errors", "warnings", "shot_count", "package_count", "confirmed", "wrote") if k in result}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        return 1
    if args.keyframes:
        kf = build_keyframes(prod, args.episode)
        print(json.dumps({k: kf[k] for k in ("ok", "errors", "missing", "count")}, ensure_ascii=False, indent=2))
        if not kf.get("ok"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
