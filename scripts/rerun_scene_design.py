#!/usr/bin/env python3
"""Selective 3-candidate + critic re-design for listed scenes. Paper only.

Reuses existing scene cards / header. Replaces only the target scene in the
suffixed episode shot_list, then rebuilds frame_desc + Seedance packages.
Never writes EP01 unsuffixed artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
os.environ["GROK_DESIGN_CANDIDATES"] = "3"
os.environ.setdefault("GROK_DESIGN_EFFORT", "medium")
os.environ.setdefault("GROK_DESIGN_RETRIES", "3")

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import compile_episode  # noqa: E402
from director.design_critic import styles_for  # noqa: E402
from director.direction import scene_card_for  # noqa: E402
from director.frame_desc import index_by_shot as frame_desc_index  # noqa: E402
from director.grok_text import TextError, text_backend, text_configured  # noqa: E402
from director.pipeline import (  # noqa: E402
    episode_artifact_name,
    pipeline_dir,
    read_artifact,
    write_artifact,
)
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from concurrent.futures import TimeoutError as FuturesTimeout  # noqa: E402

from director.shot_table import table_context, validate_shot_table  # noqa: E402
from director import station_agents as station_agents_mod  # noqa: E402
from director.station_agents import (  # noqa: E402
    _candidate_context,
    _design_base_context,
    _design_one_candidate,
    _finalize_design,
    _renumber,
    _run_critic,
    _system,
    candidates_name,
    design_cache_name,
    frame_desc_artifact_name,
    run_frame_descriptions,
    scene_cards_artifact_name,
    set_active_episode,
    shot_list_artifact_name,
    writer_artifact_name,
)

_WALL = int(os.environ.get("GROK_DESIGN_WALL_TIMEOUT", "1800") or 1800)
_ORIG_DESIGN_CHAT = station_agents_mod._design_chat


def _design_chat_walled(system, ctx, temperature=0.3):
    started = time.time()
    call = str((ctx or {}).get("call") or "design")
    style = str(((ctx or {}).get("candidate_style") or {}).get("id") or "")
    print(f"  grok {call} {style} wall={_WALL}s…", flush=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_ORIG_DESIGN_CHAT, system, ctx, temperature)
        try:
            data = future.result(timeout=_WALL)
        except FuturesTimeout as exc:
            raise TextError("GROK_HTTP", f"design wall timeout {_WALL}s ({call} {style})") from exc
    print(f"  grok {call} {style} ok {int(time.time() - started)}s", flush=True)
    return data


station_agents_mod._design_chat = _design_chat_walled

DESIGN_BRIEF = (
    "一镜一机位。禁止片内切、禁止「立刻切/硬切/转切/cut to」。internal_cuts 必须是空数组。"
    "out_to / in_from 只写本机位开始与结束的状态，不要写下一镜或下一机位。"
    "一句对白只贴一镜，禁止把同一段独白重复贴进多镜。超过十二秒的独白按句号拆到多镜。"
    "按 candidate_style 拆这一场，三版不要写成同一种覆盖派。"
    "Seedance 2.0，每镜 4–15 秒整数。底板无高棉文、无汉字。"
    "波帕：漂浮、下摆盖脚、半透明、微弱暖金光、地上无影、无伤口。禁止固体人、禁止血。"
    "不要写 prompt / image_prompt / motion_prompt。"
)
FRAME_BRIEF = "底板无高棉文、无汉字。波帕盖脚漂浮半透明暖金。一镜一机位，描述里不要写切镜。"

DEFAULT_SCENES = [
    "EP03_SC01",
    "EP05_SC04",
    "EP06_SC04",
    "EP09_SC01",
    "EP09_SC03",
    "EP10_SC01",
    "EP10_SC02",
    "EP11_SC02",
    "EP13_SC03",
    "EP14_SC03",
]
EP01_LOCK = (
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


def load_dotenv(root: Path) -> None:
    path = root / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def ep01_checksums(prod: Path) -> dict[str, str]:
    return {rel: sha256_file(prod / rel) for rel in EP01_LOCK}


def assert_ep01_untouched(prod: Path, before: dict[str, str] | None = None) -> None:
    """Fail only if EP01 identity was replaced. Parallel edits on the locked EP01 table are allowed."""
    table = read_artifact(prod, "shot_list.json")
    smashed = []
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
    if smashed:
        raise PermissionError("EP01 identity smashed: " + ", ".join(smashed))


def parse_scene_id(scene_id: str) -> int:
    if not scene_id.startswith("EP") or "_SC" not in scene_id:
        raise ValueError("bad scene_id " + scene_id)
    ep = int(scene_id[2:4])
    if ep == 1:
        raise PermissionError("refusing to touch EP01")
    return ep


def shots_by_scene(shots: list[dict]) -> tuple[list[str], dict[str, list[dict]]]:
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for shot in shots:
        sid = str(shot.get("scene_id") or "")
        if not sid:
            continue
        if sid not in grouped:
            order.append(sid)
            grouped[sid] = []
        grouped[sid].append(dict(shot))
    return order, grouped


def scene_stats(shots: list[dict]) -> dict[str, int]:
    return {"shots": len(shots), "seconds": sum(int(s.get("duration_sec") or 0) for s in shots)}


def load_candidate_dump(prod: Path, episode: int) -> dict:
    folder = pipeline_dir(prod)
    for name in (candidates_name(episode), f"design.ep{int(episode):02d}.candidates.json"):
        path = folder / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return {"schema": "design-candidates-v1", "scenes": [], "picks": {}}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report_path(prod: Path) -> Path:
    return pipeline_dir(prod, create=True) / "selective-rerun-report.json"


def load_report(prod: Path) -> dict:
    path = report_path(prod)
    if not path.exists():
        return {"schema": "selective-rerun-v1", "scenes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "selective-rerun-v1", "scenes": {}}
    data.setdefault("scenes", {})
    return data


def save_report(prod: Path, report: dict) -> None:
    report["updated_at"] = int(time.time())
    write_json(report_path(prod), report)


def remap_frame_desc(prod: Path, episode: int, old_ids: dict[str, list[str]], new_table: dict, changed: str) -> int:
    existing = frame_desc_index(read_artifact(prod, frame_desc_artifact_name(episode)))
    order, grouped = shots_by_scene(list(new_table.get("shots") or []))
    remapped: dict[str, dict] = {}
    kept = 0
    for sid in order:
        new_ids = [str(s.get("shot_id") or "") for s in grouped.get(sid) or []]
        if sid == changed:
            continue
        prev = old_ids.get(sid) or []
        if len(prev) != len(new_ids):
            continue
        for old_id, new_id in zip(prev, new_ids):
            item = existing.get(old_id)
            if not item:
                continue
            copy = dict(item)
            copy["shot_id"] = new_id
            remapped[new_id] = copy
            kept += 1
    items = [remapped[str(s.get("shot_id") or "")] for s in (new_table.get("shots") or []) if str(s.get("shot_id") or "") in remapped]
    payload = read_artifact(prod, frame_desc_artifact_name(episode)) or {"schema": "frame-desc-v1"}
    payload["schema"] = payload.get("schema") or "frame-desc-v1"
    payload["items"] = items
    write_artifact(prod, frame_desc_artifact_name(episode), payload)
    return kept


def patch_prep_notes(prod: Path, episode: int, note: str, counts: dict) -> None:
    path = prod / "01-bible" / "EPISODES-PREP.md"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    key = f"| EP{int(episode):02d} |"
    out = []
    for line in lines:
        if not line.startswith(key):
            out.append(line)
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 8:
            out.append(line)
            continue
        parts[2] = str(counts.get("shots", parts[2]))
        parts[3] = str(counts.get("seconds", parts[3]))
        parts[4] = str(counts.get("packages", parts[4]))
        parts[5] = str(counts.get("frame_desc", parts[5]))
        old_note = parts[6]
        if note and note not in old_note:
            parts[6] = (old_note + "; " if old_note and old_note not in {"—", ""} else "") + note
        out.append("| " + " | ".join(parts) + " |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def update_manifest(prod: Path, episode: int, counts: dict, notes: list[str]) -> None:
    path = prod / ".pipeline" / "episodes.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    episodes = data.setdefault("episodes", {})
    row = dict(episodes.get(f"{int(episode):02d}") or {})
    row.update(
        {
            "writer": writer_artifact_name(episode),
            "shot_list": shot_list_artifact_name(episode),
            "shot_specs": episode_artifact_name("shot_specs.json", episode),
            "scene_cards": episode_artifact_name("scene_cards.json", episode),
            "frame_descriptions": episode_artifact_name("frame_descriptions.json", episode),
            "gen_packages": episode_artifact_name("gen_packages.json", episode),
            "gen_packages_2_5": f"gen_packages.seedance_2_5.ep{int(episode):02d}.json",
            "sets": f"03-storyboard/sets.ep{int(episode):02d}.json",
            "shot_list_md": f"03-storyboard/shot-list.ep{int(episode):02d}.md",
            "updated_at": int(time.time()),
            "counts": counts,
            "notes": notes,
        }
    )
    episodes[f"{int(episode):02d}"] = row
    data["updated_at"] = int(time.time())
    write_json(path, data)


def copy_storyboard(prod: Path, episode: int) -> None:
    table = read_artifact(prod, shot_list_artifact_name(episode))
    if not table.get("shots"):
        return
    dest = prod / "03-storyboard" / f"shot_list.ep{int(episode):02d}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def episode_counts(prod: Path, episode: int) -> dict:
    table = read_artifact(prod, shot_list_artifact_name(episode))
    packages = read_artifact(prod, episode_artifact_name("gen_packages.json", episode))
    frames = read_artifact(prod, frame_desc_artifact_name(episode))
    writer = read_artifact(prod, writer_artifact_name(episode))
    shots = list(table.get("shots") or [])
    return {
        "scenes": len(writer.get("scenes") or []),
        "shots": len(shots),
        "seconds": sum(int(s.get("duration_sec") or 0) for s in shots),
        "packages": len(packages.get("packages") or []),
        "frame_desc": len(frames.get("items") or []),
    }


def design_one_scene(prod: Path, scene_id: str) -> dict:
    ep = parse_scene_id(scene_id)
    if not text_configured():
        raise TextError("NEED_GROK_LOGIN", "Grok 不可用")
    prev = set_active_episode(ep)
    try:
        return _design_one_scene_body(prod, scene_id, ep)
    finally:
        set_active_episode(prev)


def _design_one_scene_body(prod: Path, scene_id: str, ep: int) -> dict:
    table = read_artifact(prod, shot_list_artifact_name(ep))
    cards_art = read_artifact(prod, scene_cards_artifact_name(ep))
    scene_cards = cards_art.get("scene_cards") or table.get("scene_cards") or []
    grammar = cards_art.get("visual_grammar") or table.get("visual_grammar") or {}
    card = scene_card_for(scene_cards, scene_id)
    if not card:
        raise PermissionError(f"{scene_id}: scene card missing")
    writer = read_artifact(prod, writer_artifact_name(ep))
    writer_ids = [str(s.get("scene_id") or "") for s in (writer.get("scenes") or [])]
    if scene_id not in writer_ids:
        raise PermissionError(f"{scene_id}: not in writer.ep{ep:02d}.json")

    order, grouped = shots_by_scene(list(table.get("shots") or []))
    if scene_id not in grouped:
        raise PermissionError(f"{scene_id}: not in official shot_list")
    before_stats = scene_stats(grouped[scene_id])
    old_ids = {sid: [str(s.get("shot_id") or "") for s in shots] for sid, shots in grouped.items()}

    before: list[dict] = []
    after: list[dict] = []
    seen = False
    for sid in order:
        if sid == scene_id:
            seen = True
            continue
        if not seen:
            before.extend(grouped[sid])
        else:
            after.extend(grouped[sid])

    header = {
        "whose_pov": table.get("whose_pov"),
        "left_right_lock": table.get("left_right_lock"),
        "continuity_bible": table.get("continuity_bible"),
        "scene_plan": table.get("scene_plan"),
        "dropped_shots": table.get("dropped_shots") or [],
    }
    base = _design_base_context(prod, "seedance_2_0")
    scene = next((s for s in (base.get("writer") or {}).get("scenes") or [] if str(s.get("scene_id") or "") == scene_id), None)
    if scene is None:
        raise PermissionError(f"{scene_id}: missing from design writer context")
    check = table_context(prod, "seedance_2_0", episode=ep)
    profile = check["profile"]
    system = _system("design")
    table_extra = {"scene_cards": scene_cards, "visual_grammar": grammar}
    styles = styles_for(3)
    shot_id_start = f"SH{len(before) + 1:03d}"
    prev_shot = before[-1] if before else None

    cache_path = pipeline_dir(prod, create=True) / design_cache_name(ep)
    write_json(
        cache_path,
        {
            "key": f"selective-{scene_id}",
            "forced": scene_id,
            "header": header,
            "analysis": {"schema": cards_art.get("schema") or "scene-cards-v1", "scene_cards": scene_cards, "visual_grammar": grammar},
            "scenes": {sid: grouped[sid] for sid in order if sid != scene_id},
        },
    )

    accepted: list[dict] = []
    style_status = []
    for style in styles:
        print(f"{scene_id} design {style['id']}…", flush=True)
        ctx = _candidate_context(base, header, scene, card, grammar, shot_id_start, prev_shot, style, DESIGN_BRIEF)
        result = _design_one_candidate(
            prod,
            system,
            ctx,
            sid=scene_id,
            merged_shots=before,
            header=header,
            check=check,
            profile=profile,
            style=style,
            table_extra=table_extra,
        )
        style_status.append({"style": style["id"], "label": style["label"], "passed": bool(result)})
        if result:
            accepted.append(result)
            print(f"{scene_id} {style['id']} PASS shots={len(result.get('shots') or [])}", flush=True)
        else:
            print(f"{scene_id} {style['id']} FAIL validation", flush=True)

    if not accepted:
        if cache_path.exists():
            cache_path.unlink()
        raise PermissionError(f"{scene_id}: 3 版都没过机器校验")

    verdict = _run_critic(prod, sid=scene_id, scene=scene, card=card, grammar=grammar, candidates=accepted, profile=profile)
    pick = int(verdict.get("pick", 0) or 0)
    if pick < 0 or pick >= len(accepted):
        pick = 0
        verdict = dict(verdict)
        verdict["pick"] = 0
    chosen = list(accepted[pick].get("shots") or [])
    print(
        f"{scene_id} critic source={verdict.get('source')} pick={pick} "
        f"style={accepted[pick].get('style')} shots={len(chosen)} passed={len(accepted)}/3",
        flush=True,
    )

    merged: list[dict] = []
    for sid in order:
        chunk = chosen if sid == scene_id else grouped[sid]
        merged.extend(_renumber(list(chunk), len(merged) + 1))

    dump = load_candidate_dump(prod, ep)
    new_row = {"scene_id": scene_id, "scene_card": card, "candidates": accepted, "verdict": verdict, "pick": pick}
    rows = []
    replaced = False
    for row in dump.get("scenes") or []:
        if str(row.get("scene_id") or "") == scene_id:
            rows.append(new_row)
            replaced = True
        else:
            rows.append(row)
    if not replaced:
        inserted = False
        rebuilt = []
        for sid in order:
            if sid == scene_id:
                rebuilt.append(new_row)
                inserted = True
            else:
                existing = next((r for r in rows if str(r.get("scene_id") or "") == sid), None)
                if existing:
                    rebuilt.append(existing)
        if not inserted:
            rebuilt.append(new_row)
        rows = rebuilt

    picks = {str(k): int(v) for k, v in (table.get("candidate_picks") or dump.get("picks") or {}).items()}
    picks[scene_id] = pick
    reports = []
    for item in table.get("scene_reports") or []:
        if str(item.get("scene_id") or "") == scene_id:
            continue
        reports.append(item)
    reports.append(
        {
            "scene_id": scene_id,
            "shots": len(chosen),
            "warnings": accepted[pick].get("warnings") or [],
            "attempts": accepted[pick].get("attempts"),
            "candidates": len(accepted),
            "pick": pick,
            "critic": verdict.get("source"),
        }
    )

    written = _finalize_design(
        prod,
        merged_shots=merged,
        header=header,
        check=check,
        profile=profile,
        scene_cards=scene_cards,
        grammar=grammar,
        picks=picks,
        candidate_rows=rows,
        scene_reports=reports,
    )
    write_artifact(prod, candidates_name(ep), {"schema": "design-candidates-v1", "scenes": rows, "picks": picks})
    if cache_path.exists():
        cache_path.unlink()
    copy_storyboard(prod, ep)

    errors, _warnings = validate_shot_table(
        written,
        writer=check["writer"],
        sets=check["sets"],
        profile=profile,
        look_text=check["look_text"],
    )
    if errors:
        raise PermissionError("validate after merge: " + " / ".join(errors[:8]))

    after_group = [s for s in (written.get("shots") or []) if str(s.get("scene_id") or "") == scene_id]
    after_stats = scene_stats(after_group)

    kept = remap_frame_desc(prod, ep, old_ids, written, scene_id)
    print(f"{scene_id} frame_desc remap kept={kept}…", flush=True)
    frames = run_frame_descriptions(prod, brief=FRAME_BRIEF, scene_ids=[scene_id], episode=ep)
    print(f"{scene_id} packages…", flush=True)
    compiled = compile_episode(prod, ep, confirm=True, write=True)
    if not compiled.get("ok"):
        raise PermissionError("package: " + " / ".join((compiled.get("errors") or [])[:6]))

    counts = episode_counts(prod, ep)
    note = (
        f"{scene_id} candidates=3 passed={len(accepted)} "
        f"source={verdict.get('source')} pick={accepted[pick].get('style')}"
    )
    existing_notes = list((json.loads((prod / ".pipeline" / "episodes.json").read_text(encoding="utf-8"))
                           .get("episodes", {}).get(f"{ep:02d}", {}).get("notes") or []))
    merged_notes = [n for n in existing_notes if scene_id not in str(n)]
    merged_notes.append(note)
    update_manifest(prod, ep, counts, merged_notes)
    patch_prep_notes(prod, ep, note, counts)
    return {
        "ok": True,
        "scene_id": scene_id,
        "episode": ep,
        "styles": style_status,
        "passed": len(accepted),
        "pick": pick,
        "pick_style": accepted[pick].get("style"),
        "critic": {
            "source": verdict.get("source"),
            "why": verdict.get("why"),
            "scores": verdict.get("scores") or [],
        },
        "before": before_stats,
        "after": after_stats,
        "episode_counts": counts,
        "frame_desc": True,
        "packages": True,
        "packages_2_5": bool((compiled.get("wrote") or {}).get("gen_packages_2_5")),
        "backend": text_backend(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", default="productions/010-gongpai")
    parser.add_argument("--scenes", nargs="*", default=DEFAULT_SCENES)
    parser.add_argument("--only", action="append")
    args = parser.parse_args()
    load_dotenv(ROOT)
    prod = Path(args.prod)
    if not prod.is_absolute():
        prod = (ROOT / prod).resolve()
    scenes = list(args.only or args.scenes)
    if not text_configured():
        print(json.dumps({"ok": False, "error": "NEED_GROK_LOGIN", "backend": text_backend()}, ensure_ascii=False))
        return 2
    report = load_report(prod)
    print(
        json.dumps(
            {
                "prod": str(prod),
                "backend": text_backend(),
                "effort": os.environ.get("GROK_DESIGN_EFFORT"),
                "candidates": os.environ.get("GROK_DESIGN_CANDIDATES"),
                "retries": os.environ.get("GROK_DESIGN_RETRIES"),
                "scenes": scenes,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    failed = []
    for scene_id in scenes:
        if int(scene_id[2:4]) == 1:
            raise PermissionError("refusing EP01")
        prior = (report.get("scenes") or {}).get(scene_id) or {}
        if prior.get("ok"):
            print(f"{scene_id} already ok, skip", flush=True)
            continue
        started = int(time.time())
        try:
            result = design_one_scene(prod, scene_id)
            result["elapsed_sec"] = int(time.time()) - started
            report.setdefault("scenes", {})[scene_id] = result
            save_report(prod, report)
            assert_ep01_untouched(prod)
            print(json.dumps({"STATUS": scene_id, **{k: result[k] for k in ("ok", "passed", "pick_style", "before", "after", "critic") if k in result}}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f"STATUS {scene_id} FAIL {exc}", flush=True)
            prior_ok = ((report.get("scenes") or {}).get(scene_id) or {}).get("ok")
            if not prior_ok:
                report.setdefault("scenes", {})[scene_id] = {
                    "ok": False,
                    "scene_id": scene_id,
                    "error": str(exc)[:400],
                    "elapsed_sec": int(time.time()) - started,
                }
                save_report(prod, report)
            failed.append(scene_id)
            try:
                assert_ep01_untouched(prod)
            except PermissionError:
                print("EP01 TOUCHED — stop", flush=True)
                return 3
            continue
    print(json.dumps({"ok": not failed, "failed": failed, "report": str(report_path(prod))}, ensure_ascii=False), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
