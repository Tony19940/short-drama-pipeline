#!/usr/bin/env python3
"""E+ SFX bed: locked shot-table key_sfx + 05-shots durations -> one episode m4a.

Does not read or write 03-storyboard/shots.json. Does not mix VO or BGM.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import load_dotenv
from director.sfx import run_mix


def _prod(raw: str) -> Path:
    path = Path(raw)
    if path.is_dir():
        return path.resolve()
    root = SCRIPTS.parent / "productions" / raw
    return root.resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="已有 m4a 也重混")
    parser.add_argument("--no-preview", action="store_true", help="只出音频，不拼预览片")
    args = parser.parse_args()
    load_dotenv()
    prod = _prod(args.prod)
    result = run_mix(
        prod,
        episode=args.episode,
        dry_run=args.dry_run,
        force=args.force,
        preview=not args.no_preview,
    )
    print(json.dumps({k: result[k] for k in result if k != "sfx"}, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("dry-run only; no mix written")
        return
    if result.get("skipped"):
        print(result.get("note") or "already exists")
        return
    print(f"wrote {result.get('audio')}")
    if result.get("preview"):
        print(f"wrote {result.get('preview')}")


if __name__ == "__main__":
    main()
