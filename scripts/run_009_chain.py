#!/usr/bin/env python3
"""Run 009 writer -> shot table (header + per-scene) -> compiled specs, outside the 30s tool kill.

Usage: python3 scripts/run_009_chain.py [--target seedance_2_0] [--redo]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director.paths import prod_path  # noqa: E402
from director.pipeline import read_artifact  # noqa: E402
from director.station_agents import run_station_agent  # noqa: E402

PROD = prod_path("009-siem-reap")
PIPE = PROD / ".pipeline"
LOG = PIPE / "run_009_chain.log"
STATUS = PIPE / "chain.status.json"

WRITER_BRIEF = (
    "Adapt episode 1 of 暹粒 only. Do not write episodes 2-8 as scenes. "
    "Keep the 8-episode bible, but scenes[] must cover ep01 only: "
    "modern rain fall into the old channel, then ancient shoal capture and escape, then granary hook. "
    "Character names: 速卡 sokha, 云朗 yunlong. Guard can be 守卫. "
    "location_id must be modern-channel, ancient-shoal, granary. "
    "Copy dialogue lines from ep01.md verbatim. "
    "Each scene: heading, location_id, time_of_day, int_ext, present_cast, scene_job, whose_scene, "
    "start_state, end_state, action, dialogue[], mute_test=pass, unfilmable_check=pass, preach_check=pass. "
    "action is visible present-tense only. No 景别/运镜/焦段/机位/镜头推进. "
    "Aspect is 16:9. Origin is station-agent."
)
DESIGN_BRIEF = (
    "第 1 集《水认得旧路》。视点速卡。三场：现代旧河道坠河、古浅滩被俘与逃脱、粮栈水线钩子。"
    "证据：观众必须看清「手是空的 + 槽口断残」才知道她穿越了。测量杆坠河后不再出现；麻绳在哪一场脱掉要写明；粮栈换草绳。"
    "水路方向、高棉岸与暹罗对岸、粮栈门与柱的左右，一场一条轴写清。剧本里「再爬上岸时四周只剩芦苇」是时空省略，中间必须切。"
)


def log(message: str) -> None:
    PIPE.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%H:%M:%S ") + message
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
    STATUS.write_text(
        json.dumps(
            {
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "message": message,
                "writer": (PIPE / "writer.json").exists(),
                "shot_list": (PIPE / "shot_list.json").exists(),
                "shot_specs": (PIPE / "shot_specs.json").exists(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(line, flush=True)


def park_old(name: str, tag: str) -> None:
    src = PIPE / name
    if src.exists():
        dest = PIPE / f"{Path(name).stem}.{tag}.json"
        if not dest.exists():
            shutil.copy2(src, dest)
            log(f"parked {name} -> {dest.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="seedance_2_0")
    parser.add_argument("--redo", action="store_true", help="redo the shot table even if one exists")
    args = parser.parse_args()
    LOG.write_text("", encoding="utf-8")
    log("chain begin target=" + args.target)
    if not (PIPE / "writer.json").exists():
        run_station_agent(PROD, "writer", brief=WRITER_BRIEF)
        log("writer done")
    writer = read_artifact(PROD, "writer.json")
    log("writer scenes=" + str(len(writer.get("scenes") or [])))
    shot_list = read_artifact(PROD, "shot_list.json")
    if args.redo or shot_list.get("schema") != "shot-table-v2":
        park_old("shot_list.json", "v1-8shots" if shot_list and shot_list.get("schema") != "shot-table-v2" else "prev")
        park_old("shot_specs.json", "v1-8shots" if shot_list and shot_list.get("schema") != "shot-table-v2" else "prev")
        t0 = time.time()
        log("START design (shot-table-v2)")
        result = run_station_agent(PROD, "design", brief=DESIGN_BRIEF, target_model=args.target)
        log("OK design %.1fs shots=%d total_sec=%s" % (time.time() - t0, len(result["artifact"]["shots"]), result["artifact"].get("total_sec")))
        for report in result.get("scene_reports") or []:
            log("  " + json.dumps(report, ensure_ascii=False))
        for warning in result.get("warnings") or []:
            log("  warn " + warning)
        log("table -> " + str(result.get("table_md")))
    else:
        log("skip design, shot-table-v2 already exists")
    specs = read_artifact(PROD, "shot_specs.json")
    log("spec count=" + str(len(specs.get("shot_specs") or [])) + " origin=" + str(specs.get("origin")))
    log("DONE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log(traceback.format_exc())
        raise
