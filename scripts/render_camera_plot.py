#!/usr/bin/env python3
"""Top-down camera plots from sets.json marks + cameras → 02-assets/scenes/<id>/camera-plot.png

    python3 scripts/render_camera_plot.py --prod productions/<slug> [--check]

`--check` only prints the axis report (180° rule, per-camera left→right order) and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.camera_plot import render_all, set_report  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prod", required=True)
    p.add_argument("--check", action="store_true", help="只打印轴线报告，不画图")
    args = p.parse_args()
    prod = Path(args.prod).resolve()
    sets_path = prod / "03-storyboard" / "sets.json"
    if not sets_path.exists():
        raise SystemExit(f"缺 {sets_path}")
    data = json.loads(sets_path.read_text(encoding="utf-8"))
    if args.check:
        for entry in data.get("sets") or []:
            report = set_report(entry)
            print(f"{report['id']}: axis {'–'.join(report['axis']) or '—'}; cameras {len(report['cameras'])}")
            for view in report["views"]:
                print(f"  {view['camera']:<8} {view['lens']:<6} left→right {' / '.join(view['left_to_right']) or '—'}  A看B {view['eyeline_a_to_b'] or '—'}")
            for problem in report["axis_problems"]:
                print(f"  ! {problem}")
        return
    result = render_all(prod, data)
    for rel in result["written"]:
        print(f"wrote {prod / rel}")
    for report in result["sets"]:
        for problem in report["axis_problems"]:
            print(f"! {report['id']}: {problem}")
    if not result["written"]:
        print("no set has marks or cameras; nothing to draw")


if __name__ == "__main__":
    main()
