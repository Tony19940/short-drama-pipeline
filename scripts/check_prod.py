#!/usr/bin/env python3
"""Run Xiaoyunque-aligned gates A/S/C before any video API."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    args = p.parse_args()
    prod = Path(args.prod).resolve()
    if not prod.is_dir():
        raise SystemExit(f"no such production {prod}")
    cmd = [sys.executable, str(ROOT / "scripts" / "check_storyboard.py"), "--prod", str(prod)]
    subprocess.check_call(cmd)
    print(f"check_prod ok: {prod.name}")


if __name__ == "__main__":
    main()
