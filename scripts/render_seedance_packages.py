#!/usr/bin/env python3
"""6.2 for pipeline productions: gen_packages + locked keyframes -> Seedance clips.

Does not read or write 03-storyboard/shots.json. Designed 04-frames/*-last.jpg
stills are never overwritten with an extracted last frame.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import load_dotenv, productions_root, safe_under
from director.pipeline import (
    assert_keyframes_passed,
    assert_packages_confirmed,
    duration_for_shot,
    packages_confirmed,
    read_artifact,
    uses_pipeline,
    validate_packages,
)
from video_backends.seedance_ark import SeedanceArk

SEEDANCE_MODE = {
    "i2v_first": "i2v",
    "flf2v": "flf",
    "video_extend": "i2v",
}
FACE_TYPES = {"character", "costume_state"}
MAX_REFS = 4


def _prod(path: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raw = (ROOT / raw).resolve()
    return raw


def _text(value) -> str:
    return str(value or "").strip()


def _packages(prod: Path) -> list[dict]:
    data = read_artifact(prod, "gen_packages.json")
    return list(data.get("packages") or data.get("gen_packages") or [])


def _keyframes(prod: Path) -> dict[str, dict]:
    data = read_artifact(prod, "keyframes.json")
    return {item.get("shot_id"): item for item in (data.get("keyframes") or []) if item.get("shot_id")}


def _assets(prod: Path) -> dict[str, dict]:
    data = read_artifact(prod, "assets.json")
    return {item.get("asset_id"): item for item in (data.get("assets") or []) if item.get("asset_id")}


def _shot_ids(table: dict) -> list[str]:
    return [_text(item.get("shot_id")) for item in (table.get("shots") or []) if _text(item.get("shot_id"))]


def _hardest(table: dict) -> list[str]:
    return [_text(item.get("shot_id")) for item in (table.get("shots") or []) if item.get("hardest")]


def identity_ref_paths(prod: Path, pkg: dict, assets: dict[str, dict], first: Path) -> list[Path]:
    refs: list[Path] = []
    seen: set[Path] = set()
    first_resolved = first.resolve()
    for asset_id in pkg.get("asset_refs") or []:
        item = assets.get(asset_id) or {}
        if item.get("type") not in FACE_TYPES:
            continue
        rel = _text(item.get("file"))
        if not rel:
            continue
        path = safe_under(prod, rel)
        if not path.exists() or path.resolve() == first_resolved:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        refs.append(path)
        if len(refs) >= MAX_REFS:
            break
    return refs


def seedance_mode(gen_mode: str) -> str:
    mode = SEEDANCE_MODE.get(_text(gen_mode))
    if not mode:
        raise SystemExit(f"不支持的 gen_mode: {gen_mode}")
    return mode


def plan_shot(prod: Path, pkg: dict, frames: dict[str, dict], assets: dict[str, dict]) -> dict:
    sid = _text(pkg.get("shot_id"))
    kf = frames.get(sid) or {}
    qc = kf.get("qc") or {}
    first_rel = _text(kf.get("first_frame_file")) or f"04-frames/{sid}.jpg"
    last_rel = _text(kf.get("last_frame_file"))
    gen_mode = _text(pkg.get("gen_mode"))
    plan = _text(pkg.get("keyframe_plan"))
    first = safe_under(prod, first_rel)
    last = safe_under(prod, last_rel) if last_rel else None
    dest_rel = f"05-shots/{sid}.mp4"
    extracted_rel = f"05-shots/{sid}-last.jpg"
    errors: list[str] = []
    if not pkg.get("confirmed"):
        errors.append("package not confirmed")
    if _text(qc.get("status")) != "pass":
        errors.append("keyframe not passed")
    if not first.exists():
        errors.append(f"missing first frame {first_rel}")
    if gen_mode == "flf2v" or plan == "first_last":
        if not last_rel:
            errors.append("flf2v / first_last missing last_frame_file")
        elif last is None or not last.exists():
            errors.append(f"missing last frame {last_rel}")
    prompt = _text(pkg.get("motion_prompt"))
    if not prompt:
        errors.append("missing motion_prompt")
    seconds = int(round(duration_for_shot(prod, sid, float(pkg.get("duration_sec") or 4))))
    refs = identity_ref_paths(prod, pkg, assets, first) if first.exists() else []
    return {
        "shot_id": sid,
        "gen_mode": gen_mode,
        "seedance_mode": seedance_mode(gen_mode),
        "keyframe_plan": plan,
        "prompt": prompt,
        "duration_sec": seconds,
        "first_frame": first_rel,
        "last_frame": last_rel,
        "use_last_frame": bool(gen_mode == "flf2v" and last_rel),
        "refs": [str(path.relative_to(prod)) for path in refs],
        "dest": dest_rel,
        "extracted_last": extracted_rel,
        "overwrite_designed_last": False,
        "hardest": False,
        "errors": errors,
        "ok": not errors,
        "exists": (prod / dest_rel).exists() and (prod / dest_rel).stat().st_size > 1024,
    }


def build_plan(prod: Path, only: Optional[list[str]] = None) -> dict:
    if not uses_pipeline(prod):
        raise SystemExit("这个项目不是 pipeline 岗，不要走 render_seedance_packages.py")
    packages = _packages(prod)
    frames = _keyframes(prod)
    assets = _assets(prod)
    table = read_artifact(prod, "shot_list.json")
    pkg_errors = validate_packages(read_artifact(prod, "gen_packages.json"), read_artifact(prod, "assets.json"), read_artifact(prod, "shot_specs.json"))
    if pkg_errors:
        raise SystemExit("生成包未过校验：" + pkg_errors[0])
    if not packages_confirmed(read_artifact(prod, "gen_packages.json")):
        raise SystemExit("生成包还没 confirmed=true")
    assert_packages_confirmed(prod)
    assert_keyframes_passed(prod)
    order = _shot_ids(table) or [_text(item.get("shot_id")) for item in packages]
    by_id = {_text(item.get("shot_id")): item for item in packages}
    want = set(only or [])
    hardest = set(_hardest(table))
    shots = []
    for sid in order:
        if want and sid not in want:
            continue
        pkg = by_id.get(sid)
        if not pkg:
            shots.append({"shot_id": sid, "ok": False, "errors": ["missing gen_package"]})
            continue
        item = plan_shot(prod, pkg, frames, assets)
        item["hardest"] = sid in hardest
        shots.append(item)
    missing = sorted(want - {item["shot_id"] for item in shots}) if want else []
    if missing:
        raise SystemExit("没有这些镜头：" + ", ".join(missing))
    return {
        "prod": str(prod.relative_to(ROOT)) if ROOT in prod.parents or prod == ROOT else str(prod),
        "shots": shots,
        "count": len(shots),
        "ok_count": sum(1 for item in shots if item.get("ok")),
        "hardest": [item["shot_id"] for item in shots if item.get("hardest")],
        "writes_shots_json": False,
        "overwrites_designed_last": False,
    }


def _extract_last(video: Path, dest: Path) -> None:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["ffmpeg", "-y", "-sseof", "-0.05", "-i", str(video), "-frames:v", "1", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def render_plan(prod: Path, plan: dict, *, skip_existing: bool = True) -> None:
    load_dotenv()
    backend = SeedanceArk()
    out_dir = prod / "05-shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in plan["shots"]:
        sid = item["shot_id"]
        if not item.get("ok"):
            raise SystemExit(f"{sid} 还不能出片：" + "; ".join(item.get("errors") or []))
        dest = prod / item["dest"]
        if skip_existing and item.get("exists"):
            print(f"  {sid} already has {item['dest']}, skip")
            continue
        image = safe_under(prod, item["first_frame"])
        last = safe_under(prod, item["last_frame"]) if item.get("use_last_frame") and item.get("last_frame") else None
        # Character portraits are listed on the plan for humans. Seedance 2.0
        # treats simulated faces as real-person privacy, so do not upload them.
        refs: list = []
        backend.render(
            image,
            item["prompt"],
            int(item["duration_sec"]),
            dest,
            refs=refs,
            mode=item["seedance_mode"],
            last_frame=last,
            force=not skip_existing,
        )
        extracted = prod / item["extracted_last"]
        _extract_last(dest, extracted)
        print(f"  extracted last {extracted.relative_to(prod)} (designed still untouched)")


def write_manifest(prod: Path, plan: dict) -> Path:
    dest = prod / ".pipeline" / "seedance_render_plan.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = dict(plan)
    body["status"] = "dry-run"
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def write_markdown(prod: Path, plan: dict) -> Path:
    dest = prod / "03-storyboard" / "HANDOFF-VIDEO-EP01.md"
    lines = [
        "# 第 1 集 6.2 出片准备（Seedance 2.0 Mini 480P）",
        "",
        "本文件是正式出片前的交接，不是成片。**不要写 `shots.json`。**",
        "",
        "入口：",
        "",
        "```bash",
        "python3 scripts/render_seedance_packages.py \\",
        "  --prod productions/009-siem-reap \\",
        "  --dry-run",
        "```",
        "",
        "真出片时去掉 `--dry-run`，可加 `--only SH001`。抽出的尾帧写到 `05-shots/SHxxx-last.jpg`，不覆盖 `04-frames/SHxxx-last.jpg`。",
        "",
        f"- 镜头数：{plan['count']}",
        f"- 可派：{plan['ok_count']}",
        f"- 最难：{', '.join(plan['hardest']) or '—'}",
        "- 模型 / 分辨率：以 `.env` 的 `ARK_SEEDANCE_MODEL` / `ARK_RESOLUTION` 为准（当前约定 Mini + 480P）",
        "",
        "| 镜 | 模式 | 秒 | 首帧 | 设计尾帧 | 身份参考 | 最难 | 状态 |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for item in plan["shots"]:
        refs = ", ".join(f"`{rel}`" for rel in item.get("refs") or []) or "—"
        last = item.get("last_frame") or "—"
        status = "可派" if item.get("ok") else "; ".join(item.get("errors") or ["blocked"])
        if item.get("exists"):
            status = "已有 mp4，将跳过"
        lines.append(
            f"| {item['shot_id']} | {item.get('gen_mode')}→{item.get('seedance_mode')} | {item.get('duration_sec')} | `{item.get('first_frame')}` | `{last}` | {refs} | {'是' if item.get('hardest') else ''} | {status} |"
        )
    lines.extend(
        [
            "",
            "建议顺序：先 SH001 看脸和左右轴，再最难三镜 SH004 / SH013 / SH019，不要一次派 21 镜。",
            "flf 镜只交首尾帧：Ark 拒 last_frame 和 reference_image 混用。身份参考只给 i2v 镜。",
            "",
        ]
    )
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="已有 mp4 也重跑")
    args = parser.parse_args()
    prod = _prod(args.prod)
    if not prod.is_dir():
        raise SystemExit(f"没有这个项目：{prod}")
    plan = build_plan(prod, args.only)
    if not args.only:
        manifest = write_manifest(prod, plan)
        handoff = write_markdown(prod, plan)
        print(json.dumps({k: plan[k] for k in ("prod", "count", "ok_count", "hardest", "writes_shots_json", "overwrites_designed_last")}, ensure_ascii=False, indent=2))
        print(f"wrote {manifest.relative_to(ROOT)}")
        print(f"wrote {handoff.relative_to(ROOT)}")
    else:
        print(json.dumps({k: plan[k] for k in ("prod", "count", "ok_count", "hardest", "writes_shots_json", "overwrites_designed_last")}, ensure_ascii=False, indent=2))
        print("only=" + ",".join(args.only) + "; left full seedance_render_plan.json / HANDOFF-VIDEO-EP01.md alone")
    blocked = [item for item in plan["shots"] if not item.get("ok")]
    if blocked:
        raise SystemExit("还不能出片：" + ", ".join(item["shot_id"] + "(" + ";".join(item["errors"]) + ")" for item in blocked))
    if args.dry_run:
        print("dry-run only; no Ark task submitted")
        return
    render_plan(prod, plan, skip_existing=not args.force)


if __name__ == "__main__":
    main()
