#!/usr/bin/env python3
"""CLI for Gate 0 reverse: video -> draft shots, optional Khmer localize."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from director.paths import load_dotenv, prod_path  # noqa: E402
from director.reverse import analyze_production, ingest_video, localize_production  # noqa: E402


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", required=True)
    parser.add_argument("--video", help="local mp4/mov/webm")
    parser.add_argument("--localize", action="store_true")
    parser.add_argument("--brief", default="")
    parser.add_argument("--no-grok", action="store_true")
    args = parser.parse_args()
    given = Path(args.prod)
    prod = given.resolve() if given.exists() else prod_path(args.prod)
    if args.video:
        info = ingest_video(prod, Path(args.video).resolve(), Path(args.video).name)
        print(f"stored {info['stored']} {info['duration']}s {info['aspect']}")
    result = analyze_production(prod, use_grok=not args.no_grok, brief=args.brief)
    print(f"analyzed {result['analysis']['shot_count']} shots origin={result['analysis']['origin']}")
    if args.localize:
        localized = localize_production(prod, brief=args.brief, use_grok=not args.no_grok)
        print(f"localized origin={localized['draft'].get('origin')} seeded={localized.get('seeded')}")


if __name__ == "__main__":
    main()
