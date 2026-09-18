#!/usr/bin/env python3
"""Paper-prep one or more episodes: writer → sets → design → frame_desc → Seedance packages.

EP01 keeps historical filenames. EP02+ writes suffixed artifacts and never overwrites
`.pipeline/shot_list.json` / `writer.json` / `gen_packages.json`.
Does not generate keyframes or video. Does not lock Gate C (prod-wide, EP01 fingerprint).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

os.environ.setdefault("GROK_DESIGN_EFFORT", "low")
os.environ.setdefault("GROK_DESIGN_RETRIES", "3")
os.environ.setdefault("GROK_DESIGN_CANDIDATES", "1")

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import compile_episode  # noqa: E402
from director.grok_text import TextError, text_backend, text_configured  # noqa: E402
from director.pipeline import episode_artifact_name, read_artifact, write_artifact  # noqa: E402
from director.production import load_json, read_text, write_text  # noqa: E402
from director.shot_table import fit_writer_dialogue  # noqa: E402
from director.station_agents import (  # noqa: E402
    run_station_agent,
    sets_rel,
    shot_list_artifact_name,
    storyboard_md_name,
    writer_artifact_name,
)

LOCATION_ALIASES = {
    "factory-corridor": "factory-gate",
    "factory-road": "factory-gate",
    "factory-yard": "factory-gate",
    "factory-night": "factory-gate",
    "dorm-road": "dorm",
    "banquet-corridor": "banquet",
    "show-line": "line-7",
    "power-room-door": "breaker-room",
    "office-window": "factory-office",
    "factory-office-door": "factory-office",
    "assistant-desk": "factory-office",
    "river-road": "river-bank",
    "ceremony-screen": "ceremony-stage",
    "stair": "banquet",
    "canteen": "canteen-back",
}

EP01_LOCK_FILES = (
    ".pipeline/writer.json",
    ".pipeline/shot_list.json",
    ".pipeline/shot_specs.json",
    ".pipeline/frame_descriptions.json",
    ".pipeline/gen_packages.json",
    ".pipeline/gen_packages.seedance_2_5.json",
    ".pipeline/scene_cards.json",
    ".pipeline/keyframes.json",
    "03-storyboard/sets.json",
    "03-storyboard/shot_list.json",
    "03-storyboard/shot-list.md",
    "03-storyboard/scene-cards.draft.md",
)

DESIGN_BRIEF = (
    "一镜一机位。禁止片内切、禁止「立刻切/硬切/转切/cut to」。internal_cuts 必须是空数组。"
    "out_to / in_from 只写本机位开始与结束的状态，不要写下一镜或下一机位。"
    "覆盖派：先 master 交代地理，再正反打，每句对白后给反应。"
    "一句对白只贴一镜，禁止把同一段独白重复贴进多镜。超过十二秒的独白按句号拆到多镜。"
    "Seedance 2.0，每镜 4–15 秒整数。底板无高棉文、无汉字。"
    "波帕：漂浮、下摆盖脚、半透明、微弱暖金光、地上无影、无伤口。禁止固体人、禁止血。"
    "不要写 prompt / image_prompt / motion_prompt。"
)

FRAME_BRIEF = "底板无高棉文、无汉字。波帕盖脚漂浮半透明暖金。一镜一机位，描述里不要写切镜。"


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def snapshot_ep01(prod: Path) -> dict:
    dest = prod / ".pipeline" / "_ep01_lock_copy"
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"copied_at": int(time.time()), "files": {}}
    for rel in EP01_LOCK_FILES:
        src = prod / rel
        if not src.exists():
            continue
        target = dest / rel.replace("/", "__")
        if not target.exists():
            shutil.copy2(src, target)
        manifest["files"][rel] = sha256_file(src)
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def ep01_checksums(prod: Path) -> dict[str, str]:
    return {rel: sha256_file(prod / rel) for rel in EP01_LOCK_FILES}


def assert_ep01_untouched(prod: Path, before: dict[str, str]) -> list[str]:
    """Fail only if we replaced EP01 identity. Parallel cut-language edits on the locked table are allowed."""
    smashed = []
    table = read_artifact(prod, "shot_list.json")
    if int(table.get("episode_no") or 0) != 1:
        smashed.append("shot_list.json episode_no")
    scenes = {str(s.get("scene_id") or "") for s in table.get("shots") or []}
    if scenes and not all(sid.startswith("EP01_") for sid in scenes if sid):
        smashed.append("shot_list.json scene_id prefix")
    if len(table.get("shots") or []) < 20:
        smashed.append("shot_list.json shot count")
    writer = read_artifact(prod, "writer.json")
    wscenes = {str(s.get("scene_id") or "") for s in writer.get("scenes") or []}
    if wscenes and not all(sid.startswith("EP01_") for sid in wscenes if sid):
        smashed.append("writer.json scene_id prefix")
    packages = read_artifact(prod, "gen_packages.json")
    if packages.get("episode_no") not in (None, 1) and int(packages.get("episode_no") or 1) != 1:
        smashed.append("gen_packages.json episode_no")
    return smashed


def list_episode_mds(prod: Path) -> list[int]:
    bible = prod / "01-bible"
    found = []
    for path in sorted(bible.glob("ep*.md")):
        stem = path.stem
        if not stem.startswith("ep") or not stem[2:].isdigit():
            continue
        found.append(int(stem[2:]))
    return found


def canonical_locations(prod: Path) -> list[str]:
    root = prod / "02-assets" / "scenes"
    if not root.exists():
        return []
    return sorted(child.name for child in root.iterdir() if child.is_dir() and (child / "master.jpg").exists())


def remap_writer_locations(writer: dict, allowed: list[str]) -> dict:
    allowed_set = set(allowed)
    for scene in writer.get("scenes") or []:
        loc = str(scene.get("location_id") or "").strip()
        if loc in allowed_set:
            continue
        mapped = LOCATION_ALIASES.get(loc)
        if mapped and mapped in allowed_set:
            path = list(scene.get("location_path") or [])
            if loc and loc not in path:
                path.insert(0, loc)
            scene["location_path"] = path
            scene["location_id"] = mapped
            continue
        for token in loc.replace("_", "-").split("/"):
            token = token.strip()
            mapped = LOCATION_ALIASES.get(token, token)
            if mapped in allowed_set:
                scene["location_id"] = mapped
                break
    return writer


def seed_sets(prod: Path, episode: int, writer: dict) -> Path:
    base = load_json(prod, "03-storyboard/sets.json", {"sets": []})
    by_id = {str(item.get("id")): dict(item) for item in base.get("sets") or [] if item.get("id")}
    names = {
        "factory-gate": "厂门门房",
        "storeroom": "后排杂物间",
        "line-7": "七线车间",
        "locker-room": "更衣室",
        "line-4": "四线车间",
        "ironing": "烫台",
        "breaker-room": "电闸房",
        "canteen-back": "食堂后",
        "pa-room": "广播室",
        "notice-board": "布告栏",
        "management-corridor": "管理廊",
        "factory-office": "厂办",
        "reception": "会客",
        "banquet": "宴席",
        "ceremony-stage": "剪彩台",
        "chairman-temp-office": "董事长临时办",
        "dorm": "宿舍",
        "river-bank": "河岸",
    }
    needed = []
    for scene in writer.get("scenes") or []:
        loc = str(scene.get("location_id") or "").strip()
        if loc and loc not in needed:
            needed.append(loc)
    sets = []
    for loc in needed:
        if loc in by_id:
            sets.append(by_id[loc])
            continue
        master = f"02-assets/scenes/{loc}/master.jpg"
        sets.append(
            {
                "id": loc,
                "name": loc,
                "master": master if (prod / master).exists() else "",
                "axis": "左右锁以本集 shot_list.left_right_lock 为准。",
                "notes": "底板无高棉文、无汉字。波帕若入画：漂浮、盖脚、半透明、暖金光。",
            }
        )
    payload = {
        "episode": f"ep{int(episode):02d}",
        "origin": "prep_episode.py seeded from EP01 sets + writer locations",
        "sets": sets,
    }
    dest = prod / sets_rel(episode)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def writer_brief(prod: Path, episode: int) -> str:
    allowed = ", ".join(canonical_locations(prod))
    aliases = "；".join(f"{k}→{v}" for k, v in LOCATION_ALIASES.items())
    return (
        f"本集是第 {int(episode):02d} 集。只拆 01-bible/ep{int(episode):02d}.md，不要写别集。"
        f"scene_id 必须 EP{int(episode):02d}_SC01 起，episode_no={int(episode)}。"
        "复用 reuse_series_bible 的人物/地点 id，不要另起一套。"
        f"location_id 必须是已有空镜：{allowed}。派生地点用：{aliases}。"
        "每场一个 location_id；走廊/夹道归所在主空镜。"
        "对白逐字从剧本抄。不要写景别、运镜、焦段、机位。"
        "mute_test/unfilmable_check/preach_check 填 pass。"
    )


def status_path(prod: Path) -> Path:
    return prod / "01-bible" / "EPISODES-PREP.md"


def load_status_rows(prod: Path) -> dict[int, dict]:
    path = status_path(prod)
    rows: dict[int, dict] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| EP") or line.startswith("| ep "):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 8 or not parts[0].startswith("EP"):
            continue
        try:
            ep = int(parts[0][2:])
        except ValueError:
            continue
        rows[ep] = {
            "ep": ep,
            "scenes": parts[1],
            "shots": parts[2],
            "seconds": parts[3],
            "packages": parts[4],
            "frame_desc": parts[5],
            "notes": parts[6],
            "blocked": parts[7],
        }
    return rows


def write_status(prod: Path, rows: dict[int, dict], *, resume: str = "") -> None:
    lines = [
        "# 010-gongpai 分集纸面准备",
        "",
        "EP01 已完成（29 镜，Gate C 锁的是 `.pipeline/shot_list.json`）。后面各集用后缀文件，**不重锁 Gate C**，不生成首帧/视频。",
        "",
        "覆盖派 1 候选 + critic skip。`GROK_DESIGN_EFFORT=low`，`GROK_DESIGN_RETRIES=3`。一镜一机位，`internal_cuts=[]`。",
        "",
        "| ep | scenes | shots | seconds | packages | frame_desc | notes | blocked? |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for ep in sorted(rows):
        row = rows[ep]
        lines.append(
            "| {ep} | {scenes} | {shots} | {seconds} | {packages} | {frame_desc} | {notes} | {blocked} |".format(
                ep=f"EP{ep:02d}",
                scenes=row.get("scenes", "—"),
                shots=row.get("shots", "—"),
                seconds=row.get("seconds", "—"),
                packages=row.get("packages", "—"),
                frame_desc=row.get("frame_desc", "—"),
                notes=row.get("notes", "—"),
                blocked=row.get("blocked", "—"),
            )
        )
    lines.extend(
        [
            "",
            "## Resume",
            "",
            resume
            or "python3 scripts/prep_episode.py --prod productions/010-gongpai --from 2 --to 15",
            "",
            "## Gate C",
            "",
            "锁 API 是整剧一份，指纹 EP01 `shot_list.json`。后面各集不要调用 lock C。",
            "",
        ]
    )
    status_path(prod).write_text("\n".join(lines) + "\n", encoding="utf-8")


def episode_counts(prod: Path, episode: int) -> dict:
    table = read_artifact(prod, shot_list_artifact_name(episode))
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    frames = read_artifact(prod, episode_artifact_name("frame_descriptions.json", episode))
    writer = read_artifact(prod, writer_artifact_name(episode))
    shots = list(table.get("shots") or [])
    seconds = sum(int(s.get("duration_sec") or 0) for s in shots)
    return {
        "scenes": len(writer.get("scenes") or []),
        "shots": len(shots),
        "seconds": seconds,
        "packages": len(packages.get("packages") or []),
        "frame_desc": len(frames.get("items") or []),
    }


def write_manifest(prod: Path, episode: int, extra: Optional[dict] = None) -> None:
    path = prod / ".pipeline" / "episodes.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    episodes = data.setdefault("episodes", {})
    episodes[f"{int(episode):02d}"] = {
        "writer": writer_artifact_name(episode),
        "shot_list": shot_list_artifact_name(episode),
        "shot_specs": episode_artifact_name("shot_specs.json", episode),
        "scene_cards": episode_artifact_name("scene_cards.json", episode),
        "frame_descriptions": episode_artifact_name("frame_descriptions.json", episode),
        "gen_packages": episode_artifact_name("gen_packages.json", episode),
        "gen_packages_2_5": (
            "gen_packages.seedance_2_5.json"
            if int(episode) == 1
            else f"gen_packages.seedance_2_5.ep{int(episode):02d}.json"
        ),
        "sets": sets_rel(episode),
        "shot_list_md": storyboard_md_name("shot-list.md", episode) if episode == 1 else f"03-storyboard/shot-list.ep{int(episode):02d}.md",
        "updated_at": int(time.time()),
        **(extra or {}),
    }
    data["updated_at"] = int(time.time())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_storyboard_table(prod: Path, episode: int) -> None:
    table = read_artifact(prod, shot_list_artifact_name(episode))
    if not table.get("shots"):
        return
    dest = prod / "03-storyboard" / (f"shot_list.ep{int(episode):02d}.json" if int(episode) != 1 else "shot_list.json")
    dest.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prep_one(prod: Path, episode: int, *, resume: bool = True) -> dict:
    if int(episode) == 1:
        raise SystemExit("EP01 is already locked; this script is for remaining episodes")
    if not (prod / "01-bible" / f"ep{int(episode):02d}.md").exists():
        raise SystemExit(f"missing 01-bible/ep{int(episode):02d}.md")
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "Grok 不可用")

    before = ep01_checksums(prod)
    notes = []
    writer_name = writer_artifact_name(episode)
    existing_writer = read_artifact(prod, writer_name)
    if existing_writer.get("scenes") and resume:
        writer = existing_writer
        notes.append("writer cache")
        print(f"EP{int(episode):02d} writer cache {len(writer.get('scenes') or [])} scenes", flush=True)
    else:
        print(f"EP{int(episode):02d} writer…", flush=True)
        result = run_station_agent(
            prod,
            "writer",
            brief=writer_brief(prod, episode),
            episode=episode,
        )
        writer = result["artifact"]
    remapped = remap_writer_locations(json.loads(json.dumps(writer)), canonical_locations(prod))
    fitted = fit_writer_dialogue(json.loads(json.dumps(remapped)))
    if fitted != writer:
        writer = fitted
        write_artifact(prod, writer_name, writer)
        notes.append("writer dialogue fitted")
    seed_sets(prod, episode, writer)

    design_name = shot_list_artifact_name(episode)
    existing_table = read_artifact(prod, design_name)
    if existing_table.get("shots") and resume:
        notes.append("design cache")
        design = {"artifact": existing_table, "ok": True}
        print(f"EP{int(episode):02d} design cache {len(existing_table.get('shots') or [])} shots", flush=True)
    else:
        print(f"EP{int(episode):02d} design…", flush=True)
        design = run_station_agent(
            prod,
            "design",
            brief=DESIGN_BRIEF,
            target_model="seedance_2_0",
            resume=resume,
            candidates=1,
            episode=episode,
        )
    copy_storyboard_table(prod, episode)

    frame_name = episode_artifact_name("frame_descriptions.json", episode)
    existing_frames = read_artifact(prod, frame_name)
    table = read_artifact(prod, design_name)
    shot_ids = [str(s.get("shot_id") or "") for s in table.get("shots") or []]
    have = {str(i.get("shot_id") or "") for i in (existing_frames.get("items") or [])}
    if shot_ids and have.issuperset(shot_ids) and resume:
        notes.append("frame_desc cache")
        frames = {"ok": True, "artifact": existing_frames}
        print(f"EP{int(episode):02d} frame_desc cache {len(have)} items", flush=True)
    else:
        print(f"EP{int(episode):02d} frame_desc…", flush=True)
        frames = run_station_agent(
            prod,
            "frame_desc",
            brief=FRAME_BRIEF,
            episode=episode,
        )

    print(f"EP{int(episode):02d} packages…", flush=True)
    compiled = compile_episode(prod, episode, confirm=True, write=True)
    if not compiled.get("ok"):
        raise PermissionError("package: " + " / ".join((compiled.get("errors") or [])[:6]))

    smashed = assert_ep01_untouched(prod, before)
    if smashed:
        raise PermissionError("EP01 lock files changed: " + ", ".join(smashed))

    counts = episode_counts(prod, episode)
    write_manifest(prod, episode, extra={"counts": counts, "notes": notes})
    return {
        "ok": True,
        "episode": episode,
        "counts": counts,
        "notes": notes,
        "backend": text_backend(),
        "design": design.get("scene_reports") or [],
        "frame_desc": frames.get("scene_reports") or [],
        "packages": compiled.get("package_count"),
        "wrote": compiled.get("wrote"),
    }


def format_status_line(episode: int, result: dict) -> str:
    counts = result.get("counts") or {}
    return (
        f"STATUS EP{int(episode):02d} scenes={counts.get('scenes', '?')} "
        f"shots={counts.get('shots', '?')} sec={counts.get('seconds', '?')} "
        f"packages={counts.get('packages', '?')} frame_desc={counts.get('frame_desc', '?')} "
        f"ok={result.get('ok')} {'; '.join(result.get('notes') or [])}"
    )


def run_range(prod: Path, start: int, end: int, *, resume: bool = True) -> list[dict]:
    os.environ.setdefault("GROK_DESIGN_EFFORT", "low")
    os.environ.setdefault("GROK_DESIGN_RETRIES", "3")
    os.environ.setdefault("GROK_DESIGN_CANDIDATES", "1")
    snapshot_ep01(prod)
    rows = load_status_rows(prod)
    if 1 not in rows:
        rows[1] = {
            "scenes": "3",
            "shots": "29",
            "seconds": "—",
            "packages": "29",
            "frame_desc": "29",
            "notes": "already locked; Gate C fingerprints this table",
            "blocked": "no",
        }
    results = []
    remaining = [ep for ep in range(start, end + 1) if ep != 1]
    for episode in remaining:
        rows[episode] = {
            "scenes": "…",
            "shots": "…",
            "seconds": "…",
            "packages": "…",
            "frame_desc": "…",
            "notes": "running",
            "blocked": "—",
        }
        write_status(
            prod,
            rows,
            resume=f"python3 scripts/prep_episode.py --prod productions/010-gongpai --from {episode} --to {end}",
        )
        try:
            result = prep_one(prod, episode, resume=resume)
        except Exception as exc:
            print(f"STATUS EP{episode:02d} FAIL {exc}", flush=True)
            try:
                result = prep_one(prod, episode, resume=True)
            except Exception as retry_exc:
                print(f"STATUS EP{episode:02d} MISS {retry_exc}", flush=True)
                rows[episode] = {
                    "scenes": "—",
                    "shots": "—",
                    "seconds": "—",
                    "packages": "—",
                    "frame_desc": "—",
                    "notes": str(retry_exc)[:180],
                    "blocked": "yes",
                }
                write_status(
                    prod,
                    rows,
                    resume=f"python3 scripts/prep_episode.py --prod productions/010-gongpai --from {episode} --to {end}",
                )
                results.append({"ok": False, "episode": episode, "error": str(retry_exc)})
                continue
        counts = result["counts"]
        rows[episode] = {
            "scenes": str(counts["scenes"]),
            "shots": str(counts["shots"]),
            "seconds": str(counts["seconds"]),
            "packages": str(counts["packages"]),
            "frame_desc": str(counts["frame_desc"]),
            "notes": "; ".join(result.get("notes") or []) or "coverage ×1",
            "blocked": "no",
        }
        nxt = episode + 1 if episode < end else end
        write_status(
            prod,
            rows,
            resume=f"python3 scripts/prep_episode.py --prod productions/010-gongpai --from {nxt} --to {end}",
        )
        print(format_status_line(episode, result), flush=True)
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", type=int)
    parser.add_argument("--from", dest="start", type=int, default=2)
    parser.add_argument("--to", dest="end", type=int)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    prod = Path(args.prod)
    if not prod.is_absolute():
        prod = (ROOT / prod).resolve()
    episodes = list_episode_mds(prod)
    if args.inventory:
        print(json.dumps({"prod": str(prod), "episodes": episodes, "backend": text_backend()}, ensure_ascii=False, indent=2))
        return 0
    if args.episode:
        start = end = int(args.episode)
    else:
        start = int(args.start)
        end = int(args.end or max(episodes or [start]))
    print(
        json.dumps(
            {
                "prod": str(prod),
                "range": [start, end],
                "scripts": [f"ep{n:02d}.md" for n in episodes],
                "backend": text_backend(),
                "effort": os.environ.get("GROK_DESIGN_EFFORT", "low"),
                "candidates": os.environ.get("GROK_DESIGN_CANDIDATES", "1"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    results = run_range(prod, start, end, resume=not args.no_resume)
    failed = [r for r in results if not r.get("ok")]
    print(json.dumps({"ok": not failed, "done": len(results) - len(failed), "failed": [r.get("episode") for r in failed]}, ensure_ascii=False), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
