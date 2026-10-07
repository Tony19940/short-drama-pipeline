#!/usr/bin/env python3
"""Run Xiaoyunque-aligned gates A/S/C before any video API."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    p.add_argument("--episode", default="1")
    p.add_argument("--revision", default="")
    args = p.parse_args(argv)
    prod = Path(args.prod).resolve()
    if not prod.is_dir():
        raise SystemExit(f"no such production {prod}")
    cmd = [sys.executable, str(ROOT / "scripts" / "check_storyboard.py"), "--prod", str(prod), "--episode", str(args.episode)]
    if args.revision:
        cmd.extend(["--revision", args.revision])
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
    print(f"check_prod ok: {prod.name}")


if __name__ == "__main__":
    main()
