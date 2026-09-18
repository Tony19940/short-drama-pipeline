#!/usr/bin/env python3
"""Stills animatic for review: locked keyframes cut to the shot table's seconds.

    python3 scripts/animatic.py --prod productions/<slug> [--episode 1] [--audio 07-dubbing/xxx.m4a] [--fps 24] [--plan]

Writes only 03-storyboard/animatic/epNN.animatic.mp4. Not a finish path; never enters 05-shots / 06-export.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.animatic import build_animatic, plan_animatic  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prod", required=True)
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--audio", default="", help="可选音轨（相对项目或绝对路径），只混进 animatic")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--plan", action="store_true", help="只打印每张卡的秒数，不出片")
    args = p.parse_args()
    prod = Path(args.prod).resolve()
    if not prod.exists():
        raise SystemExit(f"没有这个项目：{prod}")
    if args.plan:
        plan = plan_animatic(prod, args.episode)
        for item in plan:
            print(f"{item['shot_id']:<7} {item['seconds']:>6.2f}s  {'缺' if item['missing'] else '有'}  {item['label']}")
        print(f"共 {len(plan)} 张卡，{sum(i['seconds'] for i in plan):.1f} 秒")
        return
    try:
        result = build_animatic(prod, args.episode, audio=args.audio or None, fps=args.fps)
    except (PermissionError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
